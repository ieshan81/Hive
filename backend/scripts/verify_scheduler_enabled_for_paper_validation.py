"""Verify scheduler enable path keeps live locked and exposes tick status."""

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

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg_mgr = ConfigManager(session)
        cur = cfg_mgr.get_current()
        merged = {**cur, "autonomous_paper_learning": {**(cur.get("autonomous_paper_learning") or {}), "mode_enabled": True}}
        cfg_mgr._activate(merged, "verifier", "verify_scheduler")
        out = AutonomousPaperScheduler(session).enable("verifier")
        session.commit()
        assert out.get("scheduler_enabled") is True
        assert out.get("live_locked") is True
        assert "last_tick_at" in out
        assert "tick_in_progress" in out
    print("verify_scheduler_enabled_for_paper_validation: PASS")


if __name__ == "__main__":
    main()
