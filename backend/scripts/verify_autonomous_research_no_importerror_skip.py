"""Autonomous research status must expose explicit skip reasons, not ImportError mush."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.services.autonomous_research_worker import AutonomousResearchWorker


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        out = AutonomousResearchWorker(session, {"autonomous_paper_learning": {"autonomous_research": {"autonomous_backtest_worker_enabled": True}}}).status()
    reason = str(out.get("last_skip_reason") or "")
    assert "safety_probe_error:ImportError" not in reason, out
    assert reason in ("no_targets", "broker_not_synced") or reason.startswith("safety_not_ok:"), out
    print("verify_autonomous_research_no_importerror_skip: PASS")
    print({"last_skip_reason": reason})


if __name__ == "__main__":
    main()
