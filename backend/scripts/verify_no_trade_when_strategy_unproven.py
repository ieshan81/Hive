from _alpha_factory_verify_common import seed_scorecard, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_scorecard(session, verdict="unproven")
    gate = AutonomousAlphaFactoryService(session, cfg).can_trade_paper("BTC/USD", strategy_id="crypto_push_pull_baseline")
    assert gate["allowed"] is False, gate
    assert "unproven" in gate["reason"], gate
    print("verify_no_trade_when_strategy_unproven: PASS")
    print(gate)


if __name__ == "__main__":
    main()
