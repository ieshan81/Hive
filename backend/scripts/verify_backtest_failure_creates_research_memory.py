"""Backtest failures must create research lesson memories."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import LessonNode, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.memory_categories import RESEARCH_MEMORY_TYPES
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.research_memory_service import ResearchMemoryService
from app.services.research_test_fixtures import seed_hourly_bars


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        seed_hourly_bars(session, "BTC/USD", count=180, trend=-0.3)
        out = ResearchBacktestEngine(session, cfg).run(
            "crypto_push_pull_momentum",
            ["BTC/USD"],
            parameters={"momentum_threshold_1h": 0.001, "edge_multiplier": 1.0, "max_hold_hours": 4},
        )
        assert out.get("run_id"), "expected run_id"
        created = ResearchMemoryService(session, cfg).from_backtest_run(out["run_id"])
        session.commit()
        assert created >= 1, f"expected >=1 memories, got {created}"
        rows = session.exec(
            select(LessonNode).where(LessonNode.memory_type.in_(list(RESEARCH_MEMORY_TYPES)))
        ).all()
        assert rows, "research memory types should exist"
        print("verify_backtest_failure_creates_research_memory: OK", created, "memories")


if __name__ == "__main__":
    main()
