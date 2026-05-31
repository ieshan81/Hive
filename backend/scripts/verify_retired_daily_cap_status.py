"""Status/UI must not treat the retired fixed daily entry cap as an active blocker.

Proves (when adaptive opportunity budget replaces the fixed daily cap):
- entry_cap_hit is not true solely because new_entries_today >= old 6/day reference
- daily entry count is surfaced as telemetry (retired mode, non-blocking)
- hourly / open-position hard caps still appear as active blockers at the boundary
- adaptive budget summary still reports replaces_fixed_daily_entry_cap
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.database import ExecutionLog
from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
from app.services.paper_autopilot_caps import cap_status, resolve_cap


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed_entries(session: Session, count: int, *, hours_apart: float = 2.0) -> None:
    """Seed buy fills spread across time so daily count can exceed hourly cap separately."""
    now = datetime.utcnow()
    for i in range(count):
        session.add(
            ExecutionLog(
                event_id=f"e{i}",
                cycle_run_id="c",
                symbol="DOGE/USD",
                side="buy",
                status="paper_order_filled",
                submitted_at=now - timedelta(hours=i * hours_apart),
            )
        )
    session.commit()


def _adaptive_cfg(**overrides: object) -> dict:
    apl = {
        "opportunity_budget": {"enabled": True},
        **overrides,
    }
    return {"autonomous_paper_learning": apl}


def test_daily_count_not_blocking_when_retired() -> None:
    session = _mem_session()
    cfg = _adaptive_cfg()
    cap = resolve_cap(cfg, "absolute_max_new_entries_per_day")
    _seed_entries(session, cap)

    st = cap_status(session, cfg)
    assert st["new_entries_today"] >= cap, st
    assert st.get("daily_entry_cap_mode") == "retired", st
    assert st.get("daily_entry_count_is_blocking") is False, st
    assert st.get("active_trade_gate") == "adaptive_opportunity_budget", st
    assert st.get("entries_today_remaining") is None, st
    assert st.get("entry_cap_hit") is False, st
    assert "absolute_max_new_entries_per_day" not in (st.get("entry_cap_hit_reasons") or []), st
    sem = st.get("absolute_max_new_entries_per_day_semantics") or {}
    assert sem.get("mode") == "legacy_telemetry", st
    assert sem.get("blocking") is False, st

    sched = AutonomousPaperScheduler(session, cfg).status()
    assert sched.get("entry_cap_hit") is False, sched
    ab = sched.get("adaptive_opportunity_budget") or {}
    assert ab.get("replaces_fixed_daily_entry_cap") is True, sched
    session.close()
    print("retired-daily-cap: count at old cap does not block status — PASS")


def test_hourly_cap_still_blocks_status() -> None:
    session = _mem_session()
    cfg = _adaptive_cfg()
    hour_cap = resolve_cap(cfg, "absolute_max_new_entries_per_hour")
    now = datetime.utcnow()
    for i in range(hour_cap):
        session.add(
            ExecutionLog(
                event_id=f"h{i}",
                cycle_run_id="c",
                symbol="DOGE/USD",
                side="buy",
                status="paper_order_filled",
                submitted_at=now - timedelta(minutes=i * 5),
            )
        )
    session.commit()

    st = cap_status(session, cfg)
    assert st.get("entry_cap_hit") is True, st
    assert "absolute_max_new_entries_per_hour" in (st.get("entry_cap_hit_reasons") or []), st
    assert "absolute_max_new_entries_per_day" not in (st.get("entry_cap_hit_reasons") or []), st
    assert st.get("daily_entry_count_is_blocking") is False, st
    session.close()
    print("retired-daily-cap: hourly hard cap still visible as blocker — PASS")


def test_open_positions_still_blocks_status() -> None:
    from app.database import PositionSnapshot

    session = _mem_session()
    cfg = _adaptive_cfg()
    open_cap = resolve_cap(cfg, "absolute_max_open_positions")
    for i in range(open_cap):
        session.add(
            PositionSnapshot(
                symbol=f"S{i}",
                qty=1.0,
                avg_entry_price=1.0,
                synced_at=datetime.utcnow(),
            )
        )
    session.commit()

    st = cap_status(session, cfg)
    assert st.get("entry_cap_hit") is True, st
    assert "absolute_max_open_positions" in (st.get("entry_cap_hit_reasons") or []), st
    session.close()
    print("retired-daily-cap: open-position hard cap still visible — PASS")


def test_legacy_fixed_cap_mode_when_budget_disabled() -> None:
    session = _mem_session()
    cfg = {"autonomous_paper_learning": {"opportunity_budget": {"enabled": False}}}
    cap = resolve_cap(cfg, "absolute_max_new_entries_per_day")
    _seed_entries(session, cap)

    st = cap_status(session, cfg)
    assert st.get("daily_entry_cap_mode") == "fixed_cap", st
    assert st.get("entry_cap_hit") is True, st
    assert "absolute_max_new_entries_per_day" in (st.get("entry_cap_hit_reasons") or []), st
    session.close()
    print("retired-daily-cap: legacy fixed-cap status when budget disabled — PASS")


if __name__ == "__main__":
    test_daily_count_not_blocking_when_retired()
    test_hourly_cap_still_blocks_status()
    test_open_positions_still_blocks_status()
    test_legacy_fixed_cap_mode_when_budget_disabled()
    print("ALL PASS: verify_retired_daily_cap_status")
