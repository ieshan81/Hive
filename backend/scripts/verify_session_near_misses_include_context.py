"""near-misses carry the full session context the cockpit needs.

Every near-miss row must include best_session, session_blocker, session_edge_after_cost_bps,
session_sample_size, and session_next_action.
"""

from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config  # noqa: E402

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService  # noqa: E402

REQUIRED = ("best_session", "session_blocker", "session_edge_after_cost_bps", "session_sample_size", "session_next_action")


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="LINK/USD", utc_hour=14, n=4, direction=0.7)
    seed_backtest(session, symbol="LINK/USD", strategy_id="session_london_ny_overlap_continuation", trades=3)
    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.bootstrap_scorecards_from_existing_evidence()
    session.commit()

    out = svc.get_near_misses(limit=10)
    near = out["near_misses"]
    assert near, "expected near-miss rows"
    for row in near:
        for key in REQUIRED:
            assert key in row, f"near-miss missing {key}: {row}"
        # session_next_action must be a non-empty hint.
        assert row["session_next_action"], row
    assert out["orders_authority"] == "none", out
    print(f"verify_session_near_misses_include_context: PASS ({len(near)} rows, all session-annotated)")


if __name__ == "__main__":
    main()
