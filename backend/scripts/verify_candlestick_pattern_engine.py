"""Verify V2 candlestick pattern detection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.candlestick_pattern_engine import detect_candlestick_patterns


def base_context() -> list[dict]:
    return [
        {"open": 98, "high": 100, "low": 97, "close": 99, "volume": 1000},
        {"open": 99, "high": 101, "low": 98, "close": 100, "volume": 1040},
        {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1080},
    ]


def names(rows: list[dict]) -> set[str]:
    return {str(r.get("pattern")) for r in detect_candlestick_patterns(rows)}


def verify_harami() -> None:
    bullish = base_context() + [
        {"open": 106, "high": 107, "low": 99, "close": 100, "volume": 1200},
        {"open": 101, "high": 102.5, "low": 100.5, "close": 102, "volume": 900},
        {"open": 102, "high": 106, "low": 101.5, "close": 105.5, "volume": 1300},
    ]
    bearish = base_context() + [
        {"open": 100, "high": 107, "low": 99, "close": 106, "volume": 1200},
        {"open": 105, "high": 105.5, "low": 103.5, "close": 104, "volume": 900},
        {"open": 104, "high": 104.5, "low": 99.5, "close": 99.8, "volume": 1300},
    ]
    assert "bullish_harami" in names(bullish)
    assert "bearish_harami" in names(bearish)


def verify_failed_breakout() -> None:
    rows = base_context() + [
        {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 1200},
        {"open": 102, "high": 103.5, "low": 101, "close": 102.5, "volume": 1100},
        {"open": 102.8, "high": 105, "low": 101.8, "close": 103.2, "volume": 1600},
    ]
    assert "failed_breakout" in names(rows)


def verify_pin_and_engulfing() -> None:
    pin = base_context() + [
        {"open": 100, "high": 101, "low": 99, "close": 100.2, "volume": 1000},
        {"open": 100.2, "high": 100.5, "low": 96, "close": 100.1, "volume": 1500},
    ]
    engulfing = base_context() + [
        {"open": 103, "high": 104, "low": 101, "close": 102, "volume": 1000},
        {"open": 101.5, "high": 106, "low": 101, "close": 105, "volume": 1500},
    ]
    assert "pin_bar" in names(pin)
    assert "engulfing" in names(engulfing)


if __name__ == "__main__":
    verify_harami()
    verify_failed_breakout()
    verify_pin_and_engulfing()
    print("verify_candlestick_pattern_engine: PASS")
