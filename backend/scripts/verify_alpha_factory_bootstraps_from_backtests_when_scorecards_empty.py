"""Alpha Factory bootstraps scorecards from existing backtest evidence when empty."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

import app.database  # noqa: F401
from app.database import AlphaScorecard, ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

CFG = {"alpha_factory": {"min_sample_size": 5}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed_run(s, run_id, strategy_id, symbols, *, sample, win, exp, pf, dd, source="autonomous_research_worker"):
    s.add(ResearchBacktestRun(
        run_id=run_id, strategy_id=strategy_id, symbols=symbols, status="completed",
        num_trades=sample, sample_size=sample, source=source,
        metrics_json={"win_rate": win, "expectancy": exp, "profit_factor": pf, "max_drawdown_pct": dd},
        cost_model_json={"round_trip_cost_pct": 0.001},
    ))


def test_bootstrap_creates_scorecards() -> None:
    s = _mem()
    _seed_run(s, "r1", "crypto_push_pull_baseline", ["UNI/USD"], sample=2, win=0.5, exp=0.0, pf=0.9, dd=3.0)
    _seed_run(s, "r2", "crypto_push_pull_momentum", ["ETH/USD"], sample=20, win=0.4, exp=-0.2, pf=0.6, dd=8.0)
    s.commit()
    before = int(s.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
    assert before == 0, before

    out = AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    after = int(s.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
    assert after >= 2, (after, out)
    assert out["scorecards_total"] >= 2 and out["evidence_runs_scanned"] >= 2, out

    # status no longer reports no_scorecards
    st = AutonomousAlphaFactoryService(s, CFG).get_status()
    assert st["reason"] != "no_scorecards", st
    s.close()
    print(f"bootstrap: {after} scorecards created from backtest evidence; status.reason={st['reason']} — PASS")


if __name__ == "__main__":
    test_bootstrap_creates_scorecards()
    print("ALL PASS: verify_alpha_factory_bootstraps_from_backtests_when_scorecards_empty")
