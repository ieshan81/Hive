"""Reports hub — bundle health summary before raw JSON download."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ActivityLog, SettingsActionAudit
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status


EXPECTED_BUNDLE_FILES = [
    "README_FIRST.json",
    "bundle_meta.json",
    "current_run_trade_truth.json",
    "paper_validation_productivity.json",
    "alpha_coverage_matrix.json",
    "data_freshness_matrix.json",
    "p_and_l_guard_trace.json",
    "shadow_trades_summary.json",
    "shadow_outcomes.json",
    "strategy_promotion_ladder.json",
    "why_no_trade.json",
]


class ReportsHubService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def diagnostic_bundle_status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "headline": "Diagnostic proof package",
            "description": "Default download is the small current-run latest bundle (README_FIRST.json first). Full history requires ?mode=forensic.",
            "expected_files": EXPECTED_BUNDLE_FILES,
            "download_path": "/api/diagnostic-bundle/download?mode=latest",
            "forensic_download_path": "/api/diagnostic-bundle/download?mode=forensic",
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
                    "message": getattr(r, "message", None) or (r.details or {}).get("message") or r.event_type,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                    "cycle_run_id": (r.details or {}).get("cycle_run_id") if isinstance(r.details, dict) else None,
                }
                for r in rows
            ],
        }
