"""Danger Zone — nuke everything and ready-for-live cleanup (never enables live)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, delete, select

from app.database import (
    BrokerError,
    ExecutionLog,
    LessonNode,
    OrderRecord,
    PaperExperimentOutcome,
    PositionSnapshot,
    SettingsActionAudit,
    StrategyRegistry,
    SystemHealth,
)
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.nuke_reset_service import execute_nuke_reset, table_inventory


class DangerZoneService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def nuke_preview(self) -> dict[str, Any]:
        inv = table_inventory()
        return {
            "status": "ok",
            "action": "nuke_everything",
            "confirmation_phrase": "NUKE CAGED HIVE",
            "ux_notes": [
                "This deletes all learned brain/data. It does not wipe Railway volume.",
                "This keeps schema and live safety.",
                "Do not manually wipe Railway volume/database for normal reset.",
            ],
            "will_delete": inv["delete_on_nuke"],
            "will_keep": inv["preserve_on_nuke"],
            "will_reseed": inv["reseed_after_nuke"],
            "table_inventory": inv,
            "will_not_change": [
                "autonomous_paper_learning.mode_enabled",
                "autonomous_paper_learning.scheduler_enabled",
                "paper trading disabled flags",
                "training disabled flags",
                "paused flags in config",
            ],
            "live_trading_enabled": False,
            "note": "Global pause is only via Railway env vars. Nuke is a full app-level data reset.",
        }

    def nuke_everything(self, operator: str = "operator") -> dict[str, Any]:
        return execute_nuke_reset(self.session, operator)

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
