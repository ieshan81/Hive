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
            memory_type="trade_lesson",
            title="Archive test",
            summary="s",
            detailed_lesson="d",
        )
        session.commit()
        graph_before = svc.build_graph(graph_default=True)
        assert any(n["id"] == f"lesson-{row.id}" for n in graph_before["nodes"])
        svc.archive(row.id, reason="test")
        session.commit()
        graph_after = svc.build_graph(graph_default=True)
        assert not any(n["id"] == f"lesson-{row.id}" for n in graph_after["nodes"])
        svc.soft_delete(row.id)
        session.commit()
        assert svc.session.get(type(row), row.id).status == "deleted"
        svc.restore(row.id)
        session.commit()
        assert svc.session.get(type(row), row.id).status == "active"
        print("verify_memory_archive_delete: PASS")


if __name__ == "__main__":
    test()
