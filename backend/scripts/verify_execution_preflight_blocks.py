"""Preflight blocks unsafe submission."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.execution_preflight import run_preflight
from app.services.portfolio_gate import ApprovedCandidate
from app.database import PortfolioDecision


class FakeSession:
    def get(self, *a, **k):
        return None

    def exec(self, *a, **k):
        class R:
            def first(self):
                return None

            def all(self):
                return []

        return R()


def _cand(**kw):
    base = dict(
        signal_id=1,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        meta={"expected_hold_time": "12h"},
        strength=1,
        confidence=0.9,
        spread_pct=0.001,
        liquidity_score=80,
        edge_over_cost=3,
        expected_move_pct=2.0,
        position_qty=0.05,
        entry_price=100,
        stop_loss=95,
        atr14=1,
        tier="TIER_MAJOR",
        cost_evidence={},
        sizing_evidence={},
    )
    base.update(kw)
    return ApprovedCandidate(**base)


def test_paper_disabled():
    cfg = dict(DEFAULT_CONFIG)
    cfg["execution"]["paper_orders_enabled"] = False
    r = run_preflight(
        FakeSession(),
        cfg,
        cand=_cand(),
        cycle_run_id="x",
        portfolio_decision=PortfolioDecision(
            id=1,
            cycle_run_id="x",
            signal_id=1,
            symbol="BTC/USD",
            side="buy",
            signal_type="entry",
            portfolio_status="portfolio_approved",
            selected_for_execution=True,
            portfolio_rank=1,
        ),
        account=None,
        positions=[],
        open_order_symbols=set(),
        alpaca=None,
        quote={"bid": 1, "ask": 1.01, "mid": 1.005},
    )
    assert r.block_reason_code == "PAPER_EXECUTION_DISABLED"
    print("preflight paper disabled: PASS")


def test_missing_stop():
    cfg = dict(DEFAULT_CONFIG)
    cfg["execution"]["paper_orders_enabled"] = True
    r = run_preflight(
        FakeSession(),
        cfg,
        cand=_cand(stop_loss=None),
        cycle_run_id="x",
        portfolio_decision=PortfolioDecision(
            id=1,
            cycle_run_id="x",
            signal_id=1,
            symbol="BTC/USD",
            side="buy",
            signal_type="entry",
            portfolio_status="portfolio_approved",
            selected_for_execution=True,
            portfolio_rank=1,
        ),
        account=type("A", (), {"equity": 200, "cash": 120, "buying_power": 200, "daily_pl_pct": 0, "drawdown_pct": 0})(),
        positions=[],
        open_order_symbols=set(),
        alpaca=None,
        quote={"bid": 1, "ask": 1.01, "spread_pct": 0.001},
        signal_row=type("S", (), {"stop_loss": None, "take_profit": None, "signal_metadata": {}, "status": "risk_approved"})(),
    )
    assert r.block_reason_code == "MISSING_STOP_LOSS"
    print("preflight missing stop: PASS")


if __name__ == "__main__":
    test_paper_disabled()
    test_missing_stop()
