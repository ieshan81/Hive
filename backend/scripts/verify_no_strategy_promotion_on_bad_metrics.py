"""Leaderboard must block promotion when metrics fail gates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import ParameterSetResult, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.research_lab_service import ResearchLabService


def main():
    init_db()
    with Session(engine) as session:
        session.add(
            ParameterSetResult(
                parameter_set_id="bad-metrics-ps1",
                run_id="run-bad",
                strategy_id="crypto_push_pull_momentum",
                parameters_json={"edge_multiplier": 1.0},
                num_trades=1440,
                win_rate=0.3,
                expectancy=-0.009,
                profit_factor=0.35,
                max_drawdown_pct=99.0,
                status="completed",
            )
        )
        session.commit()
        lb = ResearchLabService(session).leaderboard()
        bad = [r for r in lb if r["parameter_set_id"] == "bad-metrics-ps1"]
        assert bad, "bad row should appear on leaderboard"
        assert bad[0]["promote_allowed"] is False
        assert bad[0]["recommended_action"] == "do_not_promote"
        assert bad[0]["rejection_reason"]
        print("verify_no_strategy_promotion_on_bad_metrics: OK")


if __name__ == "__main__":
    main()
