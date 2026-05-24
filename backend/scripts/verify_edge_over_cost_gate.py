"""Verify edge-over-cost gate blocks weak edge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cost_edge_gate import evaluate_cost_edge
from app.services.default_config import DEFAULT_CONFIG


def test_weak_edge_blocked():
    r = evaluate_cost_edge(
        DEFAULT_CONFIG,
        expected_move_pct=0.001,
        spread_pct=0.002,
        tier="TIER_ALT",
    )
    assert not r.passed
    assert r.block_reason_code == "EDGE_BELOW_COST"
    assert "round_trip_cost_pct" in r.evidence
    print("verify_edge_over_cost_gate: PASS")


if __name__ == "__main__":
    test_weak_edge_blocked()
