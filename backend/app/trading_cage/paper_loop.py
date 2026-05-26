"""
Paper loop state machine — the only operational trading path.

States: SCAN → PUSH_DETECT → SCORE → VALIDATE → ALLOCATE → SUBMIT → WATCH → EXIT → LEARN
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.push_pull_scan_service import PushPullScanService
from app.services.training_execution_service import TrainingExecutionService
from app.trading_cage.paper_guard import paper_guard_status


PAPER_LOOP_STATES = (
    "SCAN",
    "PUSH_DETECT",
    "SCORE",
    "VALIDATE",
    "ALLOCATE",
    "SUBMIT",
    "WATCH",
    "EXIT",
    "LEARN",
)


class PaperLoop:
    """Orchestrates one deterministic paper cycle tick."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.scan = PushPullScanService(session, self.config)
        self.training = TrainingExecutionService(session, self.config)

    def status(self) -> dict[str, Any]:
        guard = paper_guard_status(self.config)
        return {
            "status": "ok",
            "architecture": "deterministic_paper_cage",
            "states": list(PAPER_LOOP_STATES),
            "gemini_can_trade": False,
            "live_locked": guard.get("live_lock_status") == "locked",
            "paper_guard": guard,
        }

    def run_cycle(self) -> dict[str, Any]:
        """Exit watch → scan → entry attempt (single training cycle)."""
        exit_out = self.training.run_exit_monitor()
        scan_out = self.scan.run_tick_scan()
        entry_out = self.training.run_training_cycle()
        return {
            "status": "ok",
            "exit_monitor": exit_out,
            "scan": scan_out,
            "entry": entry_out,
            "state_path": ["WATCH", "SCAN", "PUSH_DETECT", "VALIDATE", "SUBMIT", "LEARN"],
        }
