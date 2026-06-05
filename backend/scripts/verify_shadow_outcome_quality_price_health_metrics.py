"""Shadow outcome quality bundle must expose price-data health metrics."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_CLOSED  # noqa: E402
from app.services.shadow_outcome_quality_service import build_shadow_outcome_quality  # noqa: E402
from app.services.shadow_outcome_service import BAR_LOOKUP_SOURCE, QUOTE_LOOKUP_SOURCE  # noqa: E402

REQUIRED = (
    "closes_attempted",
    "closes_with_exit_price",
    "closes_missing_exit_price",
    "missing_price_data_symbols",
    "quote_lookup_source",
    "bar_lookup_source",
    "quote_age_seconds",
    "fallback_used",
)


def main() -> None:
    session, cfg = session_with_config()
    session.add(
        ShadowTrade(
            shadow_trade_id="shadow-quality-closed-1",
            validation_run_id="paper_validation_run_001",
            symbol="BTC/USD",
            asset_class="crypto",
            promotion_level=LEVEL_SHADOW_TRADE,
            status=STATUS_CLOSED,
            entry_reference_price=100.0,
            exit_reference_price=105.0,
            simulated_pnl_bps=500.0,
            outcome_verdict="win",
            setup_fingerprint="fp-quality-health",
            outcome_json={
                "exit_reason": "shadow_max_hold",
                "price_source": "quote_mid",
                "quote_lookup_source": QUOTE_LOOKUP_SOURCE,
                "bar_lookup_source": None,
                "price_age_seconds": 3.0,
                "fallback_used": False,
                "hold_seconds": 400.0,
            },
            counts_as_broker_evidence=False,
            closed_at=datetime.utcnow(),
            created_at=datetime.utcnow() - timedelta(hours=2),
        )
    )
    session.commit()

    q = build_shadow_outcome_quality(session, cfg)
    missing = [k for k in REQUIRED if k not in q]
    assert not missing, missing
    assert q["closes_attempted"] >= 1
    assert q["closes_with_exit_price"] >= 1
    assert q["quote_lookup_source"] == QUOTE_LOOKUP_SOURCE
    assert q["bar_lookup_source"] == BAR_LOOKUP_SOURCE
    assert q["fallback_used"] == 0
    session.rollback()
    print("verify_shadow_outcome_quality_price_health_metrics: PASS")


if __name__ == "__main__":
    main()
