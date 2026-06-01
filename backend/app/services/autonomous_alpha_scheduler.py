"""Optional scheduler facade for autonomous alpha research.

No background loop is started here. Routes/workers can call ``run_due``. The
service records skips plainly and never submits orders.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot, SettingsActionAudit
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get


class AutonomousAlphaScheduler:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def status(self) -> dict[str, Any]:
        latest = self._latest()
        details = dict(latest.details_json or {}) if latest and latest.details_json else {}
        enabled = bool(cfg_get(self.config, "alpha_factory.scheduler_enabled", False))
        next_due = self._next_due(latest)
        return {
            "enabled": enabled,
            "last_run_at": latest.created_at.isoformat() + "Z" if latest else None,
            "last_run_status": details.get("status") if latest else "never_run",
            "last_run_duration_ms": details.get("duration_ms"),
            "next_run_due_at": next_due.isoformat() + "Z" if next_due else None,
            "skipped_reason": details.get("skipped_reason"),
            "symbols_tested": details.get("symbols_tested", 0),
            "strategies_tested": details.get("strategies_tested", 0),
            "candidates_promoted": details.get("candidates_promoted", 0),
            "candidates_rejected": details.get("candidates_rejected", 0),
            "memory_written_count": details.get("memory_written_count", 0),
            "backtests_run": details.get("backtests_run", 0),
            "walk_forward_tests_run": details.get("walk_forward_tests_run", 0),
            "parameter_sets_tested": details.get("parameter_sets_tested", 0),
            "current_phase": details.get("current_phase", "idle"),
            "plain_english": details.get("plain_english") or ("Autonomous alpha research is enabled." if enabled else "Autonomous alpha research is paused."),
        }

    def run_due(self, *, operator: str = "scheduler", force: bool = False) -> dict[str, Any]:
        enabled = bool(cfg_get(self.config, "alpha_factory.scheduler_enabled", False))
        if not enabled and not force:
            return self._skip("disabled", operator)
        reason = self._skip_reason(force=force)
        if reason:
            return self._skip(reason, operator)
        started = time.perf_counter()
        out = AutonomousAlphaFactoryService(self.session, self.config).run_autonomous_cycle({"source": "scheduler"}, operator=operator)
        duration_ms = int((time.perf_counter() - started) * 1000)
        flat = self._flatten(out)
        flat.update({"status": out.get("status"), "duration_ms": duration_ms, "current_phase": "complete"})
        self._audit(operator, flat)
        self.session.flush()
        return {"status": "ok", **flat, "orders_created": 0}

    def pause(self, *, operator: str = "operator") -> dict[str, Any]:
        return self._set_enabled(False, operator)

    def resume(self, *, operator: str = "operator") -> dict[str, Any]:
        return self._set_enabled(True, operator)

    def _skip_reason(self, *, force: bool) -> str | None:
        if force:
            return None
        open_pos = list(
            self.session.exec(
                select(PositionSnapshot).where(PositionSnapshot.qty > 0).limit(1)
            ).all()
        )
        if open_pos:
            return "open_position"
        latest = self._latest()
        next_due = self._next_due(latest)
        if next_due and next_due > datetime.utcnow():
            return "cooldown"
        return None

    def _skip(self, reason: str, operator: str) -> dict[str, Any]:
        out = {
            "status": "skipped",
            "skipped_reason": reason,
            "current_phase": "skipped",
            "orders_created": 0,
            "plain_english": f"Autonomous alpha research skipped: {reason.replace('_', ' ')}.",
        }
        self._audit(operator, out)
        self.session.flush()
        return out

    def _set_enabled(self, enabled: bool, operator: str) -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = {
            **cur,
            "alpha_factory": {**(cur.get("alpha_factory") or {}), "scheduler_enabled": enabled},
        }
        cfg_mgr._activate(merged, changed_by=operator, reason="alpha_factory_scheduler_toggle")
        self.config = cfg_mgr.get_current()
        return {"status": "ok", "enabled": enabled, "orders_created": 0}

    def _latest(self) -> SettingsActionAudit | None:
        return self.session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == "autonomous_alpha_scheduler")
            .order_by(SettingsActionAudit.created_at.desc())
            .limit(1)
        ).first()

    def _next_due(self, latest: SettingsActionAudit | None) -> datetime | None:
        if not latest:
            return None
        interval = int(cfg_get(self.config, "alpha_factory.scheduler_interval_minutes", 30) or 30)
        return latest.created_at + timedelta(minutes=interval)

    def _audit(self, operator: str, details: dict[str, Any]) -> None:
        self.session.add(
            SettingsActionAudit(
                action="autonomous_alpha_scheduler",
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json=details,
            )
        )

    @staticmethod
    def _flatten(out: dict[str, Any]) -> dict[str, Any]:
        flat = {
            "symbols_tested": 0,
            "strategies_tested": 0,
            "candidates_promoted": 0,
            "candidates_rejected": 0,
            "memory_written_count": 0,
            "backtests_run": 0,
            "walk_forward_tests_run": 0,
            "parameter_sets_tested": 0,
            "plain_english": out.get("plain_english"),
        }
        for phase in out.get("phases") or []:
            for key in flat:
                if key in phase and isinstance(phase.get(key), int):
                    flat[key] += int(phase.get(key) or 0)
        return flat
