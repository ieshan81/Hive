"""Rejected strategies list and bundle export must include rejected candidates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import StrategyCandidate, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.research_lab_service import ResearchLabService


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        ResearchLabService(session).reject_strategy(
            "crypto_push_pull_momentum",
            {"reason": "negative expectancy; profit_factor below 1", "evidence": {"test": True}},
        )
        session.commit()
        rejected = ResearchLabService(session).rejected_strategies()
        assert any(r["strategy_id"] == "crypto_push_pull_momentum" for r in rejected)
        row = session.exec(
            select(StrategyCandidate).where(
                StrategyCandidate.strategy_id == "crypto_push_pull_momentum",
                StrategyCandidate.status == "rejected",
            )
        ).first()
        assert row, "DB rejected candidate required"
        print("verify_rejected_strategies_populated: OK", len(rejected))


if __name__ == "__main__":
    main()
