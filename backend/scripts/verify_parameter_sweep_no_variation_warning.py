"""Identical sweep metrics must create PARAMETER_SWEEP_NO_VARIATION memory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import LessonNode, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.research_batch_analyzer import ResearchBatchAnalyzer


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        identical = {
            "expectancy": -0.01,
            "profit_factor": 0.4,
            "num_trades": 100,
            "max_drawdown_pct": 80.0,
            "win_rate": 0.35,
        }
        sweep_results = [{**identical, "parameter_set_id": f"ps{i}"} for i in range(6)]
        ResearchBatchAnalyzer(session, cfg).analyze_sweep(
            "variation-test-batch",
            "crypto_push_pull_momentum",
            sweep_results,
        )
        session.commit()
        row = session.exec(
            select(LessonNode).where(
                LessonNode.memory_type == "parameter_sweep_no_variation"
            )
        ).first()
        assert row, "parameter_sweep_no_variation memory required"
        assert "identical" in (row.summary or "").lower() or "not be influencing" in (row.summary or "").lower()
        print("verify_parameter_sweep_no_variation_warning: OK")


if __name__ == "__main__":
    main()
