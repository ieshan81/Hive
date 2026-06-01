from _alpha_factory_verify_common import seed_backtest, session_with_config

from sqlmodel import select

from app.database import LessonNode
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    svc = AutonomousAlphaFactoryService(session, cfg)
    seed_backtest(session)
    svc.run_candidate_promotion_cycle(operator="verify")
    out = svc.run_memory_consolidation_cycle(operator="verify")
    lessons = session.exec(select(LessonNode).where(LessonNode.source == "alpha_factory")).all()
    assert out["memory_written_count"] >= 1, out
    assert lessons and lessons[0].memory_level == "consolidated_lesson", lessons
    print("verify_autonomous_cycle_writes_memory: PASS")
    print({"memory_written_count": out["memory_written_count"], "lesson_type": lessons[0].memory_type})


if __name__ == "__main__":
    main()
