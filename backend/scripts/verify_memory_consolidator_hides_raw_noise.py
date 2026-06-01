from _alpha_factory_verify_common import seed_backtest, session_with_config

from sqlmodel import select

from app.database import LessonNode
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    session.add(
        LessonNode(
            memory_type="raw_tick_noise",
            title="No order",
            summary="No order",
            detailed_lesson="Raw no-order spam.",
            memory_level="raw_experience",
            visible_in_graph=False,
            can_influence_ranking=False,
        )
    )
    seed_backtest(session)
    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.run_candidate_promotion_cycle(operator="verify")
    svc.run_memory_consolidation_cycle(operator="verify")
    meaningful = session.exec(
        select(LessonNode).where(LessonNode.source == "alpha_factory", LessonNode.memory_level == "consolidated_lesson")
    ).all()
    raw = session.exec(select(LessonNode).where(LessonNode.memory_type == "raw_tick_noise")).first()
    assert meaningful, "expected alpha consolidated lesson"
    assert raw and raw.visible_in_graph is False and raw.can_influence_ranking is False, raw
    print("verify_memory_consolidator_hides_raw_noise: PASS")
    print({"meaningful": len(meaningful), "raw_visible": raw.visible_in_graph})


if __name__ == "__main__":
    main()
