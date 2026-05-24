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
        svc.upsert_lesson(
            memory_type="ui_truth_bug",
            title="Bug",
            summary="s",
            detailed_lesson="d",
            severity="CRITICAL",
            symbol="TESTBUG/USD",
            pattern_key="ui_truth_bug|TESTBUG",
        )
        session.commit()
        pen = svc.symbol_memory_penalty("TESTBUG/USD")
        assert pen == 0.0
        print("verify_bug_memory_does_not_influence_ranking: PASS")


if __name__ == "__main__":
    test()
