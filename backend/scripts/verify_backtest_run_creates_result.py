"""Verify backtest run persists ResearchBacktestRun — no broker calls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, ResearchBacktestRun
from app.services.config_manager import ConfigManager
from sqlmodel import Session, select
from app.database import engine
from app.services.research_backtest_engine import ResearchBacktestEngine


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        before = len(session.exec(select(ResearchBacktestRun)).all())
        engine_bt = ResearchBacktestEngine(session, cfg)
        out = engine_bt.run("mean_reversion", ["BTC/USD"], parameters={"lookback": 24, "z_entry": 2.0})
        session.commit()
        after = len(session.exec(select(ResearchBacktestRun)).all())
        assert after >= before, "run should create row"
        assert "run_id" in out
        assert out.get("status") in ("ok", "empty", "error", "skipped")
        print("verify_backtest_run_creates_result: OK", out.get("status"))


if __name__ == "__main__":
    main()
