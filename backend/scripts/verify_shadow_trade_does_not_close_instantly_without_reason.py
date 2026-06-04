"""Open shadow trade must not close within min_hold_seconds without explicit reason."""

from __future__ import annotations

import os
import sys
from datetime import datetime
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
        shadow_trade_id="shadow-hold-test-1",
        validation_run_id="paper_validation_run_001",
        symbol="ETH/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=2000.0,
        evidence_json={
            "dynamic_exit_levels": {
                "entry_price": 2000.0,
                "stop_loss": 1900.0,
                "take_profit": 2200.0,
            }
        },
        setup_fingerprint="fp-hold-test",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()

    out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={"ETH/USD": 1990.0})
    assert out.get("closed") == 0, out
    session.refresh(row)
    assert row.status == STATUS_OPEN, row.status
    session.rollback()
    print("verify_shadow_trade_does_not_close_instantly_without_reason: PASS")


if __name__ == "__main__":
    main()
