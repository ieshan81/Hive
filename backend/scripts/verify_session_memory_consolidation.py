from sqlmodel import select

from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config
from app.database import LessonNode
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.memory_evidence_consolidator_v2 import MemoryEvidenceConsolidatorV2


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="BTC/USD", utc_hour=14, n=8, direction=0.8)
    seed_backtest(session, symbol="BTC/USD", strategy_id="session_london_ny_overlap_continuation", trades=8)
    AutonomousAlphaFactoryService(session, cfg).bootstrap_scorecards_from_existing_evidence()
    out = MemoryEvidenceConsolidatorV2(session, cfg).consolidate_scorecards()
    rows = session.exec(select(LessonNode).where(LessonNode.memory_type.in_(["validated_session_candidate", "session_near_miss", "session_sample_insufficient"]))).all()
    assert out["raw_events_hidden"] is True, out
    assert rows, "expected consolidated session memory"
    assert all(r.memory_level == "consolidated_lesson" for r in rows), rows
    print("verify_session_memory_consolidation: PASS")


if __name__ == "__main__":
    main()
