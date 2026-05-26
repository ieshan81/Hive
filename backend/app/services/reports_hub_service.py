"""Reports hub — bundle health summary before raw JSON download."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ActivityLog, SettingsActionAudit
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status


EXPECTED_BUNDLE_FILES = [
    "bundle_meta.json",
    "health_snapshot.json",
    "system_log.json",
    "audit_trail.json",
    "env_pause_status.json",
    "live_lock_status.json",
    "latest_tick_execution_logs.json",
    "historical_execution_logs.json",
    "capital_allocator_plan.json",
    "push_pull_latest_tick.json",
    "ai_memory.json",
    "diagnostic_export_errors.json",
]


class ReportsHubService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def diagnostic_bundle_status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "headline": "Diagnostic proof package",
            "description": "Download includes trading, AI, push-pull, allocator, and error sections. Partial failures are listed in diagnostic_export_errors.json.",
            "expected_files": EXPECTED_BUNDLE_FILES,
            "download_path": "/api/diagnostic-bundle/download",
            "no_secrets": True,
            "env_pause": env_pause_status(),
            "live_lock": live_lock_tripwire_status(self.config),
        }

    def audit_trail(self, limit: int = 50) -> dict[str, Any]:
        rows = list(
            self.session.exec(
                select(SettingsActionAudit).order_by(SettingsActionAudit.created_at.desc()).limit(limit)
            ).all()
        )
        return {
            "status": "ok",
            "audits": [
                {
                    "action": r.action,
                    "actor": r.actor,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                    "paper_broker": r.paper_broker,
                    "live_trading_locked": r.live_trading_locked,
                }
                for r in rows
            ],
        }

    def system_log(self, limit: int = 100) -> dict[str, Any]:
        rows = list(
            self.session.exec(
                select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
            ).all()
        )
        return {
            "status": "ok",
            "events": [
                {
                    "event_type": r.event_type,
                    "message": r.message,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                    "cycle_run_id": r.cycle_run_id,
                }
                for r in rows
            ],
        }
