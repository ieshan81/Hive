from _alpha_factory_verify_common import seed_bars, session_with_config

from app.services.parameter_sweep_service import ParameterSweepService


def main() -> None:
    session, cfg = session_with_config()
    seed_bars(session)
    out = ParameterSweepService(session, cfg).run_sweep(
        strategy_id="crypto_push_pull_baseline",
        symbols=["BTC/USD"],
        parameter_grid={"lookback_bars": [1, 3], "momentum_threshold_1h": [0.001, 0.02]},
        max_trials=4,
    )
    assert out["tested_combinations"] >= 2, out
    assert out["best_parameter_set"] is not None, out
    assert "rejected_sets" in out, out
    print("verify_parameter_sweep_outputs_best_and_rejected: PASS")
    print({"tested": out["tested_combinations"], "rejected": len(out["rejected_sets"])})


if __name__ == "__main__":
    main()
