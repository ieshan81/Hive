"""Verify paper exploration cannot turn bearish structure into a long buy."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.push_pull_scoring_service import _long_structure_decision


def cfg() -> dict:
    out = copy.deepcopy(DEFAULT_CONFIG)
    out["promotion"] = {"current_stage": "PAPER"}
    out["exploration"] = {"enabled": True, "dynamic_formula_mode": True}
    return out


def main() -> None:
    bearish = _long_structure_decision(
        cfg(),
        {
            "pattern": "none",
            "direction": "long",
            "confidence": 0.0,
        },
        {
            "last_candle_green": False,
            "last_candle_return": -0.004,
            "momentum_1h": -0.003,
            "three_bar_return": -0.002,
        },
    )
    assert bearish["long_structure_ok"] is False
    assert bearish["reason"] == "BEARISH_STRUCTURE_NO_LONG_ENTRY"

    bullish_reversal = _long_structure_decision(
        cfg(),
        {
            "pattern": "failed_breakout",
            "direction": "long",
            "confidence": 0.72,
        },
        {
            "last_candle_green": True,
            "last_candle_return": 0.001,
            "momentum_1h": -0.001,
            "three_bar_return": -0.0004,
        },
    )
    assert bullish_reversal["long_structure_ok"] is True

    print("verify_long_structure_blocks_bearish_paper_buy: PASS")


if __name__ == "__main__":
    main()
