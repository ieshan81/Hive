"""Candidate selection prefers the highest-score BROKER-VALID candidate. A higher-scored
candidate that is broker-invalid (below min notional under cap) is skipped with a reason, and the
next valid one is selected. If none are broker-valid, submit returns a clean structured block
(no_broker_valid_exploration_candidate) — never an invalid broker submit, never KILL_SWITCH_ACTIVE."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402


def _row(symbol, score, broker_valid):
    return {
        "id": 1, "symbol": symbol, "strategy_id": "s", "strategy_family": "f", "best_session": "new_york_session",
        "exploration_eligible": True, "exploration_score": score,
        "broker_valid_for_exploration": broker_valid,
        "broker_valid_blockers": [] if broker_valid else ["broker_min_notional_exceeds_cap"],
        "min_required_notional_usd": 10.2,
    }


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    # Top score invalid, second valid -> select the valid one, record the skip.
    svc.near_misses = lambda *, limit=50: [_row("BTC/USD", 0.80, False), _row("XRP/USD", 0.60, True)]  # type: ignore
    sel = svc.select_candidate_detailed()
    assert sel["selected"] and sel["selected"]["symbol"] == "XRP/USD", sel
    assert any(s["symbol"] == "BTC/USD" for s in sel["skipped_broker_invalid"]), sel
    assert sel["skipped_broker_invalid"][0]["skipped_reason"] == "broker_min_notional_exceeds_cap", sel

    # None broker-valid -> no candidate + submit returns clean structured block.
    svc.near_misses = lambda *, limit=50: [_row("BTC/USD", 0.80, False), _row("ETH/USD", 0.70, False)]  # type: ignore
    sel2 = svc.select_candidate_detailed()
    assert sel2["selected"] is None and sel2["no_broker_valid_candidate"] is True, sel2

    out = svc.submit_exploration_order(dry_run=False)
    assert out["submitted"] is False and out["orders_created"] == 0, out
    assert out["block_reason"] == "no_broker_valid_exploration_candidate", out
    assert out["status"] == "blocked" and "skipped_broker_invalid" in out, out
    assert "KILL_SWITCH" not in str(out["block_reason"]), out
    print("verify_paper_exploration_selects_broker_valid_candidate: PASS")


if __name__ == "__main__":
    main()
