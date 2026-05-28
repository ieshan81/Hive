"""Verify dynamic stop, target, trail, and invalidation levels."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.dynamic_exit_levels_service import compute_dynamic_exit_levels, exit_trigger_for_long


def sample_bars(start: float = 100.0) -> list[dict]:
    bars = []
    price = start
    for i in range(24):
        close = price + (0.2 if i % 3 else 0.45)
        bars.append(
            {
                "open": price,
                "high": close + 0.55,
                "low": price - 0.45,
                "close": close,
                "volume": 1000 + i * 10,
            }
        )
        price = close
    return bars


def verify_buy_levels():
    levels = compute_dynamic_exit_levels(
        DEFAULT_CONFIG,
        symbol="BTC/USD",
        side="buy",
        entry_price=100.0,
        current_price=100.0,
        bars=sample_bars(),
        quote={"bid": 99.95, "ask": 100.05},
        signal_meta={"push_score": 0.8, "trade_quality_score": 0.78, "edge_after_cost_bps": 120},
        tier="TIER_MAJOR",
    )
    assert levels.stop_loss < levels.entry_price < levels.take_profit
    assert levels.trailing_stop <= levels.entry_price
    assert levels.risk_reward >= 1.3
    assert levels.bars["stop_loss"]["price"] == levels.stop_loss
    assert levels.bars["take_profit"]["price"] == levels.take_profit
    print("verify_dynamic_exit_levels (buy): PASS")


def verify_sell_levels():
    levels = compute_dynamic_exit_levels(
        DEFAULT_CONFIG,
        symbol="TEST",
        side="sell",
        entry_price=50.0,
        current_price=50.0,
        bars=sample_bars(50.0),
        quote={"spread_pct": 0.001},
        signal_meta={"push_score": 0.65, "trade_quality_score": 0.7, "edge_after_cost_bps": 80},
        tier="TIER_ALT",
    )
    assert levels.take_profit < levels.entry_price < levels.stop_loss
    assert levels.risk_reward >= 1.3
    print("verify_dynamic_exit_levels (sell): PASS")


def verify_exit_trigger():
    levels = compute_dynamic_exit_levels(
        DEFAULT_CONFIG,
        symbol="ETH/USD",
        side="buy",
        entry_price=100.0,
        current_price=100.0,
        bars=sample_bars(),
        quote={"spread_pct": 0.001},
        signal_meta={"push_score": 0.75, "trade_quality_score": 0.8, "edge_after_cost_bps": 150},
        tier="TIER_MAJOR",
    ).to_dict()
    hit_target = exit_trigger_for_long(current_price=levels["take_profit"] + 0.01, levels=levels)
    hit_stop = exit_trigger_for_long(current_price=levels["stop_loss"] - 0.01, levels=levels)
    assert hit_target and hit_target["reason"] == "dynamic_take_profit_hit"
    assert hit_stop and hit_stop["reason"] in {
        "dynamic_stop_loss_hit",
        "dynamic_trailing_stop_hit",
        "dynamic_invalidation_hit",
    }
    print("verify_dynamic_exit_levels (triggers): PASS")


if __name__ == "__main__":
    verify_buy_levels()
    verify_sell_levels()
    verify_exit_trigger()
