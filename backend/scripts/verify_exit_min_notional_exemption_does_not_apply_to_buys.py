"""Entry buys below min notional use ENTRY_MIN_NOTIONAL_BLOCK, not exit exemption."""

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
        cand = ApprovedCandidate(
            signal_id=99003,
            symbol="DOGE/USD",
            side="buy",
            signal_type="entry",
            meta={"asset_class": "crypto", "current_price": 0.1, "expected_move_pct": 0.05},
            strength=0.9,
            confidence=0.9,
            spread_pct=0.001,
            liquidity_score=50,
            edge_over_cost=0.1,
            expected_move_pct=0.05,
            position_qty=10,
            entry_price=0.1,
            stop_loss=0.09,
            atr14=0.01,
            tier="MEME_SUPPORTED",
            cost_evidence={},
            sizing_evidence={},
        )
        pdec = SimpleNamespace(selected_for_execution=True, portfolio_rank=1, portfolio_status="approved")
        cost_pass = SimpleNamespace(passed=True, human_reason="", evidence={})
        with patch("app.services.execution_preflight.is_paper_broker_url", return_value=True), patch(
            "app.services.execution_preflight._signal_already_submitted", return_value=False
        ), patch("app.services.execution_preflight._cycle_orders", return_value=0), patch(
            "app.services.execution_preflight._orders_in_window", return_value=0
        ), patch("app.services.execution_preflight.evaluate_cost_edge", return_value=cost_pass):
            pf = run_preflight(
                session,
                config,
                cand=cand,
                cycle_run_id="cycle-buy-99003",
                portfolio_decision=pdec,
                account=SimpleNamespace(equity=10000, cash=9500, buying_power=9500, daily_pl_pct=0, drawdown_pct=0),
                positions=[],
                open_order_symbols=set(),
                alpaca=SimpleNamespace(),
                quote={"bid": 0.099, "ask": 0.101, "spread_pct": 0.002},
            )
        assert not pf.passed
        assert pf.block_reason_code == "ENTRY_MIN_NOTIONAL_BLOCK"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
