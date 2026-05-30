"""Per-position exit-plan resolution + exit-monitor status (paper, read-only).

Proves:
- a position whose opening signal carries an explicit lever (stop-loss / take-profit)
  is managed (has_exit_plan, source "entry_signal")
- a position with no opening signal is flagged missing_exit_plan (source "none")
- a config-derived hard-safety stop is reported but does NOT, by itself, count as a
  documented per-position plan (the position still trips missing_exit_plan)
- open_positions_missing_exit_plan returns only the unmanaged symbol
- exit_monitor_status is paper/live-locked and surfaces the missing-plan symbol
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.database import StrategySignal
import app.services.exit_monitor_service as ems
from app.services.exit_monitor_service import (
    open_positions_missing_exit_plan,
    resolve_exit_plan,
)

CFG = {
    "autonomous_paper_learning": {
        "max_unrealized_loss_pct": 1.5,
        "block_new_entry_if_unmanaged_position": True,
    },
    "paper_learning": {"require_position_monitor": True},
}


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed(session: Session) -> None:
    # MANAGED: opening entry signal carries explicit exit levers.
    session.add(StrategySignal(strategy="t", symbol="MANAGED", signal="buy", signal_type="entry", stop_loss=95.0, take_profit=110.0))
    # HARD: opening entry signal with NO documented lever (only config hard stop applies).
    session.add(StrategySignal(strategy="t", symbol="HARD", signal="buy", signal_type="entry"))
    session.commit()


def test_managed_position_has_plan() -> None:
    session = _mem_session()
    _seed(session)
    plan = resolve_exit_plan(session, CFG, "MANAGED", avg_entry=100.0, current_price=101.0)
    assert plan["has_exit_plan"] is True, plan
    assert plan["missing_exit_plan"] is False, plan
    assert plan["exit_plan_source"] == "entry_signal", plan
    assert plan["stop_loss"] == 95.0 and plan["take_profit"] == 110.0, plan
    session.close()
    print("exit-monitor: managed position has documented plan — PASS")


def test_unmanaged_position_flagged() -> None:
    session = _mem_session()
    _seed(session)
    plan = resolve_exit_plan(session, CFG, "UNMANAGED", avg_entry=100.0)
    assert plan["missing_exit_plan"] is True, plan
    assert plan["has_exit_plan"] is False, plan
    assert plan["exit_plan_source"] == "none", plan
    session.close()
    print("exit-monitor: unmanaged position flagged missing_exit_plan — PASS")


def test_config_hard_stop_does_not_count() -> None:
    session = _mem_session()
    _seed(session)
    plan = resolve_exit_plan(session, CFG, "HARD", avg_entry=100.0)
    # Config hard-safety stop is computed and reported …
    assert plan["hard_safety_stop_price"] is not None, plan
    assert abs(plan["hard_safety_stop_price"] - 98.5) < 1e-6, plan
    # … but it does NOT make the position "managed".
    assert plan["missing_exit_plan"] is True, plan
    session.close()
    print("exit-monitor: config hard stop does not satisfy per-position plan — PASS")


def test_open_positions_missing_only_unmanaged() -> None:
    session = _mem_session()
    _seed(session)
    missing = open_positions_missing_exit_plan(
        session,
        CFG,
        positions=[{"symbol": "MANAGED", "qty": 1}, {"symbol": "UNMANAGED", "qty": 1}],
    )
    assert missing == ["UNMANAGED"], missing
    session.close()
    print("exit-monitor: only the unmanaged symbol is reported — PASS")


def test_exit_monitor_status_paper_locked() -> None:
    session = _mem_session()
    _seed(session)

    fake_pos = type(
        "P",
        (),
        {"symbol": "UNMANAGED", "qty": 1.0, "avg_entry_price": 100.0, "current_price": 99.0, "unrealized_pl": -1.0},
    )()
    orig_alpaca, orig_tes = ems.AlpacaAdapter, ems.TrainingExecutionService
    ems.AlpacaAdapter = type(
        "FakeAlpaca", (), {"__init__": lambda self, *a, **k: None, "sync_positions_cached": lambda self: [fake_pos]}
    )
    ems.TrainingExecutionService = type(
        "FakeTES", (), {"__init__": lambda self, *a, **k: None, "monitor_exits": lambda self: {"status": "ok", "checked": 1}}
    )
    try:
        st = ems.exit_monitor_status(session, CFG)
    finally:
        ems.AlpacaAdapter, ems.TrainingExecutionService = orig_alpaca, orig_tes

    assert st["schema_version"] == 3, st
    assert st["live_locked"] is True, st
    assert st["broker_mode"] == "paper", st
    assert st["open_positions_count"] == 1, st
    assert st["any_missing_exit_plan"] is True, st
    assert st["missing_exit_plan_symbols"] == ["UNMANAGED"], st
    session.close()
    print("exit-monitor: status is paper/live-locked and surfaces missing plan — PASS")


if __name__ == "__main__":
    test_managed_position_has_plan()
    test_unmanaged_position_flagged()
    test_config_hard_stop_does_not_count()
    test_open_positions_missing_only_unmanaged()
    test_exit_monitor_status_paper_locked()
    print("ALL PASS: verify_paper_exit_monitor")
