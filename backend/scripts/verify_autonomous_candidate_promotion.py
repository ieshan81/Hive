from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_backtest(session, trades=24, expectancy=0.008, profit_factor=1.45)
    out = AutonomousAlphaFactoryService(session, cfg).run_candidate_promotion_cycle(operator="verify")
    best = AutonomousAlphaFactoryService(session, cfg).get_best_candidates(limit=1)["candidates"][0]
    assert out["candidates_promoted"] >= 1, out
    assert best["verdict"] == "paper_candidate", best
    print("verify_autonomous_candidate_promotion: PASS")
    print(best)


if __name__ == "__main__":
    main()
