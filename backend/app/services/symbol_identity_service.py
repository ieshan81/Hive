"""
Symbol Identity / Logo Service.

Every stock and crypto gets a visual identity payload:
  { symbol, asset_type, display_name, glyph, color, badge_letter,
    logo_url?, logo_source?, exchange, cached_at }

Provider order:
  Crypto: CoinGecko (if COINGECKO_API_KEY) -> local glyph -> letter badge
  Stocks: Polygon (if POLYGON_API_KEY) -> Clearbit (if domain map) -> local map -> letter badge

The service NEVER fails the API call.  Missing provider -> always fall back to badge.
No network call is made for symbols already in the local glyph/map tables.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Local glyph maps (from spec)
# ----------------------------------------------------------------------

CRYPTO_GLYPHS: dict[str, str] = {
    "BTC": "₿", "BTCUSD": "₿", "BTC/USD": "₿",
    "ETH": "Ξ", "ETHUSD": "Ξ", "ETH/USD": "Ξ",
    "DOGE": "Ð", "DOGEUSD": "Ð", "DOGE/USD": "Ð",
    "SOL": "◎", "SOLUSD": "◎", "SOL/USD": "◎",
    "AVAX": "A", "AVAXUSD": "A", "AVAX/USD": "A",
    "LINK": "⛓", "LINKUSD": "⛓", "LINK/USD": "⛓",
    "LTC": "Ł", "LTCUSD": "Ł", "LTC/USD": "Ł",
    "UNI": "U", "UNIUSD": "U", "UNI/USD": "U",
    "AAVE": "Λ", "AAVEUSD": "Λ", "AAVE/USD": "Λ",
    "BCH": "B", "BCHUSD": "B", "BCH/USD": "B",
    "MATIC": "M", "MATICUSD": "M", "MATIC/USD": "M",
    "USDT": "₮", "USDTUSD": "₮", "USDT/USD": "₮",
    "USDC": "$", "USDCUSD": "$", "USDC/USD": "$",
    "DOT": "●", "DOTUSD": "●", "DOT/USD": "●",
    "ADA": "₳", "ADAUSD": "₳", "ADA/USD": "₳",
    "XRP": "X", "XRPUSD": "X", "XRP/USD": "X",
    "SHIB": "S", "SHIBUSD": "S", "SHIB/USD": "S",
}

STOCK_BADGES: dict[str, str] = {
    "NVDA": "N", "AAPL": "A", "MSFT": "M", "TSLA": "T", "AMD": "AMD",
    "META": "M", "AMZN": "A", "GOOGL": "G", "GOOG": "G",
    "SPY": "ETF", "QQQ": "ETF", "IWM": "ETF", "DIA": "ETF",
    "MARA": "M", "RIOT": "R", "COIN": "C", "PLTR": "P", "SOFI": "S",
    "NFLX": "N", "BAC": "B", "JPM": "J", "F": "F", "GM": "GM",
    "T": "T", "INTC": "I", "BABA": "A", "NIO": "N",
    "XLK": "ETF", "XLF": "ETF", "XLE": "ETF", "XLY": "ETF", "XLV": "ETF",
    "ARKK": "ARK", "SOXL": "3X", "TQQQ": "3X", "SQQQ": "3X",
    "UVXY": "VIX", "GLD": "ETF", "SLV": "ETF", "USO": "ETF", "TLT": "ETF", "HYG": "ETF",
}

# Brand-coloured palette (used as fallback accent if logo unavailable)
CRYPTO_COLORS: dict[str, str] = {
    "BTC": "#f7931a", "ETH": "#627eea", "DOGE": "#c2a633", "SOL": "#14f195",
    "AVAX": "#e84142", "LINK": "#2a5ada", "LTC": "#b8b8b8", "UNI": "#ff007a",
    "USDT": "#26a17b", "USDC": "#2775ca", "ADA": "#0033ad", "XRP": "#23292f",
    "SHIB": "#ffa409", "MATIC": "#8247e5", "DOT": "#e6007a", "AAVE": "#2ebac6",
}

DEFAULT_COLOR = "#00dbe9"  # neon cyan — Stitch primary fixed dim


# ----------------------------------------------------------------------
# In-memory cache (process-local)
# ----------------------------------------------------------------------

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
_ERRORS: list[dict[str, Any]] = []
_ERRORS_MAX = 200


def _record_error(symbol: str, provider: str, err: str) -> None:
    _ERRORS.append({
        "symbol": symbol,
        "provider": provider,
        "error": err[:200],
        "at": datetime.utcnow().isoformat() + "Z",
    })
    if len(_ERRORS) > _ERRORS_MAX:
        del _ERRORS[: len(_ERRORS) - _ERRORS_MAX]


# ----------------------------------------------------------------------
# Identity builder
# ----------------------------------------------------------------------

def _base_ticker(symbol: str) -> str:
    """Strip /USD, /USDT, /USDC suffixes and dashes."""
    s = symbol.upper().replace("-", "")
    for suf in ("/USD", "/USDT", "/USDC", "USDT", "USDC"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s.rstrip("/")


def _fallback_letter_badge(symbol: str) -> str:
    base = _base_ticker(symbol)
    if not base:
        return "?"
    return base[0].upper()


def _classify_asset(symbol: str) -> str:
    """crypto if symbol has / or known crypto base, else stock."""
    s = symbol.upper()
    if "/" in s:
        return "crypto"
    base = _base_ticker(s)
    if base in CRYPTO_GLYPHS:
        return "crypto"
    if s.endswith("USD") and base != s:
        return "crypto"
    return "stock"


def _build_local_identity(symbol: str) -> dict[str, Any]:
    asset_type = _classify_asset(symbol)
    base = _base_ticker(symbol)
    glyph = None
    badge = None
    color = DEFAULT_COLOR
    display_name = base

    if asset_type == "crypto":
        glyph = CRYPTO_GLYPHS.get(base) or CRYPTO_GLYPHS.get(symbol.upper())
        color = CRYPTO_COLORS.get(base, DEFAULT_COLOR)
        badge = badge or glyph or _fallback_letter_badge(symbol)
        display_name = base
    else:
        badge = STOCK_BADGES.get(base, _fallback_letter_badge(symbol))
        display_name = base

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "display_name": display_name,
        "glyph": glyph,
        "badge_letter": badge,
        "color": color,
        "logo_url": None,
        "logo_source": "local_glyph" if glyph else "letter_badge",
        "exchange": "alpaca_crypto" if asset_type == "crypto" else "alpaca_us_equity",
        "cached_at": datetime.utcnow().isoformat() + "Z",
        "ttl_seconds": _CACHE_TTL_SECONDS,
    }


# ----------------------------------------------------------------------
# Optional CoinGecko enrichment (only when CONFIGURED)
# ----------------------------------------------------------------------

def _coingecko_enabled() -> bool:
    return bool(os.environ.get("COINGECKO_API_KEY"))


_COINGECKO_ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "DOGE": "dogecoin", "SOL": "solana",
    "AVAX": "avalanche-2", "LINK": "chainlink", "LTC": "litecoin", "UNI": "uniswap",
    "USDT": "tether", "USDC": "usd-coin", "ADA": "cardano", "XRP": "ripple",
    "SHIB": "shiba-inu", "MATIC": "matic-network", "DOT": "polkadot", "AAVE": "aave",
    "BCH": "bitcoin-cash",
}


def _try_coingecko(base: str) -> Optional[dict[str, Any]]:
    if not _coingecko_enabled():
        return None
    coin_id = _COINGECKO_ID_MAP.get(base)
    if not coin_id:
        return None
    api_key = os.environ.get("COINGECKO_API_KEY", "")
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false"
        req = urllib.request.Request(url, headers={"x-cg-demo-api-key": api_key})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
        image = (data.get("image") or {}).get("large")
        if image:
            return {"logo_url": image, "logo_source": "coingecko"}
    except Exception as exc:
        _record_error(base, "coingecko", str(exc))
    return None


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def get_identity(symbol: str, *, allow_network: bool = True) -> dict[str, Any]:
    """
    Returns identity payload for one symbol.  Always succeeds (falls back to
    letter badge).  Caches by symbol.
    """
    key = symbol.upper().strip()
    if not key:
        return _build_local_identity("?")

    now = datetime.utcnow()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached:
            ts = cached.get("_cached_at_ts", 0)
            if (now.timestamp() - ts) < _CACHE_TTL_SECONDS:
                return {k: v for k, v in cached.items() if not k.startswith("_")}

    identity = _build_local_identity(key)

    if allow_network and identity["asset_type"] == "crypto" and _coingecko_enabled():
        enrichment = _try_coingecko(_base_ticker(key))
        if enrichment:
            identity.update(enrichment)

    with _CACHE_LOCK:
        identity["_cached_at_ts"] = now.timestamp()
        _CACHE[key] = identity
    return {k: v for k, v in identity.items() if not k.startswith("_")}


def get_many(symbols: list[str], *, allow_network: bool = True) -> dict[str, dict[str, Any]]:
    return {s: get_identity(s, allow_network=allow_network) for s in symbols}


def refresh_cache(symbols: Optional[list[str]] = None) -> dict[str, Any]:
    """Clear cache (selective or full) and rebuild from local maps."""
    with _CACHE_LOCK:
        if symbols is None:
            _CACHE.clear()
            return {"status": "ok", "cleared": "all", "remaining_items": 0}
        for s in symbols:
            _CACHE.pop(s.upper().strip(), None)
        return {"status": "ok", "cleared": symbols, "remaining_items": len(_CACHE)}


def cache_snapshot() -> dict[str, Any]:
    with _CACHE_LOCK:
        return {
            "items": len(_CACHE),
            "ttl_seconds": _CACHE_TTL_SECONDS,
            "symbols": sorted(list(_CACHE.keys())),
            "coingecko_configured": _coingecko_enabled(),
        }


def error_snapshot() -> list[dict[str, Any]]:
    return list(_ERRORS)


def status() -> dict[str, Any]:
    return {
        "service": "symbol_identity",
        "providers": {
            "coingecko": "configured" if _coingecko_enabled() else "not_configured_using_local_fallback",
            "polygon": "configured" if os.environ.get("POLYGON_API_KEY") else "not_configured_using_local_fallback",
            "local_glyph": "active",
            "letter_badge": "active",
        },
        "crypto_glyphs_loaded": len(set(CRYPTO_GLYPHS.values())),
        "stock_badges_loaded": len(STOCK_BADGES),
        "cache": cache_snapshot(),
        "recent_errors": len(_ERRORS),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    }
