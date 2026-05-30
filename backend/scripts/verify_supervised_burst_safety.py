"""Supervised burst is bounded and auto-stops on any material event (paper-only).

Proves:
- the burst stop-code set covers every cap / duplicate / exit-plan / kill / drift code
- ticks are bounded to at most 10 even when more are requested
- a placed order stops the burst after that tick
- a paused scheduler is a no-op (0 ticks, tick never entered)
- a pre-tick environment hard-stop (kill switch) stops BEFORE any tick runs
- every result is live-locked
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

CFG = {"autonomous_paper_learning": {"scheduler_interval_seconds": 600, "mode_enabled": True, "scheduler_enabled": True}}

_REQUIRED_STOP_CODES = (
    "DUPLICATE_SYMBOL_POSITION",
    "DUPLICATE_RECENT_ORDER",
    "DUPLICATE_OPEN_ORDER",
    "OPEN_POSITION_MISSING_EXIT_PLAN",
    "ABSOLUTE_MAX_OPEN_POSITIONS",
    "ABSOLUTE_HOURLY_ENTRY_CAP",
    "ABSOLUTE_DAILY_ENTRY_CAP",
    "ABSOLUTE_CYCLE_CAP",
    "KILL_SWITCH_ACTIVE",
    "RECONCILIATION_DRIFT",
)


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _sched() -> AutonomousPaperScheduler:
    return AutonomousPaperScheduler(_mem_session(), CFG)


def test_stop_codes_cover_caps() -> None:
    codes = set(AutonomousPaperScheduler._BURST_STOP_CODES)
    for code in _REQUIRED_STOP_CODES:
        assert code in codes, code
    print("burst: stop-code set covers every cap/duplicate/exit/kill/drift code — PASS")


def test_bounded_to_ten() -> None:
    sched = _sched()
    sched._burst_environment_block = lambda: None
    sched.tick = lambda **kw: {"status": "ok", "cycle_result": {"orders_created": 0}}
    out = sched.supervised_burst(max_ticks=99)
    assert out["status"] == "ok", out
    assert out["requested_ticks"] == 10, out
    assert out["ticks_run"] == 10, out
    assert out["stopped_reason"] is None, out
    assert out["live_locked"] is True, out
    sched.session.close()
    print("burst: bounded to 10 ticks even when 99 requested — PASS")


def test_order_stops_burst() -> None:
    sched = _sched()
    sched._burst_environment_block = lambda: None
    sched.tick = lambda **kw: {"status": "ok", "cycle_result": {"orders_created": 1}}
    out = sched.supervised_burst(max_ticks=5)
    assert out["ticks_run"] == 1, out
    assert out["stopped_reason"] == "order_placed", out
    assert out["live_locked"] is True, out
    sched.session.close()
    print("burst: a placed order stops the burst after that tick — PASS")


def test_paused_is_noop() -> None:
    sched = _sched()
    called: list[int] = []
    sched.tick = lambda **kw: called.append(1) or {"status": "ok", "cycle_result": {}}
    sched._state["paused"] = True
    out = sched.supervised_burst(max_ticks=3)
    assert out["status"] == "noop", out
    assert out["ticks_run"] == 0, out
    assert out["live_locked"] is True, out
    assert called == [], "tick must not run while paused"
    sched.session.close()
    print("burst: paused scheduler is a no-op (0 ticks) — PASS")


def test_environment_block_stops_before_tick() -> None:
    sched = _sched()
    called: list[int] = []
    sched._burst_environment_block = lambda: "kill_switch_active"
    sched.tick = lambda **kw: called.append(1) or {"status": "ok", "cycle_result": {}}
    out = sched.supervised_burst(max_ticks=3)
    assert out["ticks_run"] == 0, out
    assert out["stopped_reason"] == "kill_switch_active", out
    assert called == [], "tick must not run when environment is blocked"
    assert out["live_locked"] is True, out
    sched.session.close()
    print("burst: environment hard-stop halts before any tick runs — PASS")


if __name__ == "__main__":
    test_stop_codes_cover_caps()
    test_bounded_to_ten()
    test_order_stops_burst()
    test_paused_is_noop()
    test_environment_block_stops_before_tick()
    print("ALL PASS: verify_supervised_burst_safety")
