"""Kill switch evaluation — block entries, allow safe exits."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, KillSwitchEvent, SystemHealth
from app.services.engine_config import cfg_get


class KillSwitchService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config

    def _active_events(self) -> list[KillSwitchEvent]:
        rows = self.session.exec(
            select(KillSwitchEvent).where(KillSwitchEvent.active == True).order_by(KillSwitchEvent.created_at.desc())  # noqa: E712
        ).all()
        return list(rows)

    def activate(self, switch_name: str, message: str, *, cycle_run_id: Optional[str] = None, details: Optional[dict] = None) -> KillSwitchEvent:
        ev = KillSwitchEvent(
            switch_name=switch_name,
            active=True,
            message=message,
            details=details or {},
            cycle_run_id=cycle_run_id,
        )
        self.session.add(ev)
        health = self.session.get(SystemHealth, 1) or SystemHealth(id=1)
        health.kill_switch_active = True
        health.updated_at = datetime.utcnow()
        self.session.add(health)
        return ev

    def deactivate_manual(self) -> None:
        for ev in self._active_events():
            if ev.switch_name == "manual_master":
                ev.active = False
                ev.deactivated_at = datetime.utcnow()
                self.session.add(ev)
        if not self._active_events():
            health = self.session.get(SystemHealth, 1)
            if health:
                health.kill_switch_active = False
                self.session.add(health)

    def evaluate(self, *, equity: float, daily_pl_pct: float, drawdown_pct: float) -> tuple[bool, list[dict[str, Any]]]:
        """Returns (entries_allowed, active_switches)."""
        switches: list[dict[str, Any]] = []

        if cfg_get(self.config, "kill.manual_master_active", False) or cfg_get(self.config, "kill_switch_active"):
            switches.append({"switch_name": "manual_master", "message": "Manual or config kill switch active"})

        daily_lim = float(cfg_get(self.config, "kill.daily_drawdown_pct", 2.0))
        weekly_lim = float(cfg_get(self.config, "kill.weekly_drawdown_pct", 5.0))
        max_dd = float(cfg_get(self.config, "kill.max_drawdown_pct", 15.0))

        if daily_pl_pct is not None and daily_pl_pct <= -daily_lim:
            switches.append({"switch_name": "daily_drawdown", "message": f"Daily drawdown {daily_pl_pct:.2f}% exceeds {daily_lim}%"})
        if drawdown_pct is not None and drawdown_pct >= max_dd:
            switches.append({"switch_name": "max_drawdown", "message": f"Drawdown {drawdown_pct:.2f}% exceeds {max_dd}%"})

        health = self.session.get(SystemHealth, 1)
        if health and health.kill_switch_active:
            switches.append({"switch_name": "system_health", "message": "System health kill flag set"})

        for ev in self._active_events():
            switches.append({"switch_name": ev.switch_name, "message": ev.message, "event_id": ev.id})

        entries_allowed = len(switches) == 0
        return entries_allowed, switches

    def status(self) -> dict[str, Any]:
        entries_ok, active = self.evaluate(equity=0, daily_pl_pct=0, drawdown_pct=0)
        snap = self.session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
        return {
            "entries_allowed": entries_ok,
            "active_switches": active,
            "manual_master": bool(cfg_get(self.config, "kill.manual_master_active", False)),
            "account_equity": snap.equity if snap else None,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
