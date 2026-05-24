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
        row = svc.upsert_lesson(
            memory_type="operator_note",
            title="Note",
            summary="s",
            detailed_lesson="d",
            source="human_approved",
        )
        session.commit()
        svc.approve(row.id)
        svc.archive(row.id, hide_from_graph=True)
        session.commit()
        assert row.visible_in_graph is False
        detail = svc.get_lesson(f"lesson-{row.id}")
        assert detail and detail.get("drawer_title")
        print("verify_lesson_drawer_actions: PASS")


if __name__ == "__main__":
    test()
