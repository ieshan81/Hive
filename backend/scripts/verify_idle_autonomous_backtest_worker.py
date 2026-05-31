"""Idle autonomous research worker — safe, advisory-only, never trades.

Proves:
- the safety gate allows research only when paper + locked + synced + idle (no kill switch,
  no unmanaged position, no urgent exit, no reconciliation drift)
- verdict mapping (reject / watch / promising / paper_test_candidate)
- a run records a ResearchBacktestRun + writes a backtest_research_lesson memory
- the worker exposes no order/live methods and respects the per-hour budget
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.database  # noqa: F401
from app.database import LessonNode, PaperExperimentOutcome, ResearchBacktestRun
from app.services.autonomous_research_worker import (
    AutonomousResearchWorker,
    evaluate_research_safety,
    verdict_from_metrics,
)

CFG: dict = {}
_SAFE = dict(
    paper_mode=True,
    live_locked=True,
    kill_switch_active=False,
    broker_synced=True,
    unmanaged_open_positions=0,
    urgent_exit_pending=False,
    reconciliation_ok=True,
    scheduler_healthy=True,
)


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_safety_gate() -> None:
    assert evaluate_research_safety(**_SAFE).ok
    for unsafe in (
        {"paper_mode": False},
        {"live_locked": False},
        {"kill_switch_active": True},
        {"broker_synced": False},
        {"unmanaged_open_positions": 1},
        {"urgent_exit_pending": True},
        {"reconciliation_ok": False},
        {"scheduler_healthy": False},
    ):
        base = dict(_SAFE)
        base.update(unsafe)
        assert not evaluate_research_safety(**base).ok, unsafe
    print("research: safety gate allows ONLY paper+locked+synced+idle — PASS")


def test_verdict_logic() -> None:
    assert verdict_from_metrics(sample_size=2, win_rate=1.0, expectancy=1.0, max_drawdown_pct=0.0, fee_adjusted_pnl=2.0, profit_factor=999.0)[0] == "watch"
    assert verdict_from_metrics(sample_size=10, win_rate=0.3, expectancy=-0.1, max_drawdown_pct=2.0, fee_adjusted_pnl=-1.0, profit_factor=0.5)[0] == "reject"
    assert verdict_from_metrics(sample_size=10, win_rate=0.6, expectancy=0.2, max_drawdown_pct=3.0, fee_adjusted_pnl=2.0, profit_factor=2.0)[0] == "paper_test_candidate"
    assert verdict_from_metrics(sample_size=10, win_rate=0.5, expectancy=0.05, max_drawdown_pct=5.0, fee_adjusted_pnl=0.5, profit_factor=1.2)[0] == "promising"
    print("research: verdict mapping reject/watch/promising/paper_test_candidate — PASS")


def test_run_records_result_and_lesson() -> None:
    s = _mem()
    for x in (2.0, 3.0, -1.0, 2.5, 1.5, 2.0):
        s.add(PaperExperimentOutcome(strategy_id="strategyA", symbol="SOL/USD", realized_pnl=x, fees_estimated=0.1, exit_reason="take_profit"))
    s.commit()
    res = AutonomousResearchWorker(s, CFG).run_one("strategyA", "SOL/USD")
    s.commit()
    assert res["status"] == "ok", res
    assert res["verdict"] in ("reject", "watch", "promising", "paper_test_candidate"), res
    runs = list(s.exec(select(ResearchBacktestRun).where(ResearchBacktestRun.source == "autonomous_research_worker")).all())
    assert len(runs) == 1 and (runs[0].metrics_json or {}).get("verdict"), runs
    lessons = list(s.exec(select(LessonNode).where(LessonNode.memory_type == "backtest_research_lesson")).all())
    assert len(lessons) >= 1, lessons
    s.close()
    print(f"research: run_one records ResearchBacktestRun + backtest_research_lesson [{res['verdict']}] — PASS")


def test_never_trades_and_respects_budget() -> None:
    s = _mem()
    w = AutonomousResearchWorker(s, CFG)
    for attr in ("place_order", "submit_order", "enable_live", "buy", "sell", "cancel_order"):
        assert not hasattr(w, attr), f"worker must not expose {attr}"
    st = w.status()
    assert st["never_places_orders"] and st["advisory_only"], st
    # Per-hour budget: seed max runs, then maybe_run must skip before doing anything.
    for i in range(int(w.cfg["idle_research_max_runs_per_hour"])):
        s.add(ResearchBacktestRun(run_id=f"r{i}", strategy_id="x", symbols=["A/USD"], source="autonomous_research_worker"))
    s.commit()
    res = w.maybe_run()
    assert res["status"] == "skipped" and res["reason"] == "hourly_budget_reached", res
    s.close()
    print("research: no order/live methods; per-hour budget enforced — PASS")


if __name__ == "__main__":
    test_safety_gate()
    test_verdict_logic()
    test_run_records_result_and_lesson()
    test_never_trades_and_respects_budget()
    print("ALL PASS: verify_idle_autonomous_backtest_worker")
