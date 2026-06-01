"""Bootstrap is idempotent: re-running updates existing scorecards, no duplicate spam."""

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


def test_idempotent() -> None:
    s = _mem()
    s.add(ResearchBacktestRun(run_id="r1", strategy_id="crypto_push_pull_baseline", symbols=["UNI/USD"],
                              status="completed", num_trades=2, sample_size=2, source="autonomous_research_worker",
                              metrics_json={"expectancy": 0.0, "profit_factor": 0.9, "max_drawdown_pct": 3.0}))
    s.add(ResearchBacktestRun(run_id="r2", strategy_id="crypto_push_pull_baseline", symbols=["UNI/USD"],
                              status="completed", num_trades=4, sample_size=4, source="autonomous_research_worker",
                              metrics_json={"expectancy": 0.0, "profit_factor": 1.0, "max_drawdown_pct": 3.0}))
    s.commit()
    svc = AutonomousAlphaFactoryService(s, CFG)
    svc.bootstrap_scorecards_from_existing_evidence(); s.commit()
    count1 = int(s.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
    svc.bootstrap_scorecards_from_existing_evidence(); s.commit()
    count2 = int(s.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
    # Two runs for the SAME (strategy, symbol) must collapse to ONE scorecard, stable across runs.
    assert count1 == 1, count1
    assert count2 == count1, (count1, count2)
    s.close()
    print(f"idempotent: 2 runs same target -> 1 scorecard; re-run stable at {count2} — PASS")


if __name__ == "__main__":
    test_idempotent()
    print("ALL PASS: verify_alpha_factory_bootstrap_idempotent")
