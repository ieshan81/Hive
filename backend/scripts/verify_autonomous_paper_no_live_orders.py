"""Autonomous paper learning must not enable live orders."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService
from app.services.confidence_engine import can_unlock_live
from app.services.config_manager import ConfigManager


def main() -> None:
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        assert not cfg.get("execution", {}).get("live_orders_enabled"), "live_orders_enabled must be false"
        st = AutonomousPaperLearningService(session, cfg).status()
        assert not st.get("live_trading_enabled"), "autonomous status must not show live on"
        assert can_unlock_live() is False
    print("PASS: autonomous paths do not arm live")


if __name__ == "__main__":
    main()
