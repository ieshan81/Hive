"""Shadow close must resolve exit price from quote when scan price absent."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_OPEN  # noqa: E402
from app.services.shadow_outcome_service import QUOTE_LOOKUP_SOURCE, ShadowOutcomeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = ShadowTrade(
        shadow_trade_id="shadow-quote-exit-1",
        validation_run_id="paper_validation_run_001",
        symbol="ETH/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=2000.0,
        evidence_json={"dynamic_exit_levels": {"entry_price": 2000.0, "stop_loss": 1900.0}},
        setup_fingerprint="fp-quote-exit",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow() - timedelta(hours=9),
    )
    session.add(row)
    session.commit()

    def _quote_check(symbol, *, asset_class="crypto", quote=None):
        return {
            "symbol": symbol,
            "mid": 2050.0,
            "quote_age_seconds": 2.0,
            "quote_lookup_source": QUOTE_LOOKUP_SOURCE,
        }

    with patch.object(ShadowOutcomeService, "_latest_bar_close", return_value={"price": None}):
        with patch(
            "app.services.shadow_outcome_service.ShadowOutcomeService._quote_service"
        ) as mock_qs:
            mock_qs.return_value.check.side_effect = _quote_check
            out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={})

    assert out.get("closed") == 1, out
    session.refresh(row)
    oj = row.outcome_json or {}
    assert oj.get("price_source") == "quote_mid", oj
    assert oj.get("quote_lookup_source") == QUOTE_LOOKUP_SOURCE, oj
    assert row.exit_reference_price == 2050.0
    assert abs(row.simulated_pnl_bps or 0) >= 200, row.simulated_pnl_bps
    session.rollback()
    print("verify_shadow_exit_price_from_quote: PASS")


if __name__ == "__main__":
    main()
