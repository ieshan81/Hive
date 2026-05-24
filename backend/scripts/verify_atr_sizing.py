"""Verify ATR sizing and missing ATR block."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.atr_sizing import compute_atr_from_bars, evaluate_atr_sizing
from app.services.default_config import DEFAULT_CONFIG


def test_atr_missing():
    r = evaluate_atr_sizing(
        DEFAULT_CONFIG,
        equity=200,
        entry_price=100,
        side="buy",
        tier="TIER_ALT",
        bars=[],
        spread_pct=0.001,
        crypto_bucket_remaining=60,
        buying_power=200,
        reserve_cash_pct=60,
    )
    assert not r.passed
    assert r.block_reason_code == "ATR_DATA_MISSING"
    print("verify_atr_sizing (missing): PASS")


def test_atr_compute():
    bars = []
    price = 100.0
    for _ in range(20):
        bars.append({"open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1})
        price += 0.1
    atr = compute_atr_from_bars(bars, 14)
    assert atr is not None and atr > 0
    print("verify_atr_sizing (compute): PASS")


if __name__ == "__main__":
    test_atr_missing()
    test_atr_compute()
