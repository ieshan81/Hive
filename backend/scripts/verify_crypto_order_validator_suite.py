"""Alpaca crypto validator + broker error parsing."""

from __future__ import annotations

import sys

import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_round_down_qty():
    from app.services.alpaca_crypto_order_validator import _round_down

    assert _round_down(0.00013, 0.00001) == 0.00013
    assert _round_down(0.000135, 0.00001) == 0.00013


def test_classify_insufficient():
    from app.services.alpaca_broker_error import classify_reject_reason, parse_alpaca_exception

    parsed = parse_alpaca_exception(
        Exception(
            '{"code":40310000,"message":"insufficient balance for USDC (requested: 30, available: 0)"}'
        )
    )
    assert classify_reject_reason(parsed) == "BROKER_INSUFFICIENT_BALANCE"


def test_validate_blocks_both_qty_notional():
    from app.services.alpaca_crypto_order_validator import AlpacaCryptoOrderValidator

    class FakeSession:
        def exec(self, *a, **k):
            return type("R", (), {"first": lambda self=None: None})()

    class FakeAlpaca:
        configured = False

    v = AlpacaCryptoOrderValidator(FakeSession(), FakeAlpaca(), {}).validate_order(
        symbol="BTC/USD",
        side="buy",
        qty=0.001,
        notional=10.0,
        limit_price=50000.0,
        dry_run=True,
    )
    assert not v.valid
    assert any("both qty and notional" in r.lower() for r in v.validator_reasons)


if __name__ == "__main__":
    test_round_down_qty()
    test_classify_insufficient()
    test_validate_blocks_both_qty_notional()
    print("OK verify_crypto_order_validator_suite")
