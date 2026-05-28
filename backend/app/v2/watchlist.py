"""Live Alpaca watchlist — all USD crypto + liquid stocks (no stale cache)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.config import settings
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.alpaca_crypto_assets import fetch_crypto_assets
from app.services.session_engine import SessionEngine

MAJOR_CRYPTO = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "DOGE/USD",
    "AVAX/USD",
    "LINK/USD",
    "MATIC/USD",
    "ADA/USD",
    "XRP/USD",
    "LTC/USD",
    "DOT/USD",
    "UNI/USD",
    "ATOM/USD",
    "NEAR/USD",
    "APT/USD",
    "ARB/USD",
    "SHIB/USD",
    "BCH/USD",
]

MAJOR_STOCKS = [
    "SPY",
    "QQQ",
    "IWM",
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL",
    "GOOG",
    "NFLX",
    "COIN",
    "MARA",
    "PLTR",
    "SOFI",
    "BAC",
    "F",
    "INTC",
]


def live_crypto_watchlist(*, force: bool = True) -> dict[str, Any]:
    if not settings.alpaca_configured:
        return {
            "status": "not_configured",
            "symbols": list(MAJOR_CRYPTO),
            "usd_pairs": 0,
            "message": "Set ALPACA_API_KEY and ALPACA_SECRET_KEY",
        }
    assets = fetch_crypto_assets(force=force) or {}
    usd = sorted(s for s in assets if s.endswith("/USD") and assets[s].get("tradable", True))
    ordered: list[str] = []
    seen: set[str] = set()
    for sym in MAJOR_CRYPTO + usd:
        if sym in seen:
            continue
        if sym in assets or sym in MAJOR_CRYPTO:
            ordered.append(sym)
            seen.add(sym)
    return {
        "status": "ok",
        "symbols": ordered,
        "usd_pairs": len(usd),
        "api_called": True,
        "source": "alpaca_v2_assets",
    }


def live_stock_watchlist(session: Session, *, limit: int = 80) -> dict[str, Any]:
    if not settings.alpaca_configured:
        return {"status": "not_configured", "symbols": list(MAJOR_STOCKS), "count": len(MAJOR_STOCKS)}
    session_state = SessionEngine().detect()
    if not session_state.stock_trading_allowed:
        return {
            "status": "session_closed",
            "symbols": list(MAJOR_STOCKS),
            "count": len(MAJOR_STOCKS),
            "message": "US stock session closed — majors kept for display",
        }
    alpaca = AlpacaAdapter(session)
    rows = alpaca.get_tradable_assets(asset_class="stock", limit=limit) or []
    syms = sorted({str(r["symbol"]) for r in rows if r.get("tradable")})
    ordered: list[str] = []
    seen: set[str] = set()
    for s in MAJOR_STOCKS + syms:
        if s and s not in seen:
            ordered.append(s)
            seen.add(s)
    return {
        "status": "ok",
        "symbols": ordered[:limit],
        "count": len(ordered),
        "api_called": True,
    }


def live_full_watchlist(session: Session, *, force: bool = True) -> dict[str, Any]:
    crypto = live_crypto_watchlist(force=force)
    stocks = live_stock_watchlist(session)
    crypto_rows = [{"symbol": s, "asset_type": "crypto"} for s in crypto.get("symbols") or []]
    stock_rows = [{"symbol": s, "asset_type": "stock"} for s in stocks.get("symbols") or []]
    return {
        "status": "ok" if crypto.get("status") != "not_configured" else crypto.get("status"),
        "crypto": crypto,
        "stocks": stocks,
        "all_symbols": crypto_rows + stock_rows,
        "total": len(crypto_rows) + len(stock_rows),
    }


# Fast bootstrap bar refresh — majors only (under 2 min on paper API)
BOOTSTRAP_CRYPTO = MAJOR_CRYPTO[:10]
BOOTSTRAP_STOCKS = MAJOR_STOCKS[:8]
