"""Verify trading cage architecture modules load and core invariants hold."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_paper_guard_blocks_live():
    from app.trading_cage.paper_guard import PaperGuardViolation, assert_paper_only

    cfg = {"execution": {"live_orders_enabled": True}, "live_trading_enabled": False}
    try:
        assert_paper_only(cfg)
        raise AssertionError("expected PaperGuardViolation")
    except PaperGuardViolation as exc:
        assert exc.code == "LIVE_ORDERS_ENABLED"


def test_cost_model_negative_edge():
    from app.trading_cage.cost_model import evaluate_edge_after_cost_bps

    cfg = {"cost": {"taker_fee_pct": 0.25}, "push_pull": {"min_edge_after_cost_bps": 50.0}}
    r = evaluate_edge_after_cost_bps(cfg, expected_move_bps=30.0, spread_bps=10.0)
    assert not r.passed
    assert r.block_reason_code == "NEGATIVE_EDGE_AFTER_COST"


def test_gemini_proposal_forbidden():
    from app.trading_cage.gemini_proposal_gate import validate_gemini_proposal

    v = validate_gemini_proposal({"type": "config_change_proposal", "target": "live_trading_enabled", "value": True})
    assert not v["valid"]
    assert v["gemini_can_trade"] is False


def test_micro_cap_allocator_min():
    from app.trading_cage.micro_cap_allocator import MicroCapAllocator

    class FakePosition:
        def __init__(self, qty):
            self.qty = qty

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def exec(self, *a, **k):
            return FakeResult()

    cfg = {
        "portfolio": {"reserve_cash_pct": 60.0, "max_concurrent_positions": 2},
        "risk": {"max_exposure_per_symbol_pct": 20.0},
        "execution": {"alpaca_crypto_min_notional_usd": 10.0, "alpaca_min_notional_buffer_usd": 0.5},
        "allocator": {"paper_trade_notional_min_usd": 20.0, "paper_trade_notional_max_usd": 40.0},
    }
    d = MicroCapAllocator(FakeSession(), cfg).compute_entry_notional(
        equity=200, buying_power=200, symbol="BTC/USD", open_positions=[]
    )
    assert d.allowed
    assert d.notional_usd >= 20.0

    unlimited_cfg = {
        **cfg,
        "portfolio": {"reserve_cash_pct": 5.0, "max_concurrent_positions": 0},
        "risk": {"max_exposure_per_symbol_pct": 100.0},
    }
    unlimited = MicroCapAllocator(FakeSession(), unlimited_cfg).compute_entry_notional(
        equity=200,
        buying_power=200,
        symbol="UNI/USD",
        open_positions=[FakePosition(1), FakePosition(2)],
    )
    assert unlimited.allowed, unlimited
    assert unlimited.evidence["max_open_positions_policy"] == "unlimited"

    capped_cfg = {
        **cfg,
        "portfolio": {"reserve_cash_pct": 5.0, "max_concurrent_positions": 1},
        "risk": {"max_exposure_per_symbol_pct": 100.0},
    }
    capped = MicroCapAllocator(FakeSession(), capped_cfg).compute_entry_notional(
        equity=200,
        buying_power=200,
        symbol="UNI/USD",
        open_positions=[FakePosition(1)],
    )
    assert not capped.allowed
    assert capped.reason_code == "ALLOCATOR_MAX_POSITIONS"


if __name__ == "__main__":
    test_paper_guard_blocks_live()
    test_cost_model_negative_edge()
    test_gemini_proposal_forbidden()
    test_micro_cap_allocator_min()
    print("OK verify_trading_cage_architecture")
