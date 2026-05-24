"""Unsupported/watch meme cannot use order path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.symbol_tier_service import EngineBoundaryBlocked, SymbolTierService


def test_pepe_blocked():
    svc = SymbolTierService(DEFAULT_CONFIG)
    info = svc.classify("PEPE/USD")
    assert info.tier == "TIER_WATCH"
    assert not info.order_path_allowed
    try:
        svc.assert_order_path("PEPE/USD")
        raise AssertionError("expected ENGINE_BOUNDARY_BLOCKED")
    except EngineBoundaryBlocked:
        pass
    print("verify_meme_watch_only: PASS")


if __name__ == "__main__":
    test_pepe_blocked()
