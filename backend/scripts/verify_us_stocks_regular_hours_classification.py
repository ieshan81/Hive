import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_session_service import MarketSessionService


def main() -> None:
    svc = MarketSessionService()
    regular = svc.classify_timestamp("2026-05-28T14:00:00Z", asset_class="stock")
    pre = svc.classify_timestamp("2026-05-28T12:00:00Z", asset_class="stock")
    after = svc.classify_timestamp("2026-05-28T21:00:00Z", asset_class="stock")
    assert regular["session_name"] == "us_regular_market_hours", regular
    assert pre["session_name"] == "us_premarket", pre
    assert after["session_name"] == "us_afterhours", after
    print("verify_us_stocks_regular_hours_classification: PASS")


if __name__ == "__main__":
    main()
