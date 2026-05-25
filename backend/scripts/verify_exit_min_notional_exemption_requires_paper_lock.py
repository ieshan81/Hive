"""Exemption denied when live lock is not locked."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.closing_position_preflight import evaluate_full_position_exit_exemption
from app.services.config_manager import ConfigManager
from app.services.portfolio_gate import ApprovedCandidate


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        cand = ApprovedCandidate(
            signal_id=2,
            symbol="DOGE/USD",
            side="sell",
            signal_type="exit",
            meta={"purpose": "max_hold_exit", "asset_class": "crypto", "broker_confirmed_qty": 10},
            strength=0.9,
            confidence=0.9,
            spread_pct=0.001,
            liquidity_score=50,
            edge_over_cost=0,
            expected_move_pct=0,
            position_qty=10,
            entry_price=0.1,
            stop_loss=None,
            atr14=None,
            tier="MEME_SUPPORTED",
            cost_evidence={},
            sizing_evidence={},
        )
        positions = [SimpleNamespace(symbol="DOGEUSD", qty=10)]
        with patch("app.services.closing_position_preflight.live_lock_status", return_value={"live_lock_status": "unlocked"}):
            ok, ev = evaluate_full_position_exit_exemption(session, cfg, cand=cand, positions=positions)
        assert not ok
        assert ev.get("fail") == "live_lock_not_locked"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
