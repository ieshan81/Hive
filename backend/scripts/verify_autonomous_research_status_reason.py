"""Autonomous research status exposes counts, latest verdicts, and skip reason."""

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
    cfg = {"autonomous_paper_learning": {"autonomous_research": {"autonomous_backtest_worker_enabled": False}}}
    with Session(eng) as session:
        st = AutonomousResearchWorker(session, cfg).status()
    assert st["enabled"] is False, st
    assert "target_count" in st and "last_skip_reason" in st, st
    assert st["last_skip_reason"] == "disabled", st
    assert st["never_places_orders"] is True and st["advisory_only"] is True, st
    print("verify_autonomous_research_status_reason: PASS")
    print({"enabled": st["enabled"], "target_count": st["target_count"], "last_skip_reason": st["last_skip_reason"]})


if __name__ == "__main__":
    main()
