"""Live trading remains locked."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.broker_safety import live_lock_status
from app.services.engine_config import current_promotion_stage


def test_live_locked():
    assert current_promotion_stage(DEFAULT_CONFIG) == "PAPER"
    locks = live_lock_status(DEFAULT_CONFIG)
    assert locks["live_orders_enabled"] is False
    assert locks["promotion_stage"] == "PAPER"
    print("verify_live_locked: PASS")


if __name__ == "__main__":
    test_live_locked()
