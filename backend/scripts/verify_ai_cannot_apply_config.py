"""AI proposals cannot apply locked keys."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.config_proposal_validator import validate_proposal
from app.services.default_config import DEFAULT_CONFIG


def test_locked_rejected():
    r = validate_proposal(
        DEFAULT_CONFIG,
        {"promotion": {"current_stage": "STANDARD_LIVE"}, "execution": {"live_orders_enabled": True}},
    )
    assert r["status"] == "rejected" or len(r["rejected"]) >= 1
    print("verify_ai_cannot_apply_config: PASS")


if __name__ == "__main__":
    test_locked_rejected()
