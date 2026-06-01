"""Negative-expectancy evidence is rejected, never promoted to paper_candidate."""

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


def test_negative_expectancy_rejected() -> None:
    s = _mem()
    # Plenty of sample, but negative expectancy after cost -> rejected.
    s.add(ResearchBacktestRun(run_id="rn", strategy_id="crypto_push_pull_momentum", symbols=["AVAX/USD"],
                              status="completed", num_trades=40, sample_size=40, source="autonomous_research_worker",
                              metrics_json={"win_rate": 0.3, "expectancy": -0.4, "profit_factor": 0.6, "max_drawdown_pct": 9.0}))
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence(); s.commit()
    card = s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == "AVAXUSD")).first()
    assert card is not None, "expected AVAX scorecard"
    assert card.verdict == "rejected", (card.verdict, card.blocker_reasons_json)
    assert card.verdict not in ("paper_candidate", "paper_active")
    s.close()
    print(f"no-promotion: negative expectancy -> {card.verdict} — PASS")


if __name__ == "__main__":
    test_negative_expectancy_rejected()
    print("ALL PASS: verify_alpha_factory_no_promotion_from_negative_expectancy")
