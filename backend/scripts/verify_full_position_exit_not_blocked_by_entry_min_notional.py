"""Full-position sell below entry min notional must pass with EXIT_FULL_POSITION_MIN_NOTIONAL_EXEMPT."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, delete

from app.database import ExecutionLog, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.execution_preflight import run_preflight
from app.services.portfolio_gate import ApprovedCandidate


def main():
    init_db()
    with Session(engine) as session:
        session.exec(delete(ExecutionLog).where(ExecutionLog.side == "sell"))
        session.commit()
        config = ConfigManager(session).get_current()
        config["min_order_notional_usd"] = 50.0
        config.setdefault("execution", {})["paper_orders_enabled"] = True
        config["execution"]["live_orders_enabled"] = False
        positions = [SimpleNamespace(symbol="DOGEUSD", qty=292.633555314)]
        cand = ApprovedCandidate(
            signal_id=99001,
            symbol="DOGE/USD",
            side="sell",
            signal_type="exit",
            meta={
                "purpose": "stale_position_exit",
                "asset_class": "crypto",
                "broker_confirmed_qty": 292.633555314,
                "current_price": 0.10172,
                "close_existing_position": True,
            },
            strength=0.9,
            confidence=0.9,
            spread_pct=0.001,
            liquidity_score=50,
            edge_over_cost=0,
            expected_move_pct=0,
            position_qty=292.633555314,
            entry_price=0.10172,
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
                cycle_run_id="training-exit-test-99001",
                portfolio_decision=pdec,
                account=SimpleNamespace(equity=1000, cash=500, buying_power=500, daily_pl_pct=0, drawdown_pct=0),
                positions=positions,
                open_order_symbols=set(),
                alpaca=SimpleNamespace(),
                quote={"bid": 0.1016, "ask": 0.1018, "spread_pct": 0.002},
            )
        assert pf.passed, f"expected pass got {pf.block_reason_code} {pf.human_reason}"
        assert pf.evidence.get("notional_exemption") == "EXIT_FULL_POSITION_MIN_NOTIONAL_EXEMPT"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
