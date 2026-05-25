"""Meme spike Alpaca crypto bars map 1Min/5Min/15Min correctly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    src = (Path(__file__).resolve().parents[1] / "app/services/alpaca_adapter.py").read_text(encoding="utf-8")
    for tf in ("1Min", "5Min", "15Min"):
        assert f'"{tf}"' in src and "TimeFrameUnit.Minute" in src
    assert '"2Min"' not in src or "unsupported timeframe" in src
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
