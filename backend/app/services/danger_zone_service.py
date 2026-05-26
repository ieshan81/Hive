"""Danger Zone — nuke everything and ready-for-live cleanup (never enables live)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, delete, select

from app.database import (
    AIReview,
    ActivityLog,
    BlockedTrade,
    BrokerError,
    ExecutionLog,
    LessonNode,
    OrderRecord,
    PaperExperimentDecision,
    PaperExperimentOutcome,
    PositionSnapshot,
    ResearchBacktestRun,
    SettingsActionAudit,
    StrategyRegistry,
    SystemHealth,
    TradeRecord,
)
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status


KEEP_TABLES = frozenset({"system_health"})


class DangerZoneService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def nuke_preview(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "action": "nuke_everything",
            "confirmation_phrase": "NUKE CAGED HIVE",
            "will_delete": [
                "AI memories and lessons",
                "Memory graph data",
                "Paper orders and positions",
                "Execution logs",
                "Training/paper experiment decisions",
                "Backtest runs",
                "Broker error history",
                "Activity logs",
                "Confidence history artifacts",
            ],
            "will_keep": [
                "Database schema",
                "Live env lock (stays locked)",
                "Railway environment config (outside DB)",
                "Operator learning/scheduler desired state (not changed by nuke)",
                "Env-only pause flags (PAPER_TRADING_PAUSED_BY_ENV, etc.)",
                "Minimal system_health bootstrap row",
            ],
            "will_not_change": [
                "autonomous_paper_learning.mode_enabled",
                "autonomous_paper_learning.scheduler_enabled",
                "paper trading disabled flags",
                "training disabled flags",
                "paused flags in config",
            ],
            "live_trading_enabled": False,
            "note": "Global pause is only via Railway env vars. Nuke deletes learned data only.",
        }

    def nuke_everything(self, operator: str = "operator") -> dict[str, Any]:
        deleted = {}
        tables = [
            (LessonNode, "lessons"),
            (PaperExperimentDecision, "paper_decisions"),
            (PaperExperimentOutcome, "paper_outcomes"),
            (ExecutionLog, "execution_logs"),
            (OrderRecord, "orders"),
            (PositionSnapshot, "positions"),
            (TradeRecord, "trades"),
            (BlockedTrade, "blocked_trades"),
            (BrokerError, "broker_errors"),
            (ActivityLog, "activity_logs"),
            (AIReview, "ai_reviews"),
            (ResearchBacktestRun, "backtest_runs"),
            (SettingsActionAudit, "settings_audits"),
        ]
        for model, name in tables:
            result = self.session.exec(delete(model))
            deleted[name] = result.rowcount if hasattr(result, "rowcount") else "ok"

        # Do not mutate learning/scheduler/pause config — env vars are the only global pause.
        self._ensure_health_row()
        env = env_pause_status()
        apl = dict((self.config.get("autonomous_paper_learning") or {}))
        desired_learning = bool(apl.get("mode_enabled"))
        desired_scheduler = bool(apl.get("scheduler_enabled"))

        self.session.add(
            SettingsActionAudit(
                action="nuke_everything",
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json={"deleted": deleted, "at": datetime.utcnow().isoformat() + "Z"},
            )
        )
        self.session.flush()
        lock = live_lock_tripwire_status(self.config)
        if env.get("any_env_pause"):
            headline = "Fresh brain. No memories yet. Env pause active — execution blocked until Railway env vars cleared."
        elif desired_learning:
            headline = "Fresh brain. No memories yet. Paper learning available."
        else:
            headline = "Fresh brain. No memories yet. Turn on paper learning when ready (not env-paused)."

        return {
            "status": "ok",
            "fresh_brain": True,
            "deleted": deleted,
            "env_pause": env,
            "desired_learning_enabled": desired_learning,
            "desired_scheduler_enabled": desired_scheduler,
            "config_pause_flags_changed": False,
            **lock,
            "message": headline,
        }

    def ready_cleanup_preview(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "action": "ready_for_live_cleanup",
            "confirmation_phrase": "READY CLEANUP",
            "does_not_enable_live": True,
            "will_keep": [
                "Proven strategies in registry",
                "Useful AI memories",
                "Capital allocator settings",
                "Safety cage rules",
                "Backtest results supporting selection",
            ],
            "will_archive_or_delete": [
                "Temporary paper orders",
                "Stale paper execution logs",
                "Rejected experiment junk",
                "Ghost rows",
                "Old broker snapshots",
                "Historical errors not needed for readiness",
            ],
        }

    def ready_for_live_cleanup(self, operator: str = "operator") -> dict[str, Any]:
        deleted = {}
        for model, name in [
            (OrderRecord, "orders"),
            (PositionSnapshot, "positions"),
            (ExecutionLog, "execution_logs"),
            (BrokerError, "broker_errors"),
            (PaperExperimentOutcome, "paper_outcomes"),
        ]:
            result = self.session.exec(delete(model))
            deleted[name] = result.rowcount if hasattr(result, "rowcount") else "ok"

        strategies = list(self.session.exec(select(StrategyRegistry)).all())
        memories = [
            m
            for m in self.session.exec(select(LessonNode)).all()
            if (m.memory_type or "") not in ("experiment_blocked_memory",)
        ]
        manifest = {
            "retained_strategies": [
                {"strategy_id": s.strategy_id, "stage": s.current_stage} for s in strategies
            ],
            "retained_memories_count": len(memories),
            "cleanup_at": datetime.utcnow().isoformat() + "Z",
            "operator": operator,
        }
        self.session.add(
            SettingsActionAudit(
                action="ready_for_live_cleanup",
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json={"deleted": deleted, "manifest": manifest},
            )
        )
        self.session.flush()
        return {
            "status": "ok",
            "message": "Paper junk removed. Proven intelligence retained. Live trading NOT enabled.",
            "deleted": deleted,
            "live_readiness_snapshot": manifest,
            "retained_memory_manifest": {"count": len(memories)},
            "retained_strategy_manifest": manifest["retained_strategies"],
            "cleanup_deleted_items": deleted,
            **live_lock_tripwire_status(self.config),
        }

    def _ensure_health_row(self) -> None:
        h = self.session.get(SystemHealth, 1)
        if not h:
            self.session.add(SystemHealth(id=1, alpaca_connected=False, gemini_configured=False))
