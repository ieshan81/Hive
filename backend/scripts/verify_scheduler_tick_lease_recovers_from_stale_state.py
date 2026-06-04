"""Scheduler status must clear stale tick lease and not report tick_in_progress stuck."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
    from app.services.config_manager import ConfigManager
    from app.services.fast_training_lease_service import SCHEDULER_TICK_LEASE_KEY, FastTrainingLeaseService

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = ConfigManager(session).get_current_readonly()
        lease = FastTrainingLeaseService(session, lease_key=SCHEDULER_TICK_LEASE_KEY, ttl_seconds=60)
        row = lease._row()
        row.holder_id = "stale-scheduler-holder"
        row.acquired_at = datetime.utcnow() - timedelta(minutes=10)
        row.expires_at = datetime.utcnow() - timedelta(minutes=5)
        session.add(row)
        session.commit()

        sched = AutonomousPaperScheduler(session, cfg).status()
        assert sched.get("tick_lease_held") is False, sched
        assert sched.get("tick_in_progress") is False, sched
        assert sched.get("tick_lease_stale_recovered") is True, sched

    print("verify_scheduler_tick_lease_recovers_from_stale_state: PASS")


if __name__ == "__main__":
    main()
