import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_session_service import MarketSessionService


def main() -> None:
    svc = MarketSessionService()
    overlap = svc.classify_timestamp("2026-05-28T14:30:00Z", asset_class="crypto")
    weekend = svc.classify_timestamp("2026-05-30T02:00:00Z", asset_class="crypto")
    assert overlap["london_new_york_overlap"] is True, overlap
    assert weekend["crypto_weekend"] is True, weekend
    assert weekend["session_liquidity_score"] <= 0.5, weekend
    print("verify_crypto_session_classification: PASS")


if __name__ == "__main__":
    main()
