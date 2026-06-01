from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="DOGE/USD", utc_hour=23, n=8, direction=0.5)
    seed_backtest(session, symbol="DOGE/USD", strategy_id="session_liquidity_sweep_reversal", trades=8)
    AutonomousAlphaFactoryService(session, cfg).bootstrap_scorecards_from_existing_evidence()
    card = AutonomousAlphaFactoryService(session, cfg).get_scorecards(limit=1)["scorecards"][0]
    assert card["best_session"] == "low_liquidity_window", card
    assert card["low_liquidity_session_warning"], card
    print("verify_low_liquidity_session_penalty: PASS")


if __name__ == "__main__":
    main()
