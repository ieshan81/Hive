"""Verify stock bars are requested up to (now - delay), not the most-recent minutes.

Basic plans cannot query the latest ~15 min of stock data; requesting end=now returned 0 bars.
Asserts the delay window is configured (>0 by default) and applied in the stock bar request.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    src = (BACKEND / "app/services/alpaca_adapter.py").read_text(encoding="utf-8", errors="ignore")
    cfg = (BACKEND / "app/config.py").read_text(encoding="utf-8", errors="ignore")

    assert "alpaca_stock_data_delay_minutes: int = 16" in cfg, "default stock data delay is not 16 minutes"

    # The stock branch must subtract the delay window from now (not request end=now).
    assert "datetime.utcnow() - timedelta(minutes=stock_data_delay_minutes())" in src, \
        "get_bars does not hold the end-time back by the delay window"
    # The old bug: a bare `end = datetime.utcnow()` in the stock path must be gone.
    assert "end = datetime.utcnow()\n            start = end - timedelta(days=limit * 2)" not in src, \
        "stock get_bars still requests end=now (too-recent)"

    from app.services.alpaca_adapter import stock_data_delay_minutes

    delay = stock_data_delay_minutes()
    assert isinstance(delay, int) and delay >= 1, f"delay window must be >=1 min by default, got {delay}"
    print(f"verify_stock_bars_use_delay_window_when_basic_plan: PASS (delay_minutes={delay})")


if __name__ == "__main__":
    main()
