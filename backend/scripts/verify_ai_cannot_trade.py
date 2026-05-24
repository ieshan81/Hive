"""AI cannot enable paper or live trading."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.config_proposal_validator import validate_proposal
from app.services.default_config import DEFAULT_CONFIG


def test_ai_cannot_enable_paper():
    r = validate_proposal(DEFAULT_CONFIG, {"execution": {"paper_orders_enabled": True}})
    assert any(x["key"] == "execution.paper_orders_enabled" for x in r["rejected"])
    print("verify_ai_cannot_trade: PASS")


if __name__ == "__main__":
    test_ai_cannot_enable_paper()
