import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.lesson_memory_service import LessonMemoryService
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        svc = LessonMemoryService(session, DEFAULT_CONFIG)
        row = svc.propose_ai_lesson(
            title="Bad",
            summary="No refs",
            detailed_lesson="Invented",
            evidence_refs=[],
        )
        session.commit()
        assert row.unsupported_claim or row.action_status == "rejected"
        print("verify_ai_memory_requires_evidence: PASS")


if __name__ == "__main__":
    test()
