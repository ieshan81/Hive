from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    bt = seed_backtest(session)
    AutonomousAlphaFactoryService(session, cfg).run_candidate_promotion_cycle(operator="verify")
    card = AutonomousAlphaFactoryService(session, cfg).get_scorecards(limit=1)["scorecards"][0]
    assert card["last_backtest_run_id"] == bt.run_id, card
    assert bt.run_id in card["evidence_ids"], card
    print("verify_scorecards_created_from_backtests: PASS")
    print(card)


if __name__ == "__main__":
    main()
