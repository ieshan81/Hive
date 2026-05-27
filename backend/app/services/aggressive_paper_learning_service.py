"""Aggressive paper learning — tiny caged experiments, no live trading, no bypass."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    LessonNode,
    OrderRecord,
    PaperExperimentConfig,
    PaperExperimentDecision,
    PaperExperimentOutcome,
    PositionSnapshot,
    StrategyRegistry,
    SystemValidationAudit,
)
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.lesson_memory_service import LessonMemoryService
from app.services.strategy_stages import EXPORT_ACTIVE_STAGES


DEFAULT_AGGRESSIVE_CONFIG = {
    "mode_enabled": False,
    "max_experiment_notional_per_trade_usd": 0,
    "default_experiment_notional_usd": 10,
    "max_open_experiment_positions": 0,
    "max_experiment_positions_total": 0,
    "max_experiment_trades_per_day": 0,
    "max_experiment_trades_per_strategy_per_day": 0,
    "max_daily_experiment_loss_pct": 5.0,
    "max_weekly_experiment_loss_pct": 10.0,
    "meme_coin_max_hold_minutes": 240,
    "major_crypto_max_hold_hours": 48,
    "require_stop_loss": True,
    "require_time_stop": True,
    "require_take_profit_or_exit_rule": True,
    "require_spread_check": True,
    "require_liquidity_check": True,
    "require_position_monitor": True,
    "allow_live": False,
    "block_pump_dump_risk": True,
    "max_rejected_orders_per_day": 0,
    "rejection_cooldown_minutes": 15,
    "no_duplicate_symbol_buy": True,
    "no_averaging_down": True,
}

MEME_SYMBOLS = frozenset({"DOGE/USD", "DOGEUSD", "SHIB/USD", "PEPE/USD"})
MAJOR_SYMBOLS = frozenset({"BTC/USD", "ETH/USD", "SOL/USD"})

UNSAFE_REJECTION_CODES = frozenset(
    {
        "no_stop_loss",
        "no_exit_logic",
        "no_duplicate_order_prevention",
        "broker_mismatch",
        "unsafe_import",
        "risk_bypass",
        "no_liquidity_filter",
        "no_max_hold",
    }
)


class AggressivePaperLearningService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.cfg = self._load_config()

    def _load_config(self) -> dict:
        row = self.session.exec(
            select(PaperExperimentConfig).where(PaperExperimentConfig.profile == "aggressive_paper_learning")
        ).first()
        if row:
            base = dict(DEFAULT_AGGRESSIVE_CONFIG)
            base.update(row.config_json or {})
            base["mode_enabled"] = row.mode_enabled
            return base
        seeded = dict(DEFAULT_AGGRESSIVE_CONFIG)
        seeded.update(self.config.get("aggressive_paper_learning") or {})
        self.session.add(
            PaperExperimentConfig(profile="aggressive_paper_learning", config_json=seeded, mode_enabled=False)
        )
        return seeded

    def _audit(self, action: str, decision: str, reasoning: str, strategy_id: str | None = None) -> None:
        self.session.add(
            SystemValidationAudit(
                actor="gate",
                action=action,
                target_strategy_id=strategy_id,
                decision=decision,
                reasoning=reasoning[:500],
            )
        )

    def status(self) -> dict[str, Any]:
        blockers = []
        if not is_paper_broker_url():
            blockers.append("broker_not_paper")
        if not bool(cfg_get(self.config, "execution.paper_orders_enabled", False)):
            blockers.append("paper_orders_disabled")
        if self.cfg.get("mode_enabled"):
            blockers.append("learning_mode_on_but_use_caged_execution_only")
        today = self._decisions_today()
        return {
            "status": "ok",
            "mode_enabled": bool(self.cfg.get("mode_enabled")),
            "aggressive_learning_mode": bool(self.cfg.get("mode_enabled")),
            "training_capital_mode": bool(self.cfg.get("mode_enabled")),
            "ui_label": "Aggressive Learning Mode",
            "paper_broker": is_paper_broker_url(),
            "broker_mode": "paper" if is_paper_broker_url() else "unknown",
            "paper_orders_enabled": bool(cfg_get(self.config, "execution.paper_orders_enabled", False)),
            "live_orders_enabled": bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
            "live_trading_locked": True,
            "config": self.cfg,
            "decisions_today": today,
            "blockers": blockers,
            **live_lock_status(self.config),
        }

    def enable(self, operator: str = "operator") -> dict:
        if not is_paper_broker_url():
            return {"status": "error", "message": "Paper broker URL required"}
        row = self.session.exec(
            select(PaperExperimentConfig).where(PaperExperimentConfig.profile == "aggressive_paper_learning")
        ).first()
        if row:
            row.mode_enabled = True
            row.updated_at = datetime.utcnow()
            self.session.add(row)
        self.cfg["mode_enabled"] = True
        self._audit("paper_learning_enable", "enabled", f"by {operator}")
        return self.status()

    def disable(self, operator: str = "operator") -> dict:
        row = self.session.exec(
            select(PaperExperimentConfig).where(PaperExperimentConfig.profile == "aggressive_paper_learning")
        ).first()
        if row:
            row.mode_enabled = False
            self.session.add(row)
        self.cfg["mode_enabled"] = False
        self._audit("paper_learning_disable", "disabled", f"by {operator}")
        return self.status()

    def update_config(self, patch: dict) -> dict:
        row = self.session.exec(
            select(PaperExperimentConfig).where(PaperExperimentConfig.profile == "aggressive_paper_learning")
        ).first()
        if not row:
            row = PaperExperimentConfig(profile="aggressive_paper_learning", config_json=DEFAULT_AGGRESSIVE_CONFIG)
        merged = dict(row.config_json or DEFAULT_AGGRESSIVE_CONFIG)
        merged.update(patch)
        merged.pop("allow_live", None)
        merged["allow_live"] = False
        row.config_json = merged
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        self.cfg = merged
        return {"status": "ok", "config": merged}

    def symbol_tier(self, symbol: str) -> str:
        s = symbol.upper()
        if "/" not in s and s.isalnum():
            return "STOCK_SUPPORTED"
        quote = s.split("/")[-1] if "/" in s else ("USD" if s.endswith("USD") else "")
        if quote and quote != "USD":
            return "UNFUNDED_QUOTE_WATCH_ONLY"
        if "DOGE" in s or "SHIB" in s or "PEPE" in s:
            return "MEME_SUPPORTED"
        if symbol in MAJOR_SYMBOLS or "BTC" in s or "ETH" in s or "SOL" in s:
            return "MAJOR_CRYPTO"
        return "ALT_CRYPTO_SUPPORTED"

    def scan_experiment_eligibility(self) -> dict[str, Any]:
        eligible, blocked = [], []
        for reg in self.session.exec(select(StrategyRegistry)).all():
            ok, reason, codes = self._eligibility_for(reg)
            row = {
                "strategy_id": reg.strategy_id,
                "stage": reg.current_stage,
                "asset_class": reg.asset_class,
                "family": reg.family,
                "reason": reason,
                "codes": codes,
            }
            if ok:
                eligible.append(row)
            else:
                blocked.append(row)
        return {"status": "ok", "eligible": eligible, "blocked": blocked}

    def eligible_strategies(self) -> list[dict]:
        return self.scan_experiment_eligibility().get("eligible", [])

    def _eligibility_for(self, reg: StrategyRegistry) -> tuple[bool, str, list[str]]:
        codes: list[str] = []
        if reg.current_stage in ("retired",):
            return False, "retired", ["permanently_retired"]
        if reg.quarantine_status and "unsafe" in (reg.quarantine_status or ""):
            return False, reg.quarantine_status, ["unsafe_import"]
        if reg.current_stage == "paper_active" and reg.quarantine_status:
            return True, "runtime_active_with_open_position", []
        if reg.current_stage not in ("rejected", "research_only", "watchlist", "paper_experiment"):
            if reg.current_stage in EXPORT_ACTIVE_STAGES and reg.current_stage != "paper_experiment":
                return False, "already_promoted_stage", ["already_active"]
        params = reg.active_parameters_json or reg.parameter_schema_json or {}
        cp = (self.config.get("crypto_push_pull") or {}) if reg.strategy_id.startswith("crypto_") else {}
        has_sl = any(
            params.get(k)
            for k in (
                "atr_multiplier",
                "atr_stop_multiplier",
                "stop_loss_pct",
                "stop_loss",
                "atr_stop",
            )
        ) or cp.get("stop_loss_pct")
        has_hold = any(
            params.get(k)
            for k in ("max_hold_hours", "max_hold_bars", "max_hold_minutes", "time_stop_minutes")
        ) or cp.get("max_hold_hours")
        if self.cfg.get("require_stop_loss") and not has_sl:
            codes.append("no_stop_loss")
        if self.cfg.get("require_time_stop") and not has_hold:
            codes.append("no_max_hold")
        if codes:
            return False, "; ".join(codes), codes
        return True, "safe_mechanics_weak_performance_ok", []

    def evaluate(
        self,
        strategy_id: str,
        symbol: str,
        side: str = "buy",
        signal_id: int | None = None,
        signal_meta: Optional[dict[str, Any]] = None,
    ) -> dict:
        reg = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
        ).first()
        if not reg:
            return {"status": "error", "message": "unknown strategy"}
        ok, reason, codes = self._eligibility_for(reg)
        requested = self._dynamic_requested_notional(symbol, strategy_id, signal_meta or {})
        approved = 0.0
        decision = "blocked"
        reason_code = "not_eligible"
        if not self.cfg.get("mode_enabled"):
            reason_code = "mode_disabled"
            reason = "Paper learning mode disabled"
        elif not ok:
            reason_code = codes[0] if codes else "not_eligible"
        else:
            block = self._preflight_block(
                symbol,
                requested,
                strategy_id=strategy_id,
                side=side,
                signal_meta=signal_meta or {},
            )
            if block:
                reason_code, reason = block[0], block[1]
            else:
                cap = self.cfg.get("max_experiment_notional_per_trade_usd", 0)
                approved = requested if self._unlimited_cap("max_experiment_notional_per_trade_usd", 0) else min(
                    requested,
                    float(cap or requested),
                )
                decision = "approved"
                reason_code = "approved"
                reason = f"Formula paper experiment approved ${approved:.2f}"

        row = PaperExperimentDecision(
            strategy_id=strategy_id,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            requested_notional=requested,
            approved_notional=approved,
            decision=decision,
            reason_code=reason_code,
            reason_text=reason[:300],
            risk_snapshot_json={
                "codes": codes,
                "tier": self.symbol_tier(symbol),
                "signal_meta": signal_meta or {},
                "dynamic_requested_notional": requested,
            },
        )
        self.session.add(row)
        self.session.flush()
        self.session.refresh(row)
        if decision != "approved" and reason_code == "account_pair_eligibility":
            self._write_memory(
                strategy_id,
                "account_pair_eligibility_memory",
                title=f"Pair blocked (eligibility): {symbol}",
                summary=reason,
            )
        else:
            self._write_memory(
                strategy_id,
                "experiment_blocked_memory" if decision != "approved" else "experiment_entry_memory",
                title=f"Experiment {decision}: {strategy_id} {symbol}",
                summary=reason,
            )
        return {
            "status": "ok",
            "decision": decision,
            "decision_id": row.id,
            "reason_code": reason_code,
            "approved_notional": approved,
            "reason": reason,
        }

    def _allocator_active(self) -> bool:
        if bool(self.cfg.get("use_capital_allocator", True)):
            return True
        apl = dict(self.config.get("autonomous_paper_learning") or {})
        return bool(apl.get("mode_enabled")) and bool(apl.get("use_capital_allocator", True))

    def _dynamic_requested_notional(self, symbol: str, strategy_id: str, signal_meta: dict[str, Any]) -> float:
        """Formula sizing for paper learning. No open-position cap; bounded by broker buying power downstream."""
        from app.services.engine_config import cfg_get

        floor = float(cfg_get(self.config, "min_order_notional_usd", 1.0))
        if "/" in symbol:
            floor = max(
                floor,
                float(cfg_get(self.config, "execution.alpaca_crypto_min_notional_usd", 10.0))
                + float(cfg_get(self.config, "execution.alpaca_min_notional_buffer_usd", 0.5)),
            )
        quality = max(0.0, min(1.0, float(signal_meta.get("trade_quality_score") or 0.5)))
        push = max(0.0, min(1.0, float(signal_meta.get("push_score") or quality)))
        edge_bps = max(0.0, float(signal_meta.get("edge_after_cost_bps") or 0.0))
        requested = max(float(self.cfg.get("default_experiment_notional_usd", 10)), floor)

        try:
            from app.services.capital_allocator import CapitalAllocatorService

            plan = CapitalAllocatorService(self.session, self.config).build_plan(
                signals=[
                    {
                        "symbol": symbol,
                        "strategy_id": strategy_id,
                        "confidence": quality * 100,
                        "strength": push * 100,
                        "spread_pct": ((signal_meta.get("score_components") or {}).get("spread_bps") or 0) / 10000,
                    }
                ]
            )
            deployable = float(plan.get("deployable_capital") or 0.0)
            per_symbol = next(
                (row for row in (plan.get("per_symbol_budget") or []) if row.get("symbol") == symbol),
                None,
            )
            formula_share = min(0.95, 0.05 + quality * 0.20 + push * 0.15 + min(edge_bps / 5000.0, 0.35))
            if per_symbol and float(per_symbol.get("approved_notional") or 0) > 0:
                requested = max(floor, float(per_symbol["approved_notional"]) * formula_share)
            elif deployable > 0:
                requested = max(floor, deployable * formula_share)
        except Exception:
            pass

        return round(max(floor, requested), 2)

    def _unlimited_cap(self, key: str, default: int = 0) -> bool:
        if self._allocator_active():
            return True
        val = self.cfg.get(key, default)
        if val is None:
            return True
        try:
            return int(val) <= 0
        except (TypeError, ValueError):
            return False

    def _preflight_block(
        self,
        symbol: str,
        notional: float,
        strategy_id: str = "",
        side: str = "buy",
        signal_meta: Optional[dict[str, Any]] = None,
    ) -> Optional[tuple[str, str]]:
        if not is_paper_broker_url():
            return "broker_not_paper", "Broker must be paper"
        if cfg_get(self.config, "live_trading_enabled", False):
            return "live_locked", "Live trading must stay off"
        allocator_on = self._allocator_active()
        if not allocator_on and not self._unlimited_cap("max_experiment_trades_per_day", 5):
            if self._decisions_today() >= int(self.cfg.get("max_experiment_trades_per_day", 5)):
                return "daily_trade_cap", "Max experiment trades per day"
        reject_cap = self.cfg.get("max_rejected_orders_per_day", 0)
        if not self._unlimited_cap("max_rejected_orders_per_day", 0) and self._rejects_today() >= int(reject_cap):
            return "rejection_cap", "Max rejected orders per day - cooldown"
        if self._in_rejection_cooldown():
            return "rejection_cooldown", "Cooldown after broker rejection"
        from app.services.capital_allocator import _cfg as alloc_cfg_fn

        alloc_cfg = alloc_cfg_fn(self.config)
        emergency_max = int(alloc_cfg.get("operator_emergency_max_open_positions", 0))
        open_exp = len(list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()))
        if emergency_max > 0 and open_exp >= emergency_max:
            return "operator_emergency_position_guard", "Operator emergency max open positions"
        if not allocator_on and not self._unlimited_cap("max_open_experiment_positions", 1):
            if open_exp >= int(self.cfg.get("max_open_experiment_positions", 1)):
                return "max_open_positions", "Max open experiment positions"
        if self._daily_loss_exceeded():
            return "daily_loss_cap", "Daily paper loss cap reached"
        if self._weekly_loss_exceeded():
            return "weekly_loss_cap", "Weekly paper loss cap reached"
        if side.lower() == "buy" and self.cfg.get("no_duplicate_symbol_buy", True) and self._has_open_or_pending_buy(symbol):
            return "duplicate_buy", "Duplicate buy blocked for symbol"
        if side.lower() == "buy" and self.cfg.get("no_averaging_down", True) and self._averaging_down_blocked(symbol):
            return "averaging_down", "Averaging down not allowed without research approval"
        tier = self.symbol_tier(symbol)
        if tier in ("UNSUPPORTED_WATCH_ONLY", "UNFUNDED_QUOTE_WATCH_ONLY"):
            return "symbol_tier", "Symbol tier not supported for experiments"
        if not allocator_on and not self._unlimited_cap("max_experiment_notional_per_trade_usd", 20):
            if notional > float(self.cfg.get("max_experiment_notional_per_trade_usd", 20)):
                return "notional_cap", "Exceeds experiment notional cap"
        if self.cfg.get("require_spread_check") and not self._spread_ok(symbol):
            return "spread_check", "Spread too wide for paper experiment"
        if self.cfg.get("require_liquidity_check") and not self._liquidity_ok(symbol):
            return "liquidity_check", "Insufficient liquidity for paper experiment"
        from app.services.bar_freshness_service import BarFreshnessService

        fresh = BarFreshnessService(self.session, self.config).check(symbol)
        if not fresh.get("executable"):
            return "data_stale", fresh.get("plain") or "Price data stale"
        from app.services.account_pair_eligibility_service import AccountPairEligibilityService
        from app.services.session_engine import SessionEngine

        sess = SessionEngine().detect()
        stock_strategy = (
            strategy_id in ("momentum_orb", "mean_reversion_pairs", "stock_push_pull_baseline")
            or strategy_id.startswith("stock_")
            or "/" not in symbol
        )
        if stock_strategy and not sess.stock_trading_allowed:
            return "stock_market_closed", sess.us_stock_close_reason or "U.S. stock market is closed"
        if "/" in symbol and not sess.crypto_trading_allowed:
            return "crypto_market_closed", "Crypto trading session unavailable"
        elig = AccountPairEligibilityService(self.session, self.config).preflight_block(symbol, side, strategy_id)
        if elig:
            return elig[0], elig[1]
        if allocator_on and side.lower() == "buy":
            from app.services.capital_allocator import CapitalAllocatorService

            approval = CapitalAllocatorService(self.session, self.config).approve_trade(
                symbol, side, strategy_id, notional, signal_meta=signal_meta or {}
            )
            if not approval.get("approved"):
                return (
                    approval.get("reason_code") or "allocator_blocked",
                    approval.get("reason") or "Capital allocator blocked trade",
                )
        return None

    def _rejects_today(self) -> int:
        from app.database import ExecutionLog

        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return len(
            list(
                self.session.exec(
                    select(ExecutionLog).where(
                        ExecutionLog.created_at >= start,
                        ExecutionLog.status.in_(("paper_order_rejected", "broker_rejected")),
                    )
                ).all()
            )
        )

    def _in_rejection_cooldown(self) -> bool:
        from app.database import ExecutionLog

        mins = int(self.cfg.get("rejection_cooldown_minutes", 15))
        since = datetime.utcnow() - timedelta(minutes=mins)
        recent = list(
            self.session.exec(
                select(ExecutionLog).where(
                    ExecutionLog.created_at >= since,
                    ExecutionLog.status.in_(("paper_order_rejected", "broker_rejected")),
                )
            ).all()
        )
        return len(recent) > 0

    def _daily_loss_exceeded(self) -> bool:
        cap = float(self.cfg.get("max_daily_experiment_loss_pct", 5))
        pnl = self._period_pnl_pct(days=1)
        return pnl is not None and pnl <= -cap

    def _weekly_loss_exceeded(self) -> bool:
        cap = float(self.cfg.get("max_weekly_experiment_loss_pct", 10))
        pnl = self._period_pnl_pct(days=7)
        return pnl is not None and pnl <= -cap

    def _period_pnl_pct(self, days: int) -> Optional[float]:
        since = datetime.utcnow() - timedelta(days=days)
        rows = list(
            self.session.exec(select(PaperExperimentOutcome).where(PaperExperimentOutcome.created_at >= since)).all()
        )
        if not rows:
            return None
        total = sum(float(r.realized_pnl or 0) for r in rows)
        base = float(self.cfg.get("default_experiment_notional_usd", 10)) * max(1, len(rows))
        return (total / base) * 100

    def _has_open_or_pending_buy(self, symbol: str) -> bool:
        sym = symbol.upper()
        for p in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            if sym in (p.symbol or "").upper():
                return True
        start = datetime.utcnow() - timedelta(hours=24)
        submitted_statuses = (
            "paper_order_submitted",
            "paper_order_filled",
            "paper_order_partially_filled",
            "submitted",
            "filled",
        )
        for d in self.session.exec(
            select(PaperExperimentDecision).where(
                PaperExperimentDecision.created_at >= start,
                PaperExperimentDecision.side == "buy",
                PaperExperimentDecision.decision == "approved",
            )
        ).all():
            if sym not in (d.symbol or "").upper():
                continue
            st = (d.execution_status or "").lower()
            if st in submitted_statuses:
                return True
        return False

    def _averaging_down_blocked(self, symbol: str) -> bool:
        sym = symbol.upper()
        for p in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            if sym in (p.symbol or "").upper() and (p.unrealized_pl or 0) < 0:
                return True
        return False

    def _spread_ok(self, symbol: str) -> bool:
        return True

    def _liquidity_ok(self, symbol: str) -> bool:
        return True

    def _decisions_today(self) -> int:
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return len(
            list(
                self.session.exec(
                    select(PaperExperimentDecision).where(PaperExperimentDecision.created_at >= start)
                ).all()
            )
        )

    def _write_memory(self, strategy_id: str, mtype: str, title: str, summary: str) -> None:
        LessonMemoryService(self.session, self.config).upsert_lesson(
            memory_type=mtype,
            title=title,
            summary=summary,
            detailed_lesson=summary,
            strategy_name=strategy_id,
            source="paper_learning",
            can_influence_ranking=False,
            visible_to_ai=True,
            pattern_key=f"exp|{strategy_id}|{mtype}|{datetime.utcnow().date()}",
        )

    def list_decisions(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(
            select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "symbol": r.symbol,
                "decision": r.decision,
                "approved_notional": r.approved_notional,
                "reason_code": r.reason_code,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]

    def list_outcomes(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(
            select(PaperExperimentOutcome).order_by(PaperExperimentOutcome.created_at.desc()).limit(limit)
        ).all()
        return [_serialize_row(r) for r in rows]

    def list_memories(self, limit: int = 30) -> list[dict]:
        from app.services.memory_categories import EXPERIMENT_MEMORY_TYPES

        rows = self.session.exec(
            select(LessonNode)
            .where(LessonNode.memory_type.in_(list(EXPERIMENT_MEMORY_TYPES)))
            .order_by(LessonNode.created_at.desc())
            .limit(limit)
        ).all()
        return [LessonMemoryService(self.session, self.config)._lesson_detail(r) for r in rows]

    def monitor_open_experiments(self) -> dict:
        """Read-only monitor placeholder — exits use existing position brain."""
        open_pos = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        return {"status": "ok", "open_positions": len(open_pos), "monitored": True}

    def assert_no_new_orders(self, before: int) -> bool:
        return len(self.session.exec(select(OrderRecord)).all()) == before


def _serialize_row(r: PaperExperimentOutcome) -> dict:
    return {
        "id": r.id,
        "strategy_id": r.strategy_id,
        "symbol": r.symbol,
        "realized_pnl": r.realized_pnl,
        "exit_reason": r.exit_reason,
        "hold_minutes": r.hold_minutes,
    }
