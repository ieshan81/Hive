"""Paper disabled -> approved_no_order with PAPER_EXECUTION_DISABLED."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.execution_policy import ExecutionPolicy
from app.services.portfolio_gate import ApprovedCandidate
from app.services.symbol_tier_service import SymbolTierService


class FakeSession:
    def get(self, *a, **k):
        return None

    def add(self, _):
        pass


class FakeAlpaca:
    def submit_marketable_limit_ioc(self, *a, **k):
        raise AssertionError("should not submit when disabled")


def test_disabled():
    config = dict(DEFAULT_CONFIG)
    config["execution"]["paper_orders_enabled"] = False
    cand = ApprovedCandidate(
        signal_id=1,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        meta={},
        strength=1,
        confidence=0.9,
        spread_pct=0.001,
        liquidity_score=90,
        edge_over_cost=3,
        expected_move_pct=2,
        position_qty=0.01,
        entry_price=50000,
        stop_loss=49000,
        atr14=500,
        tier="TIER_MAJOR",
        cost_evidence={},
        sizing_evidence={},
    )
    policy = ExecutionPolicy(FakeSession(), config, FakeAlpaca(), SymbolTierService(config))
    logs = policy.process_selected(
        "c1", [cand], quote_by_symbol={"BTC/USD": {"bid": 49900, "ask": 50000, "mid": 49950}}
    )
    assert logs[0].status == "approved_no_order"
    assert logs[0].reject_reason == "PAPER_EXECUTION_DISABLED"
    print("verify_paper_execution_disabled: PASS")


if __name__ == "__main__":
    test_disabled()
