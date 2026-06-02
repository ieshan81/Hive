"""Broker-compatible sizing: a $5 cap is below the Alpaca crypto min notional ($10), so the
candidate is broker-INVALID and never submitted. Raising the cap above the broker minimum makes
it valid. The cap is never raised silently."""

import copy

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()

    # A $5 cap (below the $10 broker min) -> broker-INVALID.
    cfg5 = copy.deepcopy(cfg)
    cfg5["alpha_factory"]["paper_exploration"]["exploration_max_notional_usd"] = 5.0
    svc5 = PaperExplorationService(session, cfg5)
    bv = svc5.broker_validity(nm())
    assert bv["broker_valid"] is False, bv
    assert "broker_min_notional_exceeds_cap" in bv["broker_valid_blockers"], bv
    assert bv["min_required_notional_usd"] >= bv["broker_min_notional_usd"], bv  # includes buffer
    assert bv["exploration_cap_usd"] == 5.0, bv

    # The operator-requested $12 cap clears the broker min -> broker-VALID.
    cfg12 = copy.deepcopy(cfg)
    cfg12["alpha_factory"]["paper_exploration"]["exploration_max_notional_usd"] = 12.0
    svc12 = PaperExplorationService(session, cfg12)
    bv12 = svc12.broker_validity(nm())
    assert bv12["broker_valid"] is True, bv12
    assert bv12["broker_valid_blockers"] == [], bv12

    # The $5 service did not silently raise its own cap.
    assert svc5.max_notional_usd == 5.0, svc5.max_notional_usd
    print(f"verify_paper_exploration_broker_valid_sizing: PASS ($5<min {bv['min_required_notional_usd']} invalid; $15 valid)")


if __name__ == "__main__":
    main()
