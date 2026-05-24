"""Paper enabled + mock broker submits limit IOC."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.paper_execution_service import PaperExecutionService
from app.services.portfolio_gate import ApprovedCandidate
from app.database import PortfolioDecision


class FakeSession:
    def __init__(self):
        self.rows = []

    def add(self, obj):
        self.rows.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def get(self, model, pk):
        return None

    def exec(self, q):
        class R:
            def first(inner):
                return None

            def all(inner):
                return []

        return R()


class MockAlpaca:
    def get_quote(self, *a, **k):
        return {"bid": 1.0, "ask": 1.01, "mid": 1.005, "spread_pct": 0.001}

    def get_open_orders(self):
        return []

    def submit_marketable_limit_ioc(self, symbol, qty, side, **kw):
        return {"success": True, "order_id": "mock-order-1", "status": "accepted"}

    def get_order_by_id(self, oid):
        return {"status": "filled", "filled_qty": 0.01, "filled_avg_price": 1.01}

    def sync_account(self):
        return MagicMock(equity=200, cash=150, buying_power=200, daily_pl_pct=0, drawdown_pct=0)

    def sync_positions(self):
        return []

    @property
    def configured(self):
        return True


def test_mock_submit():
    cfg = dict(DEFAULT_CONFIG)
    cfg["execution"]["paper_orders_enabled"] = True
    svc = PaperExecutionService(FakeSession(), config=cfg)
    svc.alpaca = MockAlpaca()
    cand = ApprovedCandidate(
        signal_id=1,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        meta={"expected_hold_time": "12h", "exit_strategy": "rules"},
        strength=1,
        confidence=0.9,
        spread_pct=0.001,
        liquidity_score=80,
        edge_over_cost=3,
        expected_move_pct=2.0,
        position_qty=0.01,
        entry_price=100,
        stop_loss=95,
        atr14=1,
        tier="TIER_MAJOR",
        cost_evidence={},
        sizing_evidence={"risk_pct": 0.005},
    )
    dec = PortfolioDecision(
        id=1,
        cycle_run_id="abc",
        signal_id=1,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        portfolio_status="portfolio_approved",
        selected_for_execution=True,
        portfolio_rank=1,
    )
    log = svc.submit_candidate(
        cand,
        cycle_run_id="abc12345-0000-0000-0000-000000000001",
        portfolio_decision=dec,
        account=MockAlpaca().sync_account(),
        positions=[],
    )
    assert log.status in ("paper_order_submitted", "paper_order_filled")
    assert log.broker_order_id == "mock-order-1"
    print("verify_paper_execution_enabled: PASS")


if __name__ == "__main__":
    test_mock_submit()
