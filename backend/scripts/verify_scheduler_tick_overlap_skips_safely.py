"""Verify overlapping scheduler ticks skip safely via DB lease."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
    from app.services.config_manager import ConfigManager
    from app.services.fast_training_lease_service import (
        SCHEDULER_TICK_LEASE_KEY,
        FastTrainingLeaseService,
    )

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg_mgr = ConfigManager(session)
        cur = cfg_mgr.get_current()
        cfg_mgr._activate(
            {
                **cur,
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "mode_enabled": True,
                    "scheduler_enabled": True,
                },
            },
            "verifier",
            "verify_overlap",
        )
        lease = FastTrainingLeaseService(session, lease_key=SCHEDULER_TICK_LEASE_KEY)
        ok1, h1 = lease.acquire("test-holder-a")
        assert ok1 is True
        ok2, h2 = lease.acquire("test-holder-b")
        assert ok2 is False
        sched = AutonomousPaperScheduler(session)
        out = sched.tick(operator="cron")
        assert out.get("reason") == "tick_in_progress", out
        lease.release(h1, {"status": "test"})
        session.commit()
    print("verify_scheduler_tick_overlap_skips_safely: PASS")


if __name__ == "__main__":
    main()
