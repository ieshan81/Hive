import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_session_service import MarketSessionService


def main() -> None:
    svc = MarketSessionService()
    assert svc.classify_timestamp("2026-05-28T14:00:00Z")["session_name"] == "london_new_york_overlap"
    assert svc.classify_timestamp("2026-05-28T09:00:00Z")["session_name"] == "london_session"
    assert svc.classify_timestamp("2026-05-28T02:00:00Z")["session_name"] == "asia_session"
    assert svc.classify_timestamp("2026-05-28T23:00:00Z")["avoid_reason"] == "low_liquidity_window"
    print("verify_market_session_classifier: PASS")


if __name__ == "__main__":
    main()
