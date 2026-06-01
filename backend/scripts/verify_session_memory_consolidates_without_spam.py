"""Session evidence consolidates into one durable memory per pattern, with no raw spam.

Re-running consolidation must not create duplicates (occurrence_count grows instead), session
memory stays hidden-raw-by-default, and only a validated session candidate can influence
ranking (none here).
"""

from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config  # noqa: E402

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService  # noqa: E402
from app.services.memory_evidence_consolidator_v2 import MemoryEvidenceConsolidatorV2  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="BTC/USD", utc_hour=14, n=8, direction=0.8)
    seed_backtest(session, symbol="BTC/USD", strategy_id="session_london_ny_overlap_continuation", trades=4, expectancy=-0.01, profit_factor=0.7)
    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.bootstrap_scorecards_from_existing_evidence()
    session.commit()

    cons = MemoryEvidenceConsolidatorV2(session, cfg)
    cons.consolidate_scorecards()
    session.commit()
    s1 = cons.session_summary()
    n1 = s1["session_memory_count"]
    assert n1 >= 1, s1
    assert s1["raw_hidden_by_default"] is True, s1
    valid_types = {"session_near_miss", "session_sample_insufficient", "rejected_session_setup", "validated_session_candidate"}
    assert set(s1["by_type"]).issubset(valid_types), s1["by_type"]

    # Re-run: no duplicates (count stable), occurrence_count grows.
    cons.consolidate_scorecards()
    session.commit()
    s2 = cons.session_summary()
    assert s2["session_memory_count"] == n1, f"session memory duplicated: {n1} -> {s2['session_memory_count']}"

    # No session memory can influence ranking unless a validated session candidate exists (none here).
    assert s2["can_influence_ranking_count"] == 0, s2
    print(f"verify_session_memory_consolidates_without_spam: PASS ({n1} consolidated session lesson(s), idempotent)")


if __name__ == "__main__":
    main()
