"""Closed shadow trade records non-zero PnL when entry and exit prices differ."""

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
        shadow_trade_id="shadow-nonzero-pnl-1",
        validation_run_id="paper_validation_run_001",
        symbol="LINK/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=10.0,
        evidence_json={
            "dynamic_exit_levels": {"entry_price": 10.0, "stop_loss": 8.0, "take_profit": 15.0}
        },
        setup_fingerprint="fp-nonzero-pnl",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow() - timedelta(hours=9),
    )
    session.add(row)
    session.commit()

    out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={"LINK/USD": 11.5})
    assert out.get("closed") == 1, out
    session.refresh(row)
    oj = row.outcome_json or {}
    assert row.entry_reference_price == 10.0
    assert row.exit_reference_price == 11.5
    assert abs(row.simulated_pnl_bps or 0) >= 1400, row.simulated_pnl_bps
    assert oj.get("price_source") == "scan_score", oj
    assert oj.get("exit_reason") == "shadow_max_hold", oj
    session.rollback()
    print("verify_shadow_outcome_nonzero_when_exit_price_differs: PASS")


if __name__ == "__main__":
    main()
