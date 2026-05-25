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
    "max_experiment_notional_per_trade_usd": 20,
    "default_experiment_notional_usd": 10,
    "max_open_experiment_positions": 1,
    "max_experiment_positions_total": 2,
    "max_experiment_trades_per_day": 5,
    "max_experiment_trades_per_strategy_per_day": 2,
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
        if "DOGE" in s or "SHIB" in s or "PEPE" in s:
            return "MEME_SUPPORTED"
        if symbol in MAJOR_SYMBOLS or "BTC" in s or "ETH" in s or "SOL" in s:
            return "MAJOR_CRYPTO"
        return "UNSUPPORTED_WATCH_ONLY"

    def scan_experiment_eligibility(self) -> dict[str, Any]:
        eligible, blocked = [], []
        for reg in self.session.exec(select(StrategyRegistry)).all():
            ok, reason, codes = self._eligibility_for(reg)
            row = {"strategy_id": reg.strategy_id, "stage": reg.current_stage, "reason": reason, "codes": codes}
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

    def evaluate(self, strategy_id: str, symbol: str, side: str = "buy", signal_id: int | None = None) -> dict:
        reg = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
        ).first()
        if not reg:
            return {"status": "error", "message": "unknown strategy"}
        ok, reason, codes = self._eligibility_for(reg)
        requested = float(self.cfg.get("default_experiment_notional_usd", 10))
        approved = 0.0
        decision = "blocked"
        reason_code = "not_eligible"
        if not self.cfg.get("mode_enabled"):
            reason_code = "mode_disabled"
            reason = "Paper learning mode disabled"
        elif not ok:
            reason_code = codes[0] if codes else "not_eligible"
        else:
            block = self._preflight_block(symbol, requested)
            if block:
                reason_code, reason = block[0], block[1]
            else:
                cap = float(self.cfg.get("max_experiment_notional_per_trade_usd", 20))
                approved = min(requested, cap)
                decision = "approved"
                reason_code = "approved"
                reason = f"Tiny paper experiment approved ${approved:.2f}"

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
            risk_snapshot_json={"codes": codes, "tier": self.symbol_tier(symbol)},
        )
        self.session.add(row)
        self._write_memory(
            strategy_id,
            "experiment_blocked_memory" if decision != "approved" else "experiment_entry_memory",
            title=f"Experiment {decision}: {strategy_id} {symbol}",
            summary=reason,
        )
        return {"status": "ok", "decision": decision, "approved_notional": approved, "reason": reason}

    def _preflight_block(self, symbol: str, notional: float) -> Optional[tuple[str, str]]:
        if not is_paper_broker_url():
            return "broker_not_paper", "Broker must be paper"
        if cfg_get(self.config, "live_trading_enabled", False):
            return "live_locked", "Live trading must stay off"
        if self._decisions_today() >= int(self.cfg.get("max_experiment_trades_per_day", 5)):
            return "daily_trade_cap", "Max experiment trades per day"
        open_exp = len(list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()))
        if open_exp >= int(self.cfg.get("max_open_experiment_positions", 1)):
            return "max_open_positions", "Max open experiment positions"
        tier = self.symbol_tier(symbol)
        if tier == "UNSUPPORTED_WATCH_ONLY":
            return "symbol_tier", "Symbol tier not supported for experiments"
        if notional > float(self.cfg.get("max_experiment_notional_per_trade_usd", 20)):
            return "notional_cap", "Exceeds experiment notional cap"
        return None

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
