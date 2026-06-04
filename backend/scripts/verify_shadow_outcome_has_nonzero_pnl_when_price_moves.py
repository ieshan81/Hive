"""Closed shadow trade must record non-zero PnL bps when entry/exit prices differ."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_OPEN  # noqa: E402
from app.services.shadow_outcome_service import ShadowOutcomeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = ShadowTrade(
        shadow_trade_id="shadow-pnl-test-1",
        validation_run_id="paper_validation_run_001",
        symbol="BTC/USD",
        asset_class="crypto",
        strategy_id="crypto_push_pull_baseline",
        side="buy",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=100.0,
        evidence_json={
            "dynamic_exit_levels": {
                "entry_price": 100.0,
                "stop_loss": 80.0,
                "take_profit": 130.0,
            }
        },
        setup_fingerprint="fp-pnl-test",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow() - timedelta(minutes=5),
    )
    session.add(row)
    session.commit()

    out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={"BTC/USD": 105.0})
    assert out.get("closed") == 0, "should not close before min hold with no rule hit"

    row.created_at = datetime.utcnow() - timedelta(hours=9)
    session.add(row)
    session.commit()
    out2 = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={"BTC/USD": 105.0})
    assert out2.get("closed") == 1, out2
    session.refresh(row)
    assert row.status == "closed"
    assert abs(row.simulated_pnl_bps or 0) >= 400, row.simulated_pnl_bps
    assert row.outcome_verdict in ("win", "flat"), row.outcome_verdict
    assert row.exit_reference_price == 105.0
    session.rollback()
    print("verify_shadow_outcome_has_nonzero_pnl_when_price_moves: PASS")


if __name__ == "__main__":
    main()
