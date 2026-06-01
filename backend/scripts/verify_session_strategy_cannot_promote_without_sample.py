from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="UNI/USD", utc_hour=14, n=2, direction=1.0)
    seed_backtest(session, symbol="UNI/USD", strategy_id="session_london_ny_overlap_continuation", trades=0)
    AutonomousAlphaFactoryService(session, cfg).bootstrap_scorecards_from_existing_evidence()
    card = AutonomousAlphaFactoryService(session, cfg).get_scorecards(limit=1)["scorecards"][0]
    assert card["verdict"] != "paper_candidate", card
    assert card["session_blocker"] == "session_sample_insufficient", card
    print("verify_session_strategy_cannot_promote_without_sample: PASS")


if __name__ == "__main__":
    main()
