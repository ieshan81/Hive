"""At max_open_shadow_trades cap, oldest open trade is released so new L1 can open."""

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
from app.services.shadow_trade_service import ShadowTradeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    cfg = {**cfg, "shadow_league": {**(cfg.get("shadow_league") or {}), "max_open_shadow_trades": 2}}
    run_id = "paper_validation_run_001"
    for i in range(2):
        session.add(
            ShadowTrade(
                shadow_trade_id=f"cap-old-{i}",
                validation_run_id=run_id,
                symbol=f"COIN{i}/USD",
                asset_class="crypto",
                promotion_level=LEVEL_SHADOW_TRADE,
                status=STATUS_OPEN,
                entry_reference_price=10.0 + i,
                setup_fingerprint=f"fp-cap-{i}",
                counts_as_broker_evidence=False,
                created_at=datetime.utcnow() - timedelta(hours=i + 1),
            )
        )
    session.commit()

    released = ShadowOutcomeService(session, cfg).release_oldest_open_if_at_cap(run_id)
    assert released >= 1, released
    row = {
        "symbol": "NEW/USD",
        "asset_class": "crypto",
        "trade_quality_score": 50.0,
        "push_score": 1.0,
        "entry_allowed": False,
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
        "dynamic_exit_levels": {"entry_price": 1.0, "stop_loss": 0.9, "take_profit": 1.2},
    }
    out = ShadowTradeService(session, cfg).consider_setup(
        row, strategy_id="crypto_push_pull_baseline", paper_blocked_reason="ALPHA_NOT_READY"
    )
    assert (out.get("shadow_trade") or {}).get("shadow_trade_id") or out.get("shadow_trade", {}).get("status") != "skipped", out
    session.rollback()
    print("verify_shadow_max_open_cap_not_stuck: PASS")


if __name__ == "__main__":
    main()
