"""Shadow trades close with documented exit_reason for stop/target/max_hold."""

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

ALLOWED = {
    "shadow_stop",
    "shadow_target",
    "shadow_trailing_stop",
    "shadow_invalidation",
    "shadow_max_hold",
    "shadow_reversal_risk",
    "missing_price_data",
    "missing_entry_price",
    "max_open_cap_release",
}


def main() -> None:
    session, cfg = session_with_config()
    row = ShadowTrade(
        shadow_trade_id="shadow-stop-test-1",
        validation_run_id="paper_validation_run_001",
        symbol="SOL/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=100.0,
        evidence_json={
            "dynamic_exit_levels": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 120.0}
        },
        setup_fingerprint="fp-stop-test",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow() - timedelta(minutes=3),
    )
    session.add(row)
    session.commit()
    out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={"SOL/USD": 94.0})
    assert out.get("closed") == 1, out
    session.refresh(row)
    reason = (row.outcome_json or {}).get("exit_reason")
    assert reason in ALLOWED, reason
    assert reason == "shadow_stop"
    assert row.closed_at is not None
    assert row.entry_reference_price == 100.0
    assert row.exit_reference_price == 95.0
    session.rollback()
    print("verify_shadow_open_trades_close_by_rule: PASS")


if __name__ == "__main__":
    main()
