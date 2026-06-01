from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="LINK/USD", utc_hour=14, n=8, direction=0.8)
    seed_backtest(session, symbol="LINK/USD", strategy_id="session_london_ny_overlap_continuation", trades=8)
    AutonomousAlphaFactoryService(session, cfg).bootstrap_scorecards_from_existing_evidence()
    card = AutonomousAlphaFactoryService(session, cfg).get_scorecards(limit=1)["scorecards"][0]
    assert card["best_session"] == "london_new_york_overlap", card
    assert card["session_sample_size"] >= 5, card
    assert card["london_new_york_overlap_metrics"], card
    print("verify_alpha_scorecards_include_session_metrics: PASS")


if __name__ == "__main__":
    main()
