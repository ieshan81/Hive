"""Soft candidate rejections rotate to the next candidate instead of freezing the cycle."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.autopilot_decision_classifier import classify_block_reason


def main() -> None:
    for reason in ("spread_check", "weak_edge", "data_stale", "liquidity_check"):
        cls = classify_block_reason(reason)
        assert cls["blocked_reason_class"] == "candidate_rejection_rotate", (reason, cls)
        assert cls["should_rotate"] is True and cls["should_freeze"] is False, (reason, cls)
    hard = classify_block_reason("KILL_SWITCH_ACTIVE")
    assert hard["should_freeze"] is True and hard["should_rotate"] is False, hard
    print("verify_candidate_rotation_not_freeze: PASS")
    print({"soft_rejections_rotate": True, "hard_safety_freezes": True})


if __name__ == "__main__":
    main()
