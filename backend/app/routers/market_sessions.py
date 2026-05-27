"""Session, stock market open, and crypto 24/7 readiness APIs."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.config_manager import ConfigManager
from app.services.hybrid_radar_service import hybrid_radar_snapshot
from app.services.operator_auth import require_operator_token
from app.services.session_engine import SessionEngine

router = APIRouter(tags=["market-sessions"])


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


@router.get("/api/session/status")
def session_status(session: Session = Depends(get_session)):
    sess = SessionEngine().detect()
    return {"status": "ok", "generated_at_utc": _now(), "session": sess.to_dict()}


@router.get("/api/stocks/readiness")
def stocks_readiness(session: Session = Depends(get_session)):
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services.broker_safety import is_paper_broker_url, live_lock_status

    cfg = ConfigManager(session).get_current()
    sess = SessionEngine().detect()
    adapter = AlpacaAdapter(session)
    checks = {
        "calendar_available": bool(sess.calendar_available),
        "us_stock_session": sess.us_stock_session,
        "stock_trading_allowed": sess.stock_trading_allowed,
        "market_open": sess.stock_trading_allowed,
        "broker_configured": adapter.configured,
        "paper_broker": is_paper_broker_url(),
        "live_lock": live_lock_status(cfg),
        "strategy_active": True,
        "risk_cage_active": True,
    }
    ready = all(
        [
            checks["broker_configured"],
            checks["paper_broker"],
            checks["live_lock"].get("live_trading_enabled") is False,
            checks["calendar_available"] or checks["stock_trading_allowed"] is not None,
        ]
    )
    reason = None
    if not sess.stock_trading_allowed:
        reason = sess.us_stock_close_reason or "U.S. stock market is closed"
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "ready_for_market_open": ready and sess.stock_trading_allowed,
        "stocks_ready_label": (
            "Stocks ready for market open"
            if sess.stock_trading_allowed
            else f"Stocks not ready — {reason}"
        ),
        "checks": checks,
        "reason": reason,
    }


@router.get("/api/stocks/watchlist")
def stocks_watchlist(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import CURATED_STOCKS

    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "watchlist": CURATED_STOCKS,
        "count": len(CURATED_STOCKS),
    }


@router.post("/api/stocks/prepare-market-open")
def prepare_market_open(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.market_data_refresh_service import MarketDataRefreshService

    cfg = ConfigManager(session).get_current()
    bar = MarketDataRefreshService(session, cfg).refresh_bars(
        asset_type="stock", timeframe="5Min", lookback_hours=48
    )
    session.commit()
    readiness = stocks_readiness(session)
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "bar_refresh": bar,
        "readiness": readiness,
    }


@router.post("/api/scanners/run-market-open-check")
def run_market_open_check(session: Session = Depends(get_session)):
    from app.services import scanner_stack

    return scanner_stack.run_all(session, symbols=["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])


@router.get("/api/crypto/readiness")
def crypto_readiness(session: Session = Depends(get_session)):
    from app.services.broker_safety import is_paper_broker_url, live_lock_status
    from app.services.alpaca_crypto_assets import fetch_crypto_assets

    cfg = ConfigManager(session).get_current()
    sess = SessionEngine().detect()
    assets = fetch_crypto_assets(force=False) or {}
    usd = [s for s in assets if s.endswith("/USD")]
    radar = hybrid_radar_snapshot(session, cfg)
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "crypto_24_7_active": bool(sess.crypto_trading_allowed),
        "crypto_24_7_label": "Crypto 24/7: Active" if sess.crypto_trading_allowed else "Crypto 24/7: Inactive",
        "available_usd_pairs": len(usd),
        "evaluated": radar.get("counts", {}).get("evaluated"),
        "eligible": radar.get("counts", {}).get("eligible"),
        "execution_shortlist": radar.get("counts", {}).get("execution_shortlist"),
        "paper_broker": is_paper_broker_url(),
        "live_lock": live_lock_status(cfg),
        "lesser_known_highlights": radar.get("lesser_known_highlights", []),
    }


@router.get("/api/crypto/radar")
def crypto_radar(session: Session = Depends(get_session)):
    return hybrid_radar_snapshot(session)


@router.post("/api/crypto/run-cycle")
def crypto_run_cycle(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services import scanner_stack

    out = scanner_stack.run_all(session)
    return {"status": "ok", "generated_at_utc": _now(), "scanner_run": out}
