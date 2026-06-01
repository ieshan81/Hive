from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="LINK/USD", utc_hour=14, n=3, direction=0.7)
    seed_backtest(session, symbol="LINK/USD", strategy_id="session_london_ny_overlap_continuation", trades=3)
    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.bootstrap_scorecards_from_existing_evidence()
    near = svc.get_near_misses(limit=5)["near_misses"]
    assert near, "expected near-miss rows"
    row = near[0]
    assert "best_session" in row and "session_next_action" in row, row
    assert row["session_sample_size"] >= 0, row
    print("verify_near_misses_include_session_context: PASS")


if __name__ == "__main__":
    main()
