"""Zero-sample evidence can never become a paper_candidate (stays unproven/watch)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.database  # noqa: F401
from app.database import AlphaScorecard, ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

CFG = {"alpha_factory": {"min_sample_size": 5}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_zero_sample_not_promoted() -> None:
    s = _mem()
    # Zero sample, even with a (meaningless) high PF — must NOT promote.
    s.add(ResearchBacktestRun(run_id="r0", strategy_id="crypto_push_pull_baseline", symbols=["DOGE/USD"],
                              status="completed", num_trades=0, sample_size=0, source="autonomous_research_worker",
                              metrics_json={"expectancy": 0.0, "profit_factor": 9.0, "max_drawdown_pct": 1.0}))
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence(); s.commit()
    cards = list(s.exec(select(AlphaScorecard)).all())
    assert cards, "expected a scorecard"
    for c in cards:
        assert c.verdict not in ("paper_candidate", "paper_active"), (c.symbol, c.verdict)
        assert c.verdict in ("unproven", "watch"), (c.symbol, c.verdict)
    s.close()
    print(f"no-promotion: zero sample -> {cards[0].verdict} (never paper_candidate) — PASS")


if __name__ == "__main__":
    test_zero_sample_not_promoted()
    print("ALL PASS: verify_alpha_factory_no_promotion_from_zero_sample")
