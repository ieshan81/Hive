"""Kill switch evaluation — block entries, allow safe exits."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, ExecutionLog, KillSwitchEvent, SystemHealth
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

    # Switches that are CATASTROPHIC — they block even tiny paper-exploration probes.
    # A daily-drawdown switch alone is NOT catastrophic: the paper-only learning lane may
    # still place a tiny capped probe. Real money is always locked regardless.
    CATASTROPHIC_SWITCHES = frozenset({"manual_master", "max_drawdown", "system_health", "weekly_drawdown"})

    def evaluate_paper_exploration(
        self, *, equity: float, daily_pl_pct: float, drawdown_pct: float
    ) -> dict[str, Any]:
        """Separate the four permission lanes. Real money is ALWAYS locked here; exits are
        ALWAYS allowed; standard paper entries follow the normal kill switch; the paper
        exploration lane may proceed only in paper mode, when config allows, and when no
        CATASTROPHIC switch is active. Per-entry caps (notional/position/daily) are enforced
        downstream by the exploration service and the cage — this is the kill-switch view only."""
        entries_ok, switches = self.evaluate(equity=equity, daily_pl_pct=daily_pl_pct, drawdown_pct=drawdown_pct)
        live_orders = bool(cfg_get(self.config, "execution.live_orders_enabled", False)) or bool(
            self.config.get("live_trading_enabled", False)
        )
        paper_orders = bool(cfg_get(self.config, "execution.paper_orders_enabled", False))
        paper_mode = paper_orders and not live_orders
        allow_cfg = bool(cfg_get(self.config, "alpha_factory.paper_exploration.allow_paper_exploration_near_misses", True))
        live_forbidden = bool(cfg_get(self.config, "alpha_factory.paper_exploration.exploration_live_forbidden", True))
        active_names = {str(s.get("switch_name")) for s in switches}
        catastrophic = sorted(active_names & self.CATASTROPHIC_SWITCHES)

        block_reason: Optional[str] = None
        if live_orders or not live_forbidden:
            block_reason = "live_not_forbidden"
        elif not paper_mode:
            block_reason = "not_paper_mode"
        elif not allow_cfg:
            block_reason = "exploration_disabled_by_config"
        elif catastrophic:
            block_reason = "catastrophic_kill_switch:" + ",".join(catastrophic)

        paper_exploration_allowed = block_reason is None
        return {
            # Real money can NEVER enter through this service; live trading stays locked.
            "real_money_entries_allowed": False,
            "paper_entries_allowed": bool(entries_ok and paper_mode),
            "paper_exploration_allowed": paper_exploration_allowed,
            "exit_management_allowed": True,
            "paper_exploration_block_reason": block_reason,
            "catastrophic_switches": catastrophic,
            "active_switches": switches,
            "paper_mode": paper_mode,
        }

    def _latest_account(self) -> AccountSnapshot | None:
        return self.session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()

    def _latest_preflight_block(self) -> ExecutionLog | None:
        return self.session.exec(
            select(ExecutionLog)
            .where(
                ExecutionLog.status == "preflight_blocked",
                ExecutionLog.reject_reason == "KILL_SWITCH_ACTIVE",
            )
            .order_by(ExecutionLog.created_at.desc())
        ).first()

    def status(self) -> dict[str, Any]:
        snap = self._latest_account()
        entries_ok, active = self.evaluate(
            equity=float(snap.equity or 0) if snap else 0,
            daily_pl_pct=float(snap.daily_pl_pct or 0) if snap else 0,
            drawdown_pct=float(snap.drawdown_pct or 0) if snap else 0,
        )
        latest_block = self._latest_preflight_block()
        now = datetime.utcnow()
        recently_blocked = bool(latest_block and latest_block.created_at >= now - timedelta(hours=24))
        last_block = None
        if latest_block:
            failed = latest_block.gates_failed_json if isinstance(latest_block.gates_failed_json, dict) else {}
            last_block = {
                "event_id": latest_block.event_id,
                "symbol": latest_block.symbol,
                "side": latest_block.side,
                "created_at": latest_block.created_at.isoformat() + "Z",
                "reject_reason": latest_block.reject_reason,
                "human_reason": failed.get("reason") or latest_block.reject_reason,
            }
        snapshot_age = None
        if snap and snap.synced_at:
            snapshot_age = max(0, int((now - snap.synced_at).total_seconds()))
        lanes = self.evaluate_paper_exploration(
            equity=float(snap.equity or 0) if snap else 0,
            daily_pl_pct=float(snap.daily_pl_pct or 0) if snap else 0,
            drawdown_pct=float(snap.drawdown_pct or 0) if snap else 0,
        )
        return {
            "entries_allowed": entries_ok,
            "active_switches": active,
            # Four explicit permission lanes (real money always locked, exits always allowed).
            "real_money_entries_allowed": lanes["real_money_entries_allowed"],
            "paper_entries_allowed": lanes["paper_entries_allowed"],
            "paper_exploration_allowed": lanes["paper_exploration_allowed"],
            "exit_management_allowed": lanes["exit_management_allowed"],
            "paper_exploration_block_reason": lanes["paper_exploration_block_reason"],
            "state": "active" if not entries_ok else "cleared_recently" if recently_blocked else "clear",
            "manual_master": bool(cfg_get(self.config, "kill.manual_master_active", False)),
            "account_equity": snap.equity if snap else None,
            "account_daily_pl_pct": snap.daily_pl_pct if snap else None,
            "account_drawdown_pct": snap.drawdown_pct if snap else None,
            "account_synced_at": snap.synced_at.isoformat() + "Z" if snap and snap.synced_at else None,
            "account_snapshot_age_seconds": snapshot_age,
            "recently_blocked": recently_blocked,
            "last_preflight_block": last_block,
            "updated_at": now.isoformat() + "Z",
        }
