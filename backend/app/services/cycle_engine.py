"""Unified strategy cycle — sync, radar, signals, risk, logging."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.database import StrategySignal, SystemHealth
from app.services.activity_logger import log_activity
from app.services.ai_fund_manager import AIFundManager
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.capital_buckets import bucket_for_asset_class, compute_buckets, compute_position_size
from app.services.config_manager import ConfigManager
from app.services.market_radar_service import MarketRadarService
from app.services.memory_engine import MemoryEngine
from app.services.risk_engine import RiskEngine, TradeProposal
from app.services.session_engine import SessionEngine
from app.services.strategy_engine import StrategyEngine
from app.services import quant_math


def _asset_class_for_signal(sig: StrategySignal) -> str:
    if sig.strategy == "crypto_night_momentum":
        return "crypto"
    if sig.strategy == "mean_reversion_pairs":
        return "stock"
    sym = sig.symbol.upper()
    if "/" in sym and sym.endswith("/USD"):
        return "crypto"
    return "stock"


def _quote_symbol(sig: StrategySignal) -> str:
    if sig.strategy == "mean_reversion_pairs":
        return sig.symbol.split("/")[0]
    if _asset_class_for_signal(sig) == "crypto":
        return normalize_crypto_symbol(sig.symbol)
    return sig.symbol.split("/")[0]


class CycleEngine:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)
        self.session_engine = SessionEngine()
        self.radar = MarketRadarService(session, self.config)
        self.strategies = StrategyEngine(session, self.config)
        self.risk = RiskEngine(session)
        self.ai = AIFundManager(session)

    def run(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "started_at": datetime.utcnow().isoformat() + "Z",
            "steps": [],
            "signals_generated": 0,
            "signals_evaluated": 0,
            "blocked": 0,
            "approved": 0,
            "paper_trading_only": True,
            "alpaca_configured": self.alpaca.configured,
        }

        log_activity(self.session, "cycle_start", "Strategy cycle started")
        summary["steps"].append("cycle_start")

        # 1. Sync Alpaca (continue cycle even if sync fails)
        account = None
        positions = []
        if self.alpaca.configured:
            account = self.alpaca.sync_account()
            positions = self.alpaca.sync_positions()
        summary["account_synced"] = account is not None
        summary["positions_count"] = len(positions)
        log_activity(
            self.session,
            "alpaca_sync",
            f"Synced account equity={account.equity if account else 'N/A'}, positions={len(positions)}",
            {"configured": self.alpaca.configured},
        )
        summary["steps"].append("alpaca_sync")

        # 2. Session mode
        session_state = self.session_engine.detect()
        summary["session"] = session_state.to_dict()
        log_activity(self.session, "session", f"Session mode: {session_state.mode}", session_state.to_dict())
        summary["steps"].append("session")

        # 3. Capital buckets
        equity = account.equity if account else 0.0
        buckets = compute_buckets(equity, self.config)
        summary["capital_buckets"] = buckets.to_dict()
        summary["steps"].append("capital_buckets")

        # 4. Refresh market radar (session-aware)
        candidates = self.radar.refresh(session_state)
        summary["radar_count"] = len(candidates)
        summary["steps"].append("market_radar")

        # 5. Generate strategy signals + update strategy states
        signals: list[StrategySignal] = []

        stock_symbols = [c.symbol for c in candidates if c.asset_class == "stock" and c.eligibility == "eligible"][:8]
        crypto_symbols = [c.symbol for c in candidates if c.asset_class == "crypto" and c.eligibility == "eligible"][:5]

        if not self.alpaca.configured:
            self._set_all_strategies_inactive("Alpaca not configured")
        elif account is None:
            self._set_all_strategies_inactive("Waiting for Alpaca sync")
        elif session_state.stock_trading_allowed:
            if stock_symbols:
                for sym in stock_symbols[:5]:
                    sig = self.strategies.run_momentum_orb(sym)
                    if sig and sig.signal != "hold":
                        signals.append(sig)
                if len(stock_symbols) >= 2:
                    sig = self.strategies.run_mean_reversion_pairs(stock_symbols[0], stock_symbols[1])
                    if sig and sig.signal != "hold":
                        signals.append(sig)
                self.strategies.set_state("momentum_orb", "active", "Stock session — signals evaluated")
                self.strategies.set_state("mean_reversion_pairs", "active", "Pairs research active")
            else:
                self.strategies.set_state("momentum_orb", "inactive", "No eligible stock symbols in radar")
                self.strategies.set_state("mean_reversion_pairs", "inactive", "No eligible stock symbols for pairs")
            self.strategies.set_state("crypto_night_momentum", "inactive", "Stock session — crypto strategy disabled")
        elif session_state.mode == "crypto_night":
            self.strategies.set_state("momentum_orb", "inactive", "US stock market closed")
            self.strategies.set_state("mean_reversion_pairs", "inactive", "US stock market closed")
            if crypto_symbols:
                self.strategies.set_state(
                    "crypto_night_momentum",
                    "inactive",
                    "Crypto night session — placeholder until crypto momentum implemented",
                )
            else:
                reason = "Crypto data unavailable" if not candidates else "No eligible crypto pairs in radar"
                self.strategies.set_state("crypto_night_momentum", "inactive", reason)
        else:
            self.strategies.set_state("momentum_orb", "inactive", "Market closed")
            self.strategies.set_state("mean_reversion_pairs", "inactive", "Market closed")
            self.strategies.set_state("crypto_night_momentum", "inactive", "Market closed")

        summary["signals_generated"] = len(signals)
        summary["steps"].append("strategy_signals")

        # 6. Risk evaluate each non-hold signal
        max_risk_pct = self.config.get("max_risk_per_trade", 0.01)
        max_strategy_pct = self.config.get("capital_allocation_rules", {}).get("max_per_strategy_pct", 0.5)

        for sig in signals:
            summary["signals_evaluated"] += 1
            asset_class = _asset_class_for_signal(sig)
            if not self.session_engine.asset_class_allowed(asset_class, session_state):
                self.risk.log_block(
                    symbol=sig.symbol,
                    strategy=sig.strategy,
                    side=sig.signal,
                    reason="Market closed for asset class",
                    check_name="market_session",
                )
                summary["blocked"] += 1
                continue

            quote_sym = _quote_symbol(sig)
            quote = self.alpaca.get_quote(quote_sym, asset_class)
            entry = quote["ask"] if quote and sig.signal in ("buy", "buy_spread") else (quote["bid"] if quote else None)
            if entry is None:
                self.risk.log_block(
                    symbol=sig.symbol,
                    strategy=sig.strategy,
                    side=sig.signal,
                    reason="No quote available",
                    check_name="no_quote",
                )
                summary["blocked"] += 1
                continue

            stop = entry * 0.985 if sig.signal in ("buy", "buy_spread") else entry * 1.015
            risk_dollars = equity * max_risk_pct
            qty_by_risk = quant_math.position_quantity(risk_dollars, entry, stop) if equity > 0 else 0
            bucket_cap = bucket_for_asset_class(asset_class, buckets)
            qty_by_bucket = bucket_cap / entry if entry > 0 else 0
            qty_by_strategy = (equity * max_strategy_pct) / entry if entry > 0 and equity > 0 else 0
            qty_by_bp = (account.buying_power / entry if account and entry > 0 else 0)
            qty = compute_position_size(qty_by_risk, qty_by_bucket, qty_by_strategy, qty_by_bp)

            candidate_row = next(
                (c for c in candidates if c.symbol == sig.symbol or c.symbol == quote_sym),
                None,
            )
            spread_pct = candidate_row.spread_pct if candidate_row else (quote.get("spread_pct") if quote else None)

            proposal = TradeProposal(
                symbol=sig.symbol,
                side="buy" if "buy" in sig.signal else "sell",
                quantity=qty,
                entry_price=entry,
                stop_loss=stop,
                strategy=sig.strategy,
                spread_pct=spread_pct,
                liquidity_score=candidate_row.liquidity_score if candidate_row else None,
                asset_class=asset_class,
            )
            decision = self.risk.evaluate(proposal, session_state=session_state)
            if decision.approved:
                summary["approved"] += 1
                log_activity(
                    self.session,
                    "signal_approved",
                    f"Approved {sig.signal} {sig.symbol} (paper only — no order submitted in cycle)",
                    {"strategy": sig.strategy, "qty": qty},
                )
            else:
                summary["blocked"] += 1

        # 7. AI review only if real activity this cycle
        if (summary["signals_evaluated"] > 0 or summary["blocked"] > 0) and self.ai.configured:
            from app.services.dashboard_service import build_dashboard

            dashboard = build_dashboard(self.session)
            review = self.ai.review("cycle", {"cycle_summary": summary, "dashboard": dashboard})
            if review:
                payload = review.payload or {}
                mem = payload.get("memory_to_create")
                if mem:
                    MemoryEngine(self.session).create_memory(
                        memory_type=mem.get("memory_type", "lesson"),
                        event=mem.get("event", "cycle_review"),
                        lesson=mem.get("lesson", review.summary),
                        symbol=mem.get("symbol"),
                        strategy=mem.get("strategy"),
                    )
                summary["ai_review"] = review.decision
            summary["steps"].append("ai_review")

        # Update system health snapshot
        health = self.session.get(SystemHealth, 1)
        if health is None:
            health = SystemHealth(id=1)
        health.alpaca_connected = account is not None
        health.database_connected = True
        health.gemini_configured = self.ai.configured
        health.last_account_sync = datetime.utcnow() if account else health.last_account_sync
        health.details = {
            "last_cycle": summary,
            "activity_logged": True,
            "strategy_states_count": len(self.strategies.get_all_states()),
            "radar_count": len(candidates),
        }
        health.updated_at = datetime.utcnow()
        self.session.add(health)
        self.session.commit()

        log_activity(
            self.session,
            "cycle_end",
            f"Cycle complete: {summary['signals_generated']} signals, {summary['blocked']} blocked, {summary['approved']} approved",
            summary,
        )
        summary["status"] = "ok" if account or not self.alpaca.configured else "partial"
        summary["message"] = (
            "Cycle completed — Alpaca not configured"
            if not self.alpaca.configured
            else "Cycle completed"
            if account
            else "Cycle completed without account sync — check Alpaca credentials"
        )
        summary["activity_count"] = len(self.strategies.get_all_states())
        summary["strategy_states_updated"] = True
        summary["ended_at"] = datetime.utcnow().isoformat() + "Z"
        return summary

    def _set_all_strategies_inactive(self, reason: str) -> None:
        for name in StrategyEngine.ALL_STRATEGIES:
            self.strategies.set_state(name, "inactive", reason)
