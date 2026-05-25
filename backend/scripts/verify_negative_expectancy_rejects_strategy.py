"""Negative expectancy batch must reject strategy candidate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import StrategyCandidate, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.research_batch_analyzer import ResearchBatchAnalyzer
from app.services.research_test_fixtures import seed_hourly_bars


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        seed_hourly_bars(session, "DOGE/USD", count=200, trend=-0.25)
        sweep_results = [
            {
                "expectancy": -0.00937,
                "profit_factor": 0.345,
                "num_trades": 1440,
                "max_drawdown_pct": 100.0,
                "win_rate": 0.3,
            }
            for _ in range(6)
        ]
        analysis = ResearchBatchAnalyzer(session, cfg).analyze_sweep(
            "batch-test-uuid",
            "crypto_push_pull_momentum",
            sweep_results,
        )
        session.commit()
        cand = session.exec(
            select(StrategyCandidate).where(
                StrategyCandidate.strategy_id == "crypto_push_pull_momentum"
            )
        ).first()
        assert analysis.get("rejected"), "batch should be rejected"
        assert cand and cand.status == "rejected", "strategy candidate must be rejected"
        print("verify_negative_expectancy_rejects_strategy: OK")


if __name__ == "__main__":
    main()
