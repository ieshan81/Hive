"""Legacy autonomous_research evidence is converted into Alpha Factory scorecards."""

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


def test_legacy_run_creates_scorecard() -> None:
    s = _mem()
    s.add(ResearchBacktestRun(run_id="legacy-1", strategy_id="crypto_push_pull", symbols=["LINK/USD"],
                              status="completed", num_trades=12, sample_size=12, source="autonomous_research_worker",
                              metrics_json={"win_rate": 0.45, "expectancy": -0.05, "profit_factor": 0.9, "max_drawdown_pct": 6.0}))
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence(); s.commit()
    card = s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == "LINKUSD")).first()
    assert card is not None, "legacy research run did not produce a scorecard"
    assert card.strategy_id == "crypto_push_pull", card.strategy_id
    assert "legacy-1" in (card.evidence_ids_json or []), card.evidence_ids_json
    assert card.display_symbol if hasattr(card, "display_symbol") else card.symbol  # symbol retained
    s.close()
    print("old-research: legacy autonomous_research_worker run -> Alpha scorecard with evidence id — PASS")


if __name__ == "__main__":
    test_legacy_run_creates_scorecard()
    print("ALL PASS: verify_old_research_writes_alpha_scorecard")
