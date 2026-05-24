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
        svc.upsert_lesson(memory_type="trade_lesson", title="T", summary="s", detailed_lesson="d")
        svc.upsert_lesson(
            memory_type="reconciliation_bug",
            title="B",
            summary="s",
            detailed_lesson="d",
            severity="LOW",
        )
        session.commit()
        trading_graph = svc.build_graph(category="trading_memory", graph_default=False)
        ids = [n["id"] for n in trading_graph["nodes"] if n["type"] == "lesson"]
        assert all("lesson-" in i for i in ids)
        default_graph = svc.build_graph(graph_default=True)
        lesson_nodes = [n for n in default_graph["nodes"] if n["type"] == "lesson"]
        assert not any(n.get("memory_type") == "reconciliation_bug" for n in lesson_nodes)
        print("verify_memory_category_filter: PASS")


if __name__ == "__main__":
    test()
