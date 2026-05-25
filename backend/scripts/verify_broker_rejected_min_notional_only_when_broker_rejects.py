"""BROKER_REJECTED_MIN_NOTIONAL is only for broker-side rejections, not internal preflight."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_execution_service import _map_broker_rejection_code


def main():
    assert _map_broker_rejection_code("order minimum notional $10") == "BROKER_REJECTED_MIN_NOTIONAL"
    assert _map_broker_rejection_code("insufficient qty") == "BROKER_REJECTED"
    assert _map_broker_rejection_code("") == "BROKER_REJECTED"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
