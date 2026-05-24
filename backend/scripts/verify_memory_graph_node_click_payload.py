import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import LessonNode, init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.lesson_memory_service import LessonMemoryService
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        svc = LessonMemoryService(session, DEFAULT_CONFIG)
        row = svc.upsert_lesson(
            memory_type="trade_lesson",
            title="Test lesson",
            summary="Summary",
            detailed_lesson="Detail",
            evidence={"foo": "bar"},
        )
        session.commit()
        detail = svc.get_lesson(f"lesson-{row.id}")
        assert detail and detail["title"] == "Test lesson"
        assert detail["evidence_human"]
        print("verify_memory_graph_node_click_payload: PASS")


if __name__ == "__main__":
    test()
