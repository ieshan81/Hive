"""Verify scheduler/enable does not change validation_run_id or reset epoch."""

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
    from app.services.nuke_epoch_service import get_latest_reset_epoch

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        before = get_latest_reset_epoch(session) or {}
        run_before = before.get("validation_run_id")
        epoch_before = before.get("reset_epoch")
        AutonomousPaperScheduler(session).enable("verifier")
        session.commit()
        after = get_latest_reset_epoch(session) or {}
        assert after.get("validation_run_id") == run_before
        assert after.get("reset_epoch") == epoch_before
    print("verify_scheduler_enable_preserves_validation_run: PASS")


if __name__ == "__main__":
    main()
