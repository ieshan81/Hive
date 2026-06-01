from _alpha_factory_verify_common import seed_backtest, seed_recent_losses, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_recent_losses(session)
    seed_backtest(session)
    AutonomousAlphaFactoryService(session, cfg).run_candidate_promotion_cycle(operator="verify")
    gate = AutonomousAlphaFactoryService(session, cfg).can_trade_paper("BTC/USD", strategy_id="crypto_push_pull_baseline")
    assert gate["allowed"] is False, gate
    assert "cooldown" in gate["reason"] or "paper_quarantined" in gate["reason"], gate
    print("verify_recent_loss_quarantine: PASS")
    print(gate)


if __name__ == "__main__":
    main()
