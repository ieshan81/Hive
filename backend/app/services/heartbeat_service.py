"""Two-loop heartbeat model.

FAST heartbeat (every tick): manage exits, refresh quotes/positions, update risk state. It NEVER
forces a new entry. SLOW decision loop (every N ticks): the only place new entries are even
considered, and only when backtest evidence exists.

This service produces ADDITIVE entry blockers — it can only block more entries, never loosen any
safety gate. It submits no orders and never touches live trading.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import ResearchBacktestRun, SettingsActionAudit
from app.services.engine_config import cfg_get

HEARTBEAT_ONLY_BLOCKER = "heartbeat_only_tick_no_forced_entry"
NO_BACKTEST_EVIDENCE_BLOCKER = "entry_requires_backtest_evidence"


class HeartbeatService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def _cfg(self, key: str, default: Any) -> Any:
        return cfg_get(self.config, f"autonomous_paper_learning.heartbeat.{key}", default)

    @property
    def enabled(self) -> bool:
        return bool(self._cfg("enabled", True))

    @property
    def decision_loop_interval(self) -> int:
        return max(1, int(self._cfg("decision_loop_interval_ticks", 4) or 4))

    @property
    def require_backtest_evidence(self) -> bool:
        return bool(self._cfg("require_backtest_evidence_for_entry", True))

    def tick_count(self) -> int:
        """Number of completed autopilot cycles (the heartbeat tick counter)."""
        try:
            return int(
                self.session.exec(
                    select(func.count()).select_from(SettingsActionAudit).where(
                        SettingsActionAudit.action == "autonomous_run_one_cycle"
                    )
                ).one()
                or 0
            )
        except Exception:
            return 0

    def has_backtest_evidence(self) -> bool:
        try:
            return int(self.session.exec(select(func.count()).select_from(ResearchBacktestRun)).one() or 0) > 0
        except Exception:
            return False

    # --- the heartbeat invariant ---
    def manages_exits_every_tick(self) -> bool:
        """Exits are ALWAYS managed by the fast heartbeat (never gated off)."""
        return bool(self._cfg("manage_exits_every_tick", True))

    def is_decision_tick(self, tick_count: Optional[int] = None) -> bool:
        """True only on the slower decision-loop cadence (where new entries may be considered)."""
        if not self.enabled:
            return True  # legacy behavior when the two-loop model is disabled
        tc = self.tick_count() if tick_count is None else int(tick_count)
        interval = self.decision_loop_interval
        return interval <= 1 or (tc % interval == 0)

    def entry_gate_blockers(self, tick_count: Optional[int] = None) -> list[str]:
        """ADDITIVE blockers: the fast heartbeat never forces an entry, and entries require
        backtest evidence. Returning [] means this tick MAY consider entries (still subject to
        every existing cage/preflight safety gate)."""
        if not self.enabled:
            return []
        blockers: list[str] = []
        # force_entries_every_candle is intentionally never honored as True — the heartbeat
        # observes/manages but does not force entries. Entries only on decision ticks.
        if bool(self._cfg("force_entries_every_candle", False)):
            # Even if misconfigured True, we still require the decision-loop cadence below.
            pass
        if not self.is_decision_tick(tick_count):
            blockers.append(HEARTBEAT_ONLY_BLOCKER)
        if self.require_backtest_evidence and not self.has_backtest_evidence():
            blockers.append(NO_BACKTEST_EVIDENCE_BLOCKER)
        return blockers

    def status(self) -> dict[str, Any]:
        tc = self.tick_count()
        return {
            "heartbeat_enabled": self.enabled,
            "manage_exits_every_tick": self.manages_exits_every_tick(),
            "force_entries_every_candle": False,  # invariant: never forces entries
            "decision_loop_interval_ticks": self.decision_loop_interval,
            "tick_count": tc,
            "is_decision_tick": self.is_decision_tick(tc),
            "require_backtest_evidence_for_entry": self.require_backtest_evidence,
            "has_backtest_evidence": self.has_backtest_evidence(),
            "entry_gate_blockers": self.entry_gate_blockers(tc),
            "orders_authority": "cage_only",
        }
