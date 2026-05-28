"""One trading cycle — refresh bars, score watchlist, exits, optional entry (research loop)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.dynamic_weights_service import get_dynamic_weights
from app.services.market_data_refresh_service import MarketDataRefreshService
from app.services.product_truth_service import product_truth
from app.v2.live_pipeline import live_funnel
from app.v2.watchlist import MAJOR_CRYPTO, live_crypto_watchlist


def run_trading_cycle(session: Session, operator: str = "v2_cycle") -> dict[str, Any]:
    """Single synchronous cycle: data refresh → funnel → fast training run-once."""
    cfg = ConfigManager(session).get_current()
    wl = live_crypto_watchlist(force=True)
    symbols = (wl.get("symbols") or MAJOR_CRYPTO)[:20]

    refresh = MarketDataRefreshService(session, cfg).refresh_bars(
        asset_type="crypto",
        timeframe="5Min",
        symbols=symbols,
        lookback_hours=48,
        operator=operator,
    )
    try:
        session.commit()
    except Exception:
        session.rollback()

    funnel = live_funnel(session, cfg, max_evaluate=36)

    from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop

    ft = FastCryptoTrainingLoop(session)
    trade_out = ft.run_once(operator=operator, force=True)

    truth = product_truth(session, cfg)
    weights = get_dynamic_weights(session)

    return {
        "status": "ok",
        "cycle_at": datetime.utcnow().isoformat() + "Z",
        "watchlist_usd_pairs": wl.get("usd_pairs"),
        "bars_refreshed": refresh.get("symbols_refreshed") or refresh.get("rows_stored"),
        "funnel": funnel.get("funnel"),
        "shortlist": funnel.get("shortlist"),
        "why_zero_shortlist": funnel.get("why_zero_shortlist"),
        "trade_cycle": trade_out,
        "can_place_paper_orders": truth.get("can_place_paper_orders"),
        "blockers": truth.get("blockers"),
        "weights": weights.get("universe_ranking"),
        "paper_learning_on": truth.get("paper_learning_on"),
    }
