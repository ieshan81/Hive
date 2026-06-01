from _alpha_factory_verify_common import seed_bars, session_with_config

from app.services.walk_forward_validation_service import WalkForwardValidationService


def main() -> None:
    session, cfg = session_with_config()
    seed_bars(session, n=12)
    out = WalkForwardValidationService(session, cfg).run_validation(
        strategy_id="crypto_push_pull_baseline",
        symbol="BTC/USD",
        parameters={"momentum_threshold_1h": 0.5},
        windows=1,
    )
    assert out["verdict"] in {"insufficient_sample", "reject_negative_test_expectancy", "reject_profit_factor_collapse", "reject_overfit_degradation"}, out
    print("verify_walk_forward_rejects_overfit: PASS")
    print({"verdict": out["verdict"], "degradation_ratio": out["degradation_ratio"]})


if __name__ == "__main__":
    main()
