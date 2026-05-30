"""Absolute paper-autopilot caps cannot be disabled or exceeded.

Proves:
- protective defaults apply when a cap is missing / 0 / negative / invalid
  (a cap can never be turned into "unlimited")
- absolute caps survive use_capital_allocator=True (opportunity mode)
- the scheduler interval is floored at 60s (never sub-minute)
- cap_status flags the daily entry cap as hit at the boundary
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.database import ExecutionLog
from app.services.paper_autopilot_caps import (
    ABSOLUTE_CAP_DEFAULTS,
    all_caps,
    cap_status,
    resolve_cap,
)


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_defaults_never_unlimited() -> None:
    assert resolve_cap({}, "absolute_max_new_entries_per_day") == 6
    for bad in (0, -1, -999, "x", None, 0.0):
        cfg = {"autonomous_paper_learning": {"absolute_max_new_entries_per_day": bad}}
        assert resolve_cap(cfg, "absolute_max_new_entries_per_day") == 6, bad
    # A legitimate positive override is honored (operator may tighten/loosen within reason).
    cfg = {"autonomous_paper_learning": {"absolute_max_new_entries_per_day": 4}}
    assert resolve_cap(cfg, "absolute_max_new_entries_per_day") == 4
    print("caps: defaults never unlimited — PASS")


def test_caps_survive_allocator() -> None:
    cfg = {"autonomous_paper_learning": {"use_capital_allocator": True}}
    caps = all_caps(cfg)
    for key, default in ABSOLUTE_CAP_DEFAULTS.items():
        assert caps[key] == default, (key, caps[key], default)
    print("caps: survive use_capital_allocator=True — PASS")


def test_interval_floor() -> None:
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    session = _mem_session()
    cfg = {"autonomous_paper_learning": {"scheduler_interval_seconds": 10}}
    st = AutonomousPaperScheduler(session, cfg).status()
    assert st["interval_seconds"] == 60, st["interval_seconds"]
    assert st["live_locked"] is True
    session.close()
    print("caps: scheduler interval floored to 60s — PASS")


def test_cap_status_entry_hit() -> None:
    session = _mem_session()
    cfg: dict = {}
    base = cap_status(session, cfg)
    assert base["entry_cap_hit"] is False, base

    cap = resolve_cap(cfg, "absolute_max_new_entries_per_day")
    for i in range(cap):
        session.add(
            ExecutionLog(
                event_id=f"e{i}",
                cycle_run_id="c",
                symbol="DOGE/USD",
                side="buy",
                status="paper_order_filled",
                submitted_at=datetime.utcnow(),
            )
        )
    session.commit()

    hit = cap_status(session, cfg)
    assert hit["new_entries_today"] == cap, hit
    assert hit["entry_cap_hit"] is True, hit
    assert "absolute_max_new_entries_per_day" in hit["entry_cap_hit_reasons"], hit
    session.close()
    print("caps: cap_status flags daily entry cap at boundary — PASS")


if __name__ == "__main__":
    test_defaults_never_unlimited()
    test_caps_survive_allocator()
    test_interval_floor()
    test_cap_status_entry_hit()
    print("ALL PASS: verify_paper_autopilot_caps")
