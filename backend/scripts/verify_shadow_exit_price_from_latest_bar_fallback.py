"""Shadow close falls back to latest bar close when quote unavailable."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import seed_bars, session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_OPEN  # noqa: E402
from app.services.shadow_outcome_service import BAR_LOOKUP_SOURCE, ShadowOutcomeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    seed_bars(session, symbol="AVAX/USD", n=20)
    row = ShadowTrade(
        shadow_trade_id="shadow-bar-fallback-1",
        validation_run_id="paper_validation_run_001",
        symbol="AVAX/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=30.0,
        evidence_json={"dynamic_exit_levels": {"entry_price": 30.0, "stop_loss": 28.0}},
        setup_fingerprint="fp-bar-fallback",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow() - timedelta(hours=9),
    )
    session.add(row)
    session.commit()

    with patch(
        "app.services.shadow_outcome_service.ShadowOutcomeService._quote_service"
    ) as mock_qs:
        mock_qs.return_value.check.return_value = {"mid": None, "bid": None, "ask": None}
        out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={})

    assert out.get("closed") == 1, out
    session.refresh(row)
    oj = row.outcome_json or {}
    assert oj.get("price_source") == "bar_close", oj
    assert oj.get("bar_lookup_source") == BAR_LOOKUP_SOURCE, oj
    assert oj.get("fallback_used") is True, oj
    assert row.exit_reference_price is not None and row.exit_reference_price > 0
    assert row.outcome_verdict in ("win", "loss", "flat"), row.outcome_verdict
    session.rollback()
    print("verify_shadow_exit_price_from_latest_bar_fallback: PASS")


if __name__ == "__main__":
    main()
