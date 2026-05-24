"""Unified strategy cycle — sync, radar, signals, risk, logging."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.database import PositionSnapshot, StrategySignal, SystemHealth
from app.services.activity_logger import log_activity
from app.services.ai_fund_manager import AIFundManager
from app.services.ai_lab_service import build_compact_cycle_context, deterministic_cycle_summary
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.capital_buckets import compute_buckets
from app.services.config_manager import ConfigManager
from app.services.crypto_push_pull import CryptoPushPullStrategy
from app.services.cycle_context import current_cycle_run_id
from app.services.cycle_persistence import verify_cycle_persistence
from app.services.market_radar_service import MarketRadarService
from app.services.memory_engine import MemoryEngine
from app.services.risk_engine import RiskEngine
from app.services.session_engine import SessionEngine
from app.services.signal_utils import is_tradeable_signal
from app.services.strategy_engine import StrategyEngine
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.signal_pipeline import SignalPipeline
from app.services.portfolio_gate import PortfolioGate
from app.services.execution_policy import ExecutionPolicy
from app.services.symbol_tier_service import SymbolTierService
from app.services.engine_config import current_promotion_stage


def _asset_class_for_signal(sig: StrategySignal) -> str:
    if sig.asset_class:
        return sig.asset_class
    if sig.strategy in ("crypto_night_momentum", "crypto_push_pull"):
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
        self.ai_budget = AIBudgetGuard(session)
        self.positions: list[PositionSnapshot] = []

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
            "observations": 0,
            "entries": 0,
            "exits": 0,
            "blocked": 0,
            "approved": 0,
            "risk_approved": 0,
            "portfolio_deferred": 0,
            "portfolio_blocked": 0,
            "selected_for_execution": 0,
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
        if self.alpaca.configured:
            account = self.alpaca.sync_account()
            self.positions = self.alpaca.sync_positions()
        else:
            self.positions = []
        summary["account_synced"] = account is not None
        summary["positions_count"] = len([p for p in self.positions if (p.qty or 0) > 0])
        summary["account_equity"] = account.equity if account else 0
        log_activity(
            self.session,
            "alpaca_sync",
            f"Synced equity={account.equity if account else 'N/A'}, positions={summary['positions_count']}",
            {"cycle_run_id": cycle_run_id, "positions_count": summary["positions_count"]},
        )
        summary["steps"].append("alpaca_sync")

        session_state = self.session_engine.detect()
        summary["session"] = session_state.to_dict()
        summary["steps"].append("session")

        equity = account.equity if account else 0.0
        cash = account.cash if account else 0.0
        buckets = compute_buckets(equity, self.config)
        summary["capital_buckets"] = buckets.to_dict()
        summary["steps"].append("capital_buckets")

        candidates = self.radar.refresh(session_state)
        summary["radar_count"] = len(candidates)
        summary["steps"].append("market_radar")

        tradeable: list[StrategySignal] = []
        all_created: list[StrategySignal] = []

        stock_symbols = [c.symbol for c in candidates if c.asset_class == "stock" and c.eligibility == "eligible"][:8]
        crypto_symbols = [c.symbol for c in candidates if c.asset_class == "crypto" and c.eligibility in ("eligible", "caution")][:8]

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
                        if is_tradeable_signal(sig):
                            tradeable.append(sig)
                if len(stock_symbols) >= 2:
                    sig = self.strategies.run_mean_reversion_pairs(stock_symbols[0], stock_symbols[1])
                    if sig:
                        all_created.append(sig)
                        if is_tradeable_signal(sig):
                            tradeable.append(sig)
            self.strategies.set_state("crypto_push_pull", "inactive", "Stock session — crypto disabled")
            self.strategies.set_state("crypto_night_momentum", "inactive", "Legacy strategy inactive")
        elif session_state.mode == "crypto_night":
            self.strategies.set_state("momentum_orb", "inactive", "US stock market closed")
            self.strategies.set_state("mean_reversion_pairs", "inactive", "US stock market closed")
            self.strategies.set_state("crypto_night_momentum", "inactive", "Replaced by crypto_push_pull")

            cpp = CryptoPushPullStrategy(self.session, self.config, self.alpaca)
            cpp.cycle_run_id = cycle_run_id
            entries = exits = obs = 0
            cand_map = {c.symbol: c for c in candidates}
            for sym in crypto_symbols[:8]:
                c_row = cand_map.get(sym)
                sig = cpp.evaluate(
                    sym,
                    positions=self.positions,
                    liquidity_score=c_row.liquidity_score if c_row else None,
                    spread_pct=c_row.spread_pct if c_row else None,
                    eligibility=c_row.eligibility if c_row else "eligible",
                )
                if not sig:
                    continue
                all_created.append(sig)
                st = (sig.signal_type or "entry").lower()
                if st == "observation":
                    obs += 1
                    summary["observations"] = summary.get("observations", 0) + 1
                elif st == "entry":
                    entries += 1
                    tradeable.append(sig)
                elif st == "exit":
                    exits += 1
                    tradeable.append(sig)

            summary["entries"] = entries
            summary["exits"] = exits
            if tradeable:
                self.strategies.set_state(
                    "crypto_push_pull",
                    "active",
                    f"Generated {entries} entry, {exits} exit, {obs} observation(s)",
                )
            elif obs:
                self.strategies.set_state(
                    "crypto_push_pull",
                    "active",
                    f"{obs} observation(s) — no tradeable signals",
                )
            else:
                self.strategies.set_state("crypto_push_pull", "inactive", "No crypto push-pull signals")
        else:
            self._set_all_strategies_inactive("Market closed")

        summary["signals_generated"] = len(tradeable)
        summary["signals_created"] = len(all_created)
        summary["steps"].append("strategy_signals")
        self.session.commit()

        pipeline = SignalPipeline(self.session, self.config, self.alpaca, self.risk)
        risk_approved_entries: list = []
        risk_approved_exits: list = []
        daily_pl = account.daily_pl_pct if account else 0
        dd = account.drawdown_pct if account else 0

        for sig in tradeable:
            summary["signals_evaluated"] += 1
            cand, status, meta = pipeline.evaluate_tradeable(
                sig,
                cycle_run_id=cycle_run_id,
                session_state=session_state,
                account=account,
                equity=equity,
                cash=cash,
                buckets=buckets,
                candidates=candidates,
                positions=self.positions,
                daily_pl_pct=daily_pl or 0,
                drawdown_pct=dd or 0,
            )
            if cand is None:
                summary["blocked"] += 1
                code = (meta or {}).get("block_reason_code", "RISK_BLOCKED")
                self.risk.log_block(
                    symbol=sig.symbol,
                    strategy=sig.strategy,
                    side=sig.side,
                    reason=(meta or {}).get("invalidation_reason", code),
                    check_name=code.lower(),
                    signal_id=sig.id,
                    cycle_run_id=cycle_run_id,
                    evidence=meta,
                )
                self.strategies.update_signal_status(sig.id, status, meta or {})
            else:
                summary["risk_approved"] += 1
                self.strategies.update_signal_status(
                    sig.id,
                    "risk_approved",
                    {
                        "gates": meta,
                        "tier": cand.tier,
                        "position_qty": cand.position_qty,
                        "atr14": cand.atr14,
                        "edge_over_cost": cand.edge_over_cost,
                    },
                )
                if cand.signal_type == "entry":
                    risk_approved_entries.append(cand)
                else:
                    risk_approved_exits.append(cand)

        self.session.commit()

        gate = PortfolioGate(self.session, self.config, self.alpaca)
        pg_result = gate.run(
            cycle_run_id,
            risk_approved_entries + risk_approved_exits,
            equity=equity,
            cash=cash,
            buying_power=account.buying_power if account else 0,
            positions=self.positions,
            open_order_symbols=set(),
            promotion_stage=current_promotion_stage(self.config),
        )
        summary["portfolio_deferred"] = pg_result.deferred_count
        summary["portfolio_blocked"] = pg_result.blocked_count
        summary["selected_for_execution"] = len(pg_result.selected)

        quote_map: dict = {}
        for cand in pg_result.selected:
            qs = normalize_crypto_symbol(cand.symbol)
            quote_map[cand.symbol] = self.alpaca.get_quote(qs, "crypto") or {}

        open_order_syms = {o.get("symbol") for o in self.alpaca.get_open_orders()}
        dec_by_signal = {d.signal_id: d for d in pg_result.decisions}

        exec_policy = ExecutionPolicy(
            self.session,
            self.config,
            self.alpaca,
            SymbolTierService(self.config),
        )
        exec_logs = exec_policy.process_selected(
            cycle_run_id,
            pg_result.selected,
            quote_by_symbol=quote_map,
            portfolio_decision_by_signal=dec_by_signal,
            account=account,
            positions=self.positions,
            open_order_symbols=open_order_syms,
        )

        for cand in risk_approved_entries + risk_approved_exits:
            dec = dec_by_signal.get(cand.signal_id)
            if dec and dec.selected_for_execution:
                log = next((l for l in exec_logs if l.signal_id == cand.signal_id), None)
                if log and log.status in (
                    "paper_order_submitted",
                    "paper_order_filled",
                    "paper_order_partially_filled",
                ):
                    summary["orders_submitted"] += 1
                    self.strategies.update_signal_status(
                        cand.signal_id,
                        log.status,
                        {
                            "execution_log_id": log.event_id,
                            "broker_order_id": log.broker_order_id,
                            "client_order_id": log.broker_client_order_id,
                        },
                    )
                    summary["approved"] += 1
                elif log and log.status == "preflight_blocked":
                    self.strategies.update_signal_status(
                        cand.signal_id,
                        "preflight_blocked",
                        {
                            "block_reason_code": log.reject_reason,
                            "invalidation_reason": (log.gates_failed_json or {}).get("reason"),
                            "portfolio_rank": dec.portfolio_rank,
                        },
                    )
                elif log and log.reject_reason == "PAPER_EXECUTION_DISABLED":
                    self.strategies.update_signal_status(
                        cand.signal_id,
                        "approved_no_order",
                        {
                            "block_reason_code": "PAPER_EXECUTION_DISABLED",
                            "invalidation_reason": "Portfolio selected; paper execution disabled",
                            "portfolio_rank": dec.portfolio_rank,
                        },
                    )
                    summary["approved"] += 1
                elif log and log.status in ("paper_order_rejected", "paper_order_cancelled", "paper_order_unfilled"):
                    self.strategies.update_signal_status(
                        cand.signal_id,
                        log.status,
                        {"block_reason_code": log.reject_reason, "broker_order_id": log.broker_order_id},
                    )
                else:
                    self.strategies.update_signal_status(
                        cand.signal_id,
                        log.status if log else "selected_for_execution",
                        {"portfolio_rank": dec.portfolio_rank},
                    )
                    if log and log.status not in ("preflight_blocked",):
                        summary["approved"] += 1
            elif dec and dec.portfolio_status == "portfolio_deferred":
                self.strategies.update_signal_status(
                    cand.signal_id,
                    "portfolio_deferred",
                    {
                        "block_reason_code": dec.portfolio_reason_code,
                        "invalidation_reason": dec.human_reason,
                        "portfolio_rank": dec.portfolio_rank,
                    },
                )
            elif dec and dec.portfolio_status == "portfolio_blocked":
                self.strategies.update_signal_status(
                    cand.signal_id,
                    "portfolio_blocked",
                    {
                        "block_reason_code": dec.portfolio_reason_code,
                        "invalidation_reason": dec.human_reason,
                    },
                )
            elif dec and dec.portfolio_status == "portfolio_approved" and not dec.selected_for_execution:
                self.strategies.update_signal_status(cand.signal_id, "portfolio_approved", {"portfolio_rank": dec.portfolio_rank})

        self.session.commit()

        meaningful_ai = summary["signals_evaluated"] > 0 or summary["blocked"] > 0 or summary["observations"] > 0
        allow, reason = self.ai_budget.allow_review()
        if meaningful_ai and self.ai.configured and allow:
            ctx = build_compact_cycle_context(self.session, cycle_run_id, summary)
            review, ai_meta = self.ai.review(
                "cycle",
                ctx,
                subject_id=cycle_run_id,
                cycle_run_id=cycle_run_id,
                mode="quick",
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
                log_activity(self.session, "ai_review_failed", summary["errors"][-1], ai_meta)
            summary["steps"].append("ai_review")
        else:
            fb = deterministic_cycle_summary(self.session, cycle_run_id, summary)
            summary["fallback_summary"] = fb
            summary["ai_review_meta"] = {
                "ai_review_status": "skipped_budget_guard" if not allow else "skipped",
                "ai_review_error_message": reason if not allow else "Gemini not configured or no meaningful activity",
                "fallback_summary_source": "system",
            }
            if meaningful_ai and not allow:
                log_activity(
                    self.session,
                    "ai_review_skipped",
                    f"AI review skipped: {reason}",
                    {"cycle_run_id": cycle_run_id, "budget": self.ai_budget.status()},
                )

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
            else "Cycle completed without account sync"
        )

        health = self.session.get(SystemHealth, 1) or SystemHealth(id=1)
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
            f"Cycle: {summary['signals_generated']} tradeable, {summary['observations']} obs, {summary['blocked']} blocked",
            summary,
        )
        self.session.commit()

        from app.services.memory_cycle_processor import process_cycle_memories

        truth_msg = None
        if summary.get("orders_submitted", 0) > 0:
            truth_msg = f"orders_submitted={summary['orders_submitted']}"
        try:
            summary["memory"] = process_cycle_memories(
                self.session,
                cycle_run_id,
                summary,
                dashboard_truth_message=truth_msg,
            )
            self.session.commit()
        except Exception as exc:
            summary["memory_error"] = str(exc)

        verify_cycle_persistence(self.session, summary)
        self.session.commit()
        return summary

    def _set_all_strategies_inactive(self, reason: str) -> None:
        for name in StrategyEngine.ALL_STRATEGIES:
            self.strategies.set_state(name, "inactive", reason)
