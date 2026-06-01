from _alpha_factory_verify_common import seed_backtest, seed_recent_losses, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_recent_losses(session)
    seed_backtest(session, trades=24, expectancy=0.008, profit_factor=1.45)
    AutonomousAlphaFactoryService(session, cfg).run_candidate_promotion_cycle(operator="verify")
    best = AutonomousAlphaFactoryService(session, cfg).get_best_candidates(limit=1)["candidates"][0]
    assert best["verdict"] == "paper_quarantined", best
    assert "recent_negative_expectancy_cooldown" in best["blocker_reasons"], best
    print("verify_autonomous_quarantine_after_recent_losses: PASS")
    print(best)


if __name__ == "__main__":
    main()
