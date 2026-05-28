"""V2 AI trading agent — bars → score → dynamic exits → paper orders (research loop)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.dynamic_weights_service import get_dynamic_weights, suggest_weights_with_ai
from app.services.market_data_refresh_service import MarketDataRefreshService
from app.services.product_truth_service import product_truth
from app.services.push_pull_scoring_service import score_active_universe
from app.services.session_engine import SessionEngine
from app.v2.live_pipeline import live_funnel
from app.v2.watchlist import BOOTSTRAP_CRYPTO, BOOTSTRAP_STOCKS, live_full_watchlist

logger = logging.getLogger("hive.v2.agent")


def refresh_watchlist_bars(
    session: Session,
    config: dict,
    *,
    crypto_symbols: Optional[list[str]] = None,
    stock_symbols: Optional[list[str]] = None,
    operator: str = "v2_agent",
) -> dict[str, Any]:
    crypto_symbols = crypto_symbols or BOOTSTRAP_CRYPTO
    stock_symbols = stock_symbols or []
    mds = MarketDataRefreshService(session, config)
    out_crypto = mds.refresh_bars(
        asset_type="crypto",
        timeframe="5Min",
        symbols=crypto_symbols,
        lookback_hours=36,
        operator=operator,
    )
    out_stock = {}
    sess = SessionEngine(session).current()
    if stock_symbols and sess.stock_trading_allowed:
        out_stock = mds.refresh_bars(
            asset_type="stock",
            timeframe="5Min",
            symbols=stock_symbols,
            lookback_hours=36,
            operator=operator,
        )
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("refresh_watchlist_bars commit: %s", exc)
    return {"crypto": out_crypto, "stock": out_stock}


def score_watchlist(
    session: Session,
    config: dict,
    *,
    limit: int = 32,
) -> dict[str, Any]:
    return score_active_universe(session, config, limit=limit)


def run_agent_cycle(session: Session, operator: str = "v2_agent") -> dict[str, Any]:
    """
    One aggressive cycle:
    1. Live watchlist from Alpaca (crypto + stocks)
    2. Refresh 5m bars for bootstrap set + any shortlist majors
    3. Score universe
    4. Optional AI weight nudge (Gemini proposes, validator applies)
    5. Fast-training run-once (exits + best entry)
    """
    cfg = ConfigManager(session).get_current()
    wl = live_full_watchlist(session, force=True)

    crypto_syms = (wl.get("crypto") or {}).get("symbols") or BOOTSTRAP_CRYPTO
    stock_syms = []
    if (wl.get("stocks") or {}).get("status") == "ok":
        stock_syms = (wl.get("stocks") or {}).get("symbols") or BOOTSTRAP_STOCKS[:6]

    refresh = refresh_watchlist_bars(
        session,
        cfg,
        crypto_symbols=crypto_syms[:16],
        stock_symbols=stock_syms[:6],
        operator=operator,
    )

    funnel = live_funnel(session, cfg, max_evaluate=48)
    scores = score_watchlist(session, cfg, limit=32)
    score_rows = scores.get("scores") or []
    passed = [r for r in score_rows if r.get("pass") or r.get("entry_allowed")]

    ai_nudge = None
    if len(passed) < 2 and bool((cfg.get("v2") or {}).get("aggressive_mode")):
        try:
            ai_nudge = suggest_weights_with_ai(
                session,
                context={
                    "passed_count": len(passed),
                    "funnel": funnel.get("funnel"),
                    "blockers": funnel.get("block_breakdown"),
                },
            )
            cfg = ConfigManager(session).get_current()
            scores = score_watchlist(session, cfg, limit=32)
            score_rows = scores.get("scores") or []
            passed = [r for r in score_rows if r.get("pass") or r.get("entry_allowed")]
        except Exception as exc:
            ai_nudge = {"status": "skipped", "error": str(exc)[:200]}

    from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop

    trade = FastCryptoTrainingLoop(session, cfg).run_once(actor=operator)

    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    sched = AutonomousPaperScheduler(session, cfg)
    if not sched.status().get("scheduler_enabled"):
        sched.enable(operator)

    truth = product_truth(session, cfg)
    weights = get_dynamic_weights(session)

    return {
        "status": "ok",
        "cycle_at": datetime.utcnow().isoformat() + "Z",
        "watchlist_total": wl.get("total"),
        "bars_refresh": refresh,
        "funnel": funnel.get("funnel"),
        "shortlist": funnel.get("shortlist"),
        "why_zero_shortlist": funnel.get("why_zero_shortlist"),
        "passed_scores": len(passed),
        "top_setup": passed[0] if passed else None,
        "scores_preview": score_rows[:8],
        "ai_nudge": ai_nudge,
        "trade_cycle": trade,
        "scheduler": sched.status(),
        "can_place_paper_orders": truth.get("can_place_paper_orders"),
        "blockers": truth.get("blockers"),
        "weights": weights.get("universe_ranking"),
    }
