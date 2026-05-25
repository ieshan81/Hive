"""Cron-driven paper learning scheduler — tick endpoint only, no in-process loop."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, SettingsActionAudit
from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService
from app.services.config_manager import ConfigManager, _deep_merge
from app.services.engine_config import cfg_get


class AutonomousPaperScheduler:
    SCHEDULER_STATE_KEY = "autonomous_scheduler"

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._state = self._load_state()

    def _load_state(self) -> dict:
        rows = list(
            self.session.exec(
                select(SettingsActionAudit).where(SettingsActionAudit.action == self.SCHEDULER_STATE_KEY)
            ).all()
        )
        row = max(rows, key=lambda r: r.created_at or datetime.min, default=None) if rows else None
        if row and row.details_json:
            return dict(row.details_json)
        return {
            "scheduler_enabled": False,
            "paused": False,
            "paused_reason": None,
            "ticks_today": 0,
            "last_tick_at": None,
            "next_planned_at_utc": None,
            "broker_error_streak": 0,
            "day_key": datetime.utcnow().strftime("%Y-%m-%d"),
        }

    def _persist_state(self, operator: str = "scheduler") -> None:
        self.session.add(
            SettingsActionAudit(
                action=self.SCHEDULER_STATE_KEY,
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json=self._state,
            )
        )

    def _reset_daily_if_needed(self) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._state.get("day_key") != today:
            self._state["day_key"] = today
            self._state["ticks_today"] = 0

    def status(self) -> dict[str, Any]:
        self._reset_daily_if_needed()
        interval = max(60, int(self.cfg.get("scheduler_interval_seconds", 300)))
        last = self._state.get("last_tick_at")
        next_at = None
        if last and self._state.get("scheduler_enabled") and not self._state.get("paused"):
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", ""))
                next_at = (last_dt + timedelta(seconds=interval)).isoformat() + "Z"
            except ValueError:
                next_at = None
        return {
            "scheduler_enabled": bool(self.cfg.get("scheduler_enabled")),
            "paused": bool(self._state.get("paused")),
            "paused_reason": self._state.get("paused_reason"),
            "interval_seconds": interval,
            "ticks_today": int(self._state.get("ticks_today", 0)),
            "max_ticks_per_day": int(self.cfg.get("max_scheduler_ticks_per_day", 48)),
            "last_tick_at": last,
            "next_planned_at_utc": next_at,
            "broker_error_streak": int(self._state.get("broker_error_streak", 0)),
        }

    def enable(self, operator: str = "operator") -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "scheduler_enabled": True,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "scheduler_enable")
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._state["scheduler_enabled"] = True
        self._state["paused"] = False
        self._state["paused_reason"] = None
        self._persist_state(operator)
        return {"status": "ok", **self.status()}

    def pause(self, operator: str = "operator") -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "scheduler_enabled": False,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "scheduler_pause")
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._state["scheduler_enabled"] = False
        self._state["paused"] = True
        self._state["paused_reason"] = "operator_pause"
        self._persist_state(operator)
        return {"status": "ok", **self.status()}

    def tick(self, *, operator: str = "cron") -> dict[str, Any]:
        self._reset_daily_if_needed()
        apl_cfg = dict(self.config.get("autonomous_paper_learning") or {})
        if not apl_cfg.get("scheduler_enabled"):
            return {"status": "noop", "reason": "scheduler_disabled"}
        if self._state.get("paused"):
            return {"status": "noop", "reason": "scheduler_paused", "paused_reason": self._state.get("paused_reason")}
        if not apl_cfg.get("mode_enabled"):
            return {"status": "noop", "reason": "autonomous_paper_learning_off"}

        max_ticks = int(apl_cfg.get("max_scheduler_ticks_per_day", 48))
        if int(self._state.get("ticks_today", 0)) >= max_ticks:
            self._state["paused"] = True
            self._state["paused_reason"] = "daily_tick_cap"
            self._persist_state(operator)
            return {"status": "stopped", "reason": "daily_tick_cap_reached"}

        max_trades = int(apl_cfg.get("max_paper_trades_per_day", 5))
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        filled_today = len(
            list(
                self.session.exec(
                    select(ExecutionLog).where(
                        ExecutionLog.created_at >= start,
                        ExecutionLog.status == "paper_order_filled",
                    )
                ).all()
            )
        )
        if filled_today >= max_trades:
            self._state["paused"] = True
            self._state["paused_reason"] = "daily_trade_cap"
            self._persist_state(operator)
            return {"status": "stopped", "reason": "daily_paper_trade_cap"}

        svc = AutonomousPaperLearningService(self.session, self.config)
        result = svc.run_one_cycle(operator=operator)
        self._state["ticks_today"] = int(self._state.get("ticks_today", 0)) + 1
        self._state["last_tick_at"] = datetime.utcnow().isoformat() + "Z"

        if result.get("status") in ("error", "blocked") and "broker" in str(result.get("reason", "")).lower():
            self._state["broker_error_streak"] = int(self._state.get("broker_error_streak", 0)) + 1
            pause_after = int(apl_cfg.get("broker_error_pause_after", 3))
            if self._state["broker_error_streak"] >= pause_after:
                self._state["paused"] = True
                self._state["paused_reason"] = "broker_errors"
        else:
            self._state["broker_error_streak"] = 0

        self._persist_state(operator)
        self.session.flush()
        return {"status": "ok", "tick": self.status(), "cycle_result": result}
