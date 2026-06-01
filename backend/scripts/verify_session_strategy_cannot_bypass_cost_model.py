from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config
from app.database import ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="AVAX/USD", utc_hour=14, n=8, direction=0.8)
    run = seed_backtest(session, symbol="AVAX/USD", strategy_id="session_london_momentum", expectancy=0.0002, profit_factor=1.4, trades=8)
    run.cost_model_json = {"round_trip_cost_pct": 0.01, "spread_pct": 0.003, "slippage_pct": 0.004, "fee_pct": 0.0}
    run.metrics_json["cost_model"] = run.cost_model_json
    session.add(run)
    session.commit()
    AutonomousAlphaFactoryService(session, cfg).bootstrap_scorecards_from_existing_evidence()
    card = AutonomousAlphaFactoryService(session, cfg).get_scorecards(limit=1)["scorecards"][0]
    assert card["verdict"] != "paper_candidate", card
    assert card["edge_after_cost_bps"] <= 0, card
    print("verify_session_strategy_cannot_bypass_cost_model: PASS")


if __name__ == "__main__":
    main()
