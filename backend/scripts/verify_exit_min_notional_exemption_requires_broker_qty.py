"""Exemption denied without broker-confirmed qty."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import patch

from sqlmodel import Session

from app.database import engine, init_db
from app.services.closing_position_preflight import evaluate_full_position_exit_exemption
from app.services.config_manager import ConfigManager
from app.services.portfolio_gate import ApprovedCandidate


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        cfg.setdefault("execution", {})["paper_orders_enabled"] = True
        cfg["execution"]["live_orders_enabled"] = False
        cand = ApprovedCandidate(
            signal_id=1,
            symbol="DOGE/USD",
            side="sell",
            signal_type="exit",
            meta={"purpose": "stale_position_exit", "asset_class": "crypto"},
            strength=0.9,
            confidence=0.9,
            spread_pct=0.001,
            liquidity_score=50,
            edge_over_cost=0,
            expected_move_pct=0,
            position_qty=100,
            entry_price=0.1,
            stop_loss=None,
            atr14=None,
            tier="MEME_SUPPORTED",
            cost_evidence={},
            sizing_evidence={},
        )
        with patch("app.services.closing_position_preflight.is_paper_broker_url", return_value=True), patch(
            "app.services.closing_position_preflight.current_promotion_stage", return_value="PAPER"
        ), patch(
            "app.services.closing_position_preflight.live_lock_status",
            return_value={"live_lock_status": "locked"},
        ):
            ok, ev = evaluate_full_position_exit_exemption(session, cfg, cand=cand, positions=[])
        assert not ok, ev
        assert ev.get("fail") == "no_broker_qty"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
