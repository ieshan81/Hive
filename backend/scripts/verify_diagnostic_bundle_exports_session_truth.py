"""The diagnostic bundle exports session truth as first-class files.

Must include alpha_session_summary.json, alpha_session_scorecards.json,
alpha_session_near_misses.json, and alpha_session_memory.json.
"""

from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config  # noqa: E402

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService  # noqa: E402
from app.services.diagnostic_export import export_diagnostic_bundle  # noqa: E402

REQUIRED_KEYS = (
    "alpha_session_summary.json",
    "alpha_session_scorecards.json",
    "alpha_session_near_misses.json",
    "alpha_session_memory.json",
)


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="BTC/USD", utc_hour=14, n=8, direction=0.8)
    seed_backtest(session, symbol="BTC/USD", strategy_id="session_london_ny_overlap_continuation", trades=8)
    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.bootstrap_scorecards_from_existing_evidence()
    session.commit()

    bundle = export_diagnostic_bundle(session)
    for key in REQUIRED_KEYS:
        assert key in bundle, f"diagnostic bundle missing {key}"

    summary = bundle["alpha_session_summary.json"]
    assert isinstance(summary, dict), summary
    assert ("session_scorecard_count" in summary) or ("session_metrics_available_count" in summary), summary

    scards = bundle["alpha_session_scorecards.json"]
    assert isinstance(scards, dict) and "session_scorecards" in scards, scards

    near = bundle["alpha_session_near_misses.json"]
    assert isinstance(near, dict) and "session_near_misses" in near, near

    mem = bundle["alpha_session_memory.json"]
    assert isinstance(mem, dict) and "session_memory_count" in mem, mem
    print("verify_diagnostic_bundle_exports_session_truth: PASS")


if __name__ == "__main__":
    main()
