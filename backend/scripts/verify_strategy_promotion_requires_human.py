import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from sqlmodel import Session
from app.services.research_lab_service import ResearchLabService


def main():
    init_db()
    with Session(engine) as session:
        out = ResearchLabService(session).promote_to_paper_candidate(
            "crypto_push_pull", {"proposed_by": "test"}
        )
        session.commit()
        assert "human approval" in out.get("message", "").lower()
        assert out["candidate"]["human_approved"] is False
        print("verify_strategy_promotion_requires_human: OK")


if __name__ == "__main__":
    main()
