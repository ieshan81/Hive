"""Verify a 0-bar / low-bar stock feed is reported as a clear blocker, never as "ready".

Exercises the readiness classifier directly so a feed that returns no bars surfaces an exact
blocker code (STOCK_MARKET_CLOSED / STOCK_SUBSCRIPTION_LIMIT / STOCK_DATA_UNAVAILABLE /
INSUFFICIENT_STOCK_BARS) instead of silently being treated as scanned.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Module-level imports here are DB-free (alpaca_adapter is imported lazily inside functions).
from app.services.stock_data_readiness_service import BLOCKER_CODES, _classify  # noqa: E402


def main() -> None:
    cases = {
        # (bars, market_open, err, min_bars) -> expected code
        (0, True, None, 2): "STOCK_DATA_UNAVAILABLE",
        (0, False, None, 2): "STOCK_MARKET_CLOSED",
        (1, True, None, 2): "INSUFFICIENT_STOCK_BARS",
        (0, True, "subscription is not permitted", 2): "STOCK_SUBSCRIPTION_LIMIT",
        (0, True, "sip feed not authorized", 2): "STOCK_FEED_UNSUPPORTED",
        (50, True, None, 2): None,  # ready
    }
    for args, expected in cases.items():
        got = _classify(*args)
        assert got == expected, f"_classify{args} -> {got}, expected {expected}"
        if got is not None:
            assert got in BLOCKER_CODES, f"blocker {got} not in BLOCKER_CODES"

    # A symbol with zero bars must NEVER classify as ready (None).
    assert _classify(0, True, None, 2) is not None, "0 bars during open market wrongly marked ready"
    assert _classify(0, False, None, 2) is not None, "0 bars (closed) wrongly marked ready"
    print("verify_stock_scanner_reports_zero_bars_truthfully: PASS (0/low bars -> explicit blocker, never ready)")


if __name__ == "__main__":
    main()
