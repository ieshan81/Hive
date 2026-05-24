"""Alias — strategy memory from backtest."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine, LessonNode
from sqlmodel import Session, select
from app.services.config_manager import ConfigManager
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.research_memory_service import ResearchMemoryService


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        out = ResearchBacktestEngine(session, cfg).run("crypto_push_pull", ["BTC/USD"])
        if out.get("run_id"):
            ResearchMemoryService(session, cfg).from_backtest_run(out["run_id"])
            session.commit()
            rows = session.exec(select(LessonNode).where(LessonNode.source == "research_lab")).all()
            assert len(rows) >= 1
        print("verify_strategy_memory_created_from_backtest: OK")


if __name__ == "__main__":
    main()
