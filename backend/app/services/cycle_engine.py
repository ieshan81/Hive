"""Unified strategy cycle — sync, radar, signals, risk, logging."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.database import StrategySignal, SystemHealth
from app.services.activity_logger import log_activity
from app.services.ai_fund_manager import AIFundManager
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.capital_buckets import bucket_for_asset_class, compute_buckets, compute_position_size
from app.services.config_manager import ConfigManager
from app.services.cycle_context import current_cycle_run_id
from app.services.cycle_persistence import verify_cycle_persistence
from app.services.market_radar_service import MarketRadarService
from app.services.memory_engine import MemoryEngine
from app.services.risk_engine import RiskEngine, TradeProposal
from app.services.session_engine import SessionEngine
from app.services.strategy_engine import StrategyEngine
from app.services import quant_math


def _asset_class_for_signal(sig: StrategySignal) -> str:
    if sig.asset_class:
        return sig.asset_class
    if sig.strategy == "crypto_night_momentum":
        return "crypto"
    if sig.strategy == "mean_reversion_pairs":
        return "stock"
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
        cycle_run_id = str(uuid.uuid4())
        token = current_cycle_run_id.set(cycle_run_id)
        try:
            return self._run_cycle(cycle_run_id)
        finally:
            current_cycle_run_id.reset(token)

    def _run_cycle(self, cycle_run_id: str) -> dict[str, Any]:
        self.strategies.cycle_run_id = cycle_run_id
        summary: dict[str, Any] = {
            "cycle_run_id": cycle_run_id,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "steps": [],
            "signals_generated": 0,
            "signals_created": 0,
            "signals_evaluated": 0,
            "blocked": 0,
            "approved": 0,
            "orders_submitted": 0,
            "errors": [],
            "paper_trading_only": True,
            "alpaca_configured": self.alpaca.configured,
        }

        log_activity(
            self.session,
            "cycle_start",
            "Strategy cycle started",
            {"cycle_run_id": cycle_run_id},
        )
        summary["steps"].append("cycle_start")

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
            {"configured": self.alpaca.configured, "cycle_run_id": cycle_run_id},
        )
        summary["steps"].append("alpaca_sync")

        session_state = self.session_engine.detect()
        summary["session"] = session_state.to_dict()
        log_activity(
            self.session,
            "session",
            f"Session mode: {session_state.mode}",
            {**session_state.to_dict(), "cycle_run_id": cycle_run_id},
        )
        summary["steps"].append("session")

        equity = account.equity if account else 0.0
        buckets = compute_buckets(equity, self.config)
        summary["capital_buckets"] = buckets.to_dict()
        summary["steps"].append("capital_buckets")

        candidates = self.radar.refresh(session_state)
        summary["radar_count"] = len(candidates)
        summary["steps"].append("market_radar")

        signals: list[StrategySignal] = []
        all_created: list[StrategySignal] = []

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
                    if sig:
                        all_created.append(sig)
                        if sig.signal != "hold":
                            signals.append(sig)
                if len(stock_symbols) >= 2:
                    sig = self.strategies.run_mean_reversion_pairs(stock_symbols[0], stock_symbols[1])
                    if sig:
                        all_created.append(sig)
                        if sig.signal != "hold":
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
                crypto_non_hold = 0
                for sym in crypto_symbols[:5]:
                    sig = self.strategies.run_crypto_night_momentum(sym)
                    if sig:
                        all_created.append(sig)
                        if sig.signal != "hold":
                            signals.append(sig)
                            crypto_non_hold += 1
                if crypto_non_hold:
                    self.strategies.set_state(
                        "crypto_night_momentum",
                        "active",
                        f"Generated {crypto_non_hold} crypto momentum signal(s)",
                    )
                elif all_created:
                    self.strategies.set_state("crypto_night_momentum", "inactive", "No eligible crypto signal")
                else:
                    self.strategies.set_state("crypto_night_momentum", "inactive", "Data unavailable for crypto symbols")
            else:
                reason = "Crypto data unavailable" if not candidates else "No eligible crypto pairs in radar"
                self.strategies.set_state("crypto_night_momentum", "inactive", reason)
        else:
            self._set_all_strategies_inactive("Market closed")

        summary["signals_generated"] = len(signals)
        summary["signals_created"] = len(all_created)
        summary["steps"].append("strategy_signals")
        self.session.commit()

        max_risk_pct = self.config.get("max_risk_per_trade", 0.01)
        max_strategy_pct = self.config.get("capital_allocation_rules", {}).get("max_per_strategy_pct", 0.5)

        for sig in signals:
            summary["signals_evaluated"] += 1
            approved = self._evaluate_signal(
                sig,
                cycle_run_id,
                session_state,
                account,
                equity,
                buckets,
                candidates,
                max_risk_pct,
                max_strategy_pct,
            )
            if approved:
                summary["approved"] += 1
            else:
                summary["blocked"] += 1

        meaningful_ai = (
            summary["signals_evaluated"] > 0
            or summary["blocked"] > 0
            or summary["approved"] > 0
            or (summary["signals_created"] > 0 and summary["radar_count"] > 0)
        )
        if meaningful_ai and self.ai.configured:
            from app.services.dashboard_service import build_dashboard

            dashboard = build_dashboard(self.session)
            review, ai_meta = self.ai.review(
                "cycle",
                {"cycle_summary": summary, "dashboard": dashboard},
                subject_id=cycle_run_id,
                cycle_run_id=cycle_run_id,
            )
            summary["ai_review_meta"] = ai_meta
            if review and ai_meta.get("ai_review_status") == "success":
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
            elif ai_meta.get("ai_review_status") == "failed":
                summary["errors"].append(
                    f"AI review failed: {ai_meta.get('ai_review_error_type')}: {ai_meta.get('ai_review_error_message')}"
                )
                log_activity(
                    self.session,
                    "ai_review_failed",
                    summary["errors"][-1],
                    ai_meta,
                )
            summary["steps"].append("ai_review")
        elif meaningful_ai:
            summary["ai_review_meta"] = {
                "ai_review_status": "skipped",
                "ai_review_error_message": "Gemini not configured",
            }

        summary["strategy_states"] = [
            {"strategy": s.strategy, "status": s.status, "reason": s.status_reason}
            for s in self.strategies.get_all_states()
        ]
        summary["ended_at"] = datetime.utcnow().isoformat() + "Z"
        summary["status"] = "ok" if account or not self.alpaca.configured else "partial"
        summary["message"] = (
            "Cycle completed — Alpaca not configured"
            if not self.alpaca.configured
            else "Cycle completed"
            if account
            else "Cycle completed without account sync — check Alpaca credentials"
        )

        health = self.session.get(SystemHealth, 1)
        if health is None:
            health = SystemHealth(id=1)
        health.alpaca_connected = account is not None
        health.database_connected = True
        health.gemini_configured = self.ai.configured
        health.last_account_sync = datetime.utcnow() if account else health.last_account_sync
        health.details = {"last_cycle": summary, "cycle_run_id": cycle_run_id}
        health.updated_at = datetime.utcnow()
        self.session.add(health)

        log_activity(
            self.session,
            "cycle_end",
            f"Cycle complete: {summary['signals_generated']} signals, {summary['blocked']} blocked, {summary['approved']} approved",
            summary,
        )
        self.session.commit()

        verify_cycle_persistence(self.session, summary)
        self.session.commit()
        return summary

    def _evaluate_signal(
        self,
        sig: StrategySignal,
        cycle_run_id: str,
        session_state,
        account,
        equity: float,
        buckets,
        candidates,
        max_risk_pct: float,
        max_strategy_pct: float,
    ) -> bool:
        asset_class = _asset_class_for_signal(sig)
        if not self.session_engine.asset_class_allowed(asset_class, session_state):
            self.risk.log_block(
                symbol=sig.symbol,
                strategy=sig.strategy,
                side=sig.side,
                reason="Market closed for asset class",
                check_name="market_session",
                signal_id=sig.id,
                cycle_run_id=cycle_run_id,
            )
            self.strategies.update_signal_status(
                sig.id,
                "blocked",
                {
                    "invalidation_reason": "Market closed",
                    "block_reason_code": "MARKET_CLOSED",
                },
            )
            log_activity(
                self.session,
                "signal_blocked",
                f"Blocked {sig.symbol}: market closed",
                {"signal_id": sig.id, "cycle_run_id": cycle_run_id},
            )
            self.session.commit()
            return False

        quote_sym = _quote_symbol(sig)
        quote = self.alpaca.get_quote(quote_sym, asset_class)
        if sig.side in ("buy", "buy_spread"):
            entry = quote["ask"] if quote else None
        elif sig.side == "sell":
            entry = quote["bid"] if quote else None
        else:
            entry = quote.get("mid") if quote else None

        if entry is None:
            self.risk.log_block(
                symbol=sig.symbol,
                strategy=sig.strategy,
                side=sig.side,
                reason="No quote available",
                check_name="no_quote",
                signal_id=sig.id,
                cycle_run_id=cycle_run_id,
            )
            self.strategies.update_signal_status(sig.id, "blocked", {"invalidation_reason": "No quote"})
            log_activity(
                self.session,
                "signal_blocked",
                f"Blocked {sig.symbol}: no quote",
                {"signal_id": sig.id, "cycle_run_id": cycle_run_id},
            )
            self.session.commit()
            return False

        stop = sig.stop_loss or (entry * 0.985 if "buy" in sig.side else entry * 1.015)
        risk_dollars = equity * max_risk_pct
        qty_by_risk = quant_math.position_quantity(risk_dollars, entry, stop) if equity > 0 else 0
        bucket_cap = bucket_for_asset_class(asset_class, buckets)
        qty_by_bucket = bucket_cap / entry if entry > 0 else 0
        qty_by_strategy = (equity * max_strategy_pct) / entry if entry > 0 and equity > 0 else 0
        qty_by_bp = account.buying_power / entry if account and entry > 0 else 0
        qty = compute_position_size(qty_by_risk, qty_by_bucket, qty_by_strategy, qty_by_bp)

        candidate_row = next(
            (c for c in candidates if c.symbol == sig.symbol or c.symbol == quote_sym),
            None,
        )
        spread_pct = candidate_row.spread_pct if candidate_row else (quote.get("spread_pct") if quote else None)

        proposal = TradeProposal(
            symbol=sig.symbol,
            side="buy" if "buy" in sig.side else "sell",
            quantity=qty,
            entry_price=entry,
            stop_loss=stop,
            take_profit=sig.take_profit,
            strategy=sig.strategy,
            spread_pct=spread_pct,
            liquidity_score=candidate_row.liquidity_score if candidate_row else None,
            asset_class=asset_class,
            signal_id=sig.id,
            signal_confidence=sig.confidence,
            cycle_run_id=cycle_run_id,
        )
        decision = self.risk.evaluate(proposal, session_state=session_state)
        if decision.approved:
            self.strategies.update_signal_status(sig.id, "approved_no_order", {"execution": "disabled_in_mvp"})
            log_activity(
                self.session,
                "signal_approved",
                f"Approved {sig.signal} {sig.symbol} (paper only — no order submitted)",
                {"strategy": sig.strategy, "qty": qty, "signal_id": sig.id, "cycle_run_id": cycle_run_id},
            )
            self.session.commit()
            return True

        self.strategies.update_signal_status(
            sig.id,
            "blocked",
            {
                "invalidation_reason": decision.human_reason or "; ".join(decision.reasons),
                "block_reason_code": decision.block_reason_code,
                "risk_rule": decision.risk_rule,
            },
        )
        log_activity(
            self.session,
            "signal_blocked",
            f"Blocked {sig.symbol}: {decision.human_reason or '; '.join(decision.reasons)}",
            {
                "signal_id": sig.id,
                "cycle_run_id": cycle_run_id,
                "block_reason_code": decision.block_reason_code,
                "reasons": decision.reasons,
            },
        )
        self.session.commit()
        return False

    def _set_all_strategies_inactive(self, reason: str) -> None:
        for name in StrategyEngine.ALL_STRATEGIES:
            self.strategies.set_state(name, "inactive", reason)
