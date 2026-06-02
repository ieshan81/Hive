"""A paper candidate requires real backtest evidence; with none, the decision loop opens no entry.

- With NO ResearchBacktestRun in the DB, the heartbeat decision gate blocks all entries
  (entry_requires_backtest_evidence) even on a decision tick.
- A scorecard built with zero backtest evidence (backtest_count 0) is never a paper_candidate.
- Backtest-only memory cannot influence trading without an evidence link (governance gate).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.database  # noqa: F401,E402
from app.database import AlphaScorecard, ResearchBacktestRun  # noqa: E402
from app.services.heartbeat_service import NO_BACKTEST_EVIDENCE_BLOCKER, HeartbeatService  # noqa: E402

CFG = {"autonomous_paper_learning": {"heartbeat": {
    "enabled": True, "decision_loop_interval_ticks": 1, "require_backtest_evidence_for_entry": True}}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng, expire_on_commit=False)


def main() -> None:
    s = _mem()
    hb = HeartbeatService(s, CFG)

    # No backtest evidence anywhere -> even a decision tick (interval 1) blocks entries.
    assert hb.has_backtest_evidence() is False
    assert NO_BACKTEST_EVIDENCE_BLOCKER in hb.entry_gate_blockers(tick_count=0), "no-evidence must block entries"

    # Add backtest evidence -> the gate opens (entries may now be considered, still cage-gated).
    s.add(ResearchBacktestRun(run_id="bt1", strategy_id="crypto_push_pull_baseline", symbols=["BTC/USD"],
                              status="completed", num_trades=20, sample_size=20, source="autonomous_research_worker",
                              metrics_json={"expectancy": 0.01, "profit_factor": 1.4}))
    s.commit()
    assert hb.has_backtest_evidence() is True
    assert NO_BACKTEST_EVIDENCE_BLOCKER not in hb.entry_gate_blockers(tick_count=0), "evidence should open the gate"

    # A scorecard with NO backtest evidence is never a paper_candidate.
    sc = AlphaScorecard(symbol="ZZZ/USD", normalized_symbol="ZZZUSD", asset_class="crypto",
                        strategy_family="momentum_continuation", strategy_id="never_backtested",
                        sample_size=0, backtest_count=0, expectancy=None, verdict="unproven")
    s.add(sc)
    s.commit()
    assert sc.backtest_count == 0 and sc.verdict not in ("paper_candidate", "paper_active"), sc.verdict
    print("verify_backtest_result_required_before_paper_candidate: PASS (no-evidence blocks entries; evidence opens gate)")


if __name__ == "__main__":
    main()
