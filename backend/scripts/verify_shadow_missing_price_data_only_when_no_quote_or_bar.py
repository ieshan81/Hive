"""missing_price_data only when neither quote nor bar provides a price."""

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
from app.services.shadow_outcome_service import ShadowOutcomeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = ShadowTrade(
        shadow_trade_id="shadow-missing-price-1",
        validation_run_id="paper_validation_run_001",
        symbol="OBSCURE/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_OPEN,
        entry_reference_price=12.5,
        evidence_json={"dynamic_exit_levels": {"entry_price": 12.5, "stop_loss": 11.0}},
        setup_fingerprint="fp-missing-price",
        counts_as_broker_evidence=False,
        created_at=datetime.utcnow() - timedelta(hours=9),
    )
    session.add(row)
    session.commit()

    with patch.object(ShadowOutcomeService, "_latest_bar_close", return_value={"price": None, "why": "no_bar_stored"}):
        with patch(
            "app.services.shadow_outcome_service.ShadowOutcomeService._quote_service"
        ) as mock_qs:
            mock_qs.return_value.check.return_value = {"mid": None, "bid": None, "ask": None}
            out = ShadowOutcomeService(session, cfg).update_open_trades(price_by_symbol={})

    assert out.get("closed") == 1, out
    session.refresh(row)
    oj = row.outcome_json or {}
    assert oj.get("exit_reason") == "missing_price_data", oj
    assert oj.get("price_source") == "missing", oj
    assert oj.get("missing_price_why") == "no_bar_stored", oj
    assert row.exit_reference_price == 12.5
    assert abs(row.simulated_pnl_bps or 0) < 0.5
    assert row.outcome_verdict == "unknown"
    session.rollback()
    print("verify_shadow_missing_price_data_only_when_no_quote_or_bar: PASS")


if __name__ == "__main__":
    main()
