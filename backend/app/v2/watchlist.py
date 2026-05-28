"""Live Alpaca watchlist — all USD crypto + major stocks, no long-lived cache."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.alpaca_adapter import normalize_crypto_symbol
from app.services.alpaca_crypto_assets import fetch_crypto_assets

# Research priority majors — always included when tradable on Alpaca paper.
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
]

MAJOR_STOCKS = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL",
]


def live_crypto_watchlist(*, force: bool = True) -> dict[str, Any]:
    """All active Alpaca USD crypto pairs + major priority list."""
    if not settings.alpaca_configured:
        return {
            "status": "not_configured",
            "symbols": [],
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
        "major_count": len(MAJOR_CRYPTO),
        "api_called": True,
        "source": "alpaca_v2_assets",
    }


def live_full_watchlist(*, force: bool = True) -> dict[str, Any]:
    crypto = live_crypto_watchlist(force=force)
    stocks = [{"symbol": s, "asset_type": "stock"} for s in MAJOR_STOCKS]
    crypto_rows = [{"symbol": s, "asset_type": "crypto"} for s in crypto.get("symbols") or []]
    return {
        "status": crypto.get("status", "ok"),
        "crypto": crypto,
        "stocks": stocks,
        "all_symbols": crypto_rows + stocks,
        "total": len(crypto_rows) + len(stocks),
    }
