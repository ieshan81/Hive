"""The fixed daily trade-count cap no longer blocks trading by itself.

Proves:
- the adaptive budget allows entries far beyond the retired 6/day count when
  risk/edge/protection checks pass (count is telemetry, not a blocker)
- the scheduler no longer hard-pauses on a daily tick count — it PACES instead
- status surfaces pacing + adaptive-budget telemetry
- risk protections still block when appropriate
- DEFAULT_CONFIG keeps open/hourly/cycle caps HARD while daily counts become
  generous telemetry references, and adds the adaptive budget + protections.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.services.adaptive_opportunity_budget import BudgetInputs, evaluate_opportunity_budget
from app.services.paper_trade_protections import ProtectionContext, run_all_protections
from app.services.default_config import DEFAULT_CONFIG


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_entries_exceed_old_count() -> None:
    # 50 entries today — far past the retired 6/day cap — still allowed on good signal/edge.
    d = evaluate_opportunity_budget(
        BudgetInputs(
            symbol="SOL/USD",
            equity=1000.0,
            signal_score=0.85,
            edge_after_cost_bps=60.0,
            entries_today=50,
            orders_today=50,
        ),
        {},
    )
    assert d.allowed and d.reason == "ok", d
    print("no-fixed-cap: 50 entries/day allowed when checks pass — PASS")


def test_protections_still_block() -> None:
    pr = run_all_protections(ProtectionContext(symbol="SOL/USD", drawdown_pct=20.0), {})
    d = evaluate_opportunity_budget(
        BudgetInputs(symbol="SOL/USD", equity=1000.0, signal_score=0.85, edge_after_cost_bps=60.0),
        {},
        pr,
    )
    assert not d.allowed and d.reason == "MAX_DRAWDOWN_PROTECTION", d
    print("no-fixed-cap: risk protections still block (drawdown) — PASS")


def test_scheduler_does_not_stop_on_tick_count() -> None:
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    session = _mem_session()
    cfg = {
        "autonomous_paper_learning": {
            "scheduler_enabled": True,
            "mode_enabled": True,
            "use_capital_allocator": True,
            "scheduler_interval_seconds": 600,
        }
    }
    sched = AutonomousPaperScheduler(session, cfg)
    # A recent tick + an absurd tick count: the old code paused with
    # "absolute_daily_tick_cap_reached"; the new code must PACE, not stop.
    sched._state["last_tick_at"] = datetime.utcnow().isoformat() + "Z"
    sched._state["ticks_today"] = 9999
    res = sched.tick(operator="cron")
    assert res.get("status") != "stopped", res
    assert res.get("reason") != "absolute_daily_tick_cap_reached", res
    assert sched._state.get("paused") is not True, res
    session.close()
    print(f"no-fixed-cap: scheduler paces (no daily tick stop) at 9999 ticks [{res.get('reason')}] — PASS")


def test_status_telemetry_fields() -> None:
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    session = _mem_session()
    st = AutonomousPaperScheduler(session, {"autonomous_paper_learning": {}}).status()
    assert "effective_interval_seconds" in st, st
    assert "configured_interval_seconds" in st, st
    assert st.get("ticks_today_telemetry_only") is True, st
    ab = st.get("adaptive_opportunity_budget", {})
    assert ab.get("enabled") is True, st
    assert ab.get("replaces_fixed_daily_entry_cap") is True, st
    assert st.get("live_locked") is True, st
    session.close()
    print("no-fixed-cap: status surfaces pacing + adaptive-budget telemetry — PASS")


def test_default_config_shape() -> None:
    apl = DEFAULT_CONFIG["autonomous_paper_learning"]
    assert apl["absolute_max_open_positions"] == 3, apl["absolute_max_open_positions"]
    assert apl["opportunity_budget"]["enabled"] is True
    assert apl["protections"]["enabled"] is True
    # Daily entry count is now a generous telemetry reference (no longer the 6/day stop).
    assert apl["absolute_max_new_entries_per_day"] >= 100, apl["absolute_max_new_entries_per_day"]
    # Hourly entry cap remains a HARD anti-spam pacing bound.
    assert apl["absolute_max_new_entries_per_hour"] >= 1, apl["absolute_max_new_entries_per_hour"]
    print("no-fixed-cap: DEFAULT_CONFIG keeps hard caps + adds adaptive budget — PASS")


if __name__ == "__main__":
    test_entries_exceed_old_count()
    test_protections_still_block()
    test_scheduler_does_not_stop_on_tick_count()
    test_status_telemetry_fields()
    test_default_config_shape()
    print("ALL PASS: verify_no_fixed_daily_trade_cap")
