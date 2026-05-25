"""Partial sell below min notional must block with EXIT_MIN_NOTIONAL_BLOCK."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.config_manager import ConfigManager
from app.services.execution_preflight import run_preflight
from app.services.portfolio_gate import ApprovedCandidate


def main():
    init_db()
    with Session(engine) as session:
        config = ConfigManager(session).get_current()
        config["min_order_notional_usd"] = 50.0
        config.setdefault("execution", {})["paper_orders_enabled"] = True
        config["execution"]["live_orders_enabled"] = False
        positions = [SimpleNamespace(symbol="DOGEUSD", qty=292.633555314)]
        cand = ApprovedCandidate(
            signal_id=99002,
            symbol="DOGE/USD",
            side="sell",
            signal_type="exit",
            meta={"purpose": "stale_position_exit", "asset_class": "crypto", "current_price": 0.1},
            strength=0.9,
            confidence=0.9,
            spread_pct=0.001,
            liquidity_score=50,
            edge_over_cost=0,
            expected_move_pct=0,
            position_qty=10.0,
            entry_price=0.1,
            stop_loss=None,
            atr14=None,
            tier="MEME_SUPPORTED",
            cost_evidence={},
            sizing_evidence={},
        )
        pdec = SimpleNamespace(selected_for_execution=True, portfolio_rank=1, portfolio_status="approved")
        with patch("app.services.execution_preflight.is_paper_broker_url", return_value=True), patch(
            "app.services.closing_position_preflight.is_paper_broker_url", return_value=True
        ), patch("app.services.execution_preflight._signal_already_submitted", return_value=False), patch(
            "app.services.execution_preflight._cycle_orders", return_value=0
        ), patch("app.services.execution_preflight._orders_in_window", return_value=0):
            pf = run_preflight(
                session,
                config,
                cand=cand,
                cycle_run_id="training-exit-partial-99002",
                portfolio_decision=pdec,
                account=SimpleNamespace(equity=1000, cash=500, buying_power=500, daily_pl_pct=0, drawdown_pct=0),
                positions=positions,
                open_order_symbols=set(),
                alpaca=SimpleNamespace(),
                quote={"bid": 0.099, "ask": 0.101, "spread_pct": 0.002},
            )
        assert not pf.passed
        assert pf.block_reason_code == "EXIT_MIN_NOTIONAL_BLOCK"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
