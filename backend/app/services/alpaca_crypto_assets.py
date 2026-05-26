"""Fetch and cache Alpaca crypto asset metadata (min size, increments)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.config import settings
from app.services.alpaca_adapter import normalize_crypto_symbol
from app.services.broker_safety import broker_base_url

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] = {"assets": {}, "fetched_at": None}
_CACHE_TTL = timedelta(minutes=30)


def _base_url() -> str:
    base = (broker_base_url() or settings.alpaca_base_url or "").rstrip("/")
    if not base:
        return "https://paper-api.alpaca.markets"
    return base


def fetch_crypto_assets(*, force: bool = False) -> dict[str, dict[str, Any]]:
    """GET /v2/assets?asset_class=crypto — keyed by normalized symbol (BTC/USD)."""
    now = datetime.utcnow()
    if (
        not force
        and _CACHE.get("fetched_at")
        and (now - _CACHE["fetched_at"]) < _CACHE_TTL
        and _CACHE.get("assets")
    ):
        return _CACHE["assets"]

    if not settings.alpaca_configured:
        return _CACHE.get("assets") or {}

    url = f"{_base_url()}/v2/assets"
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                url,
                headers=headers,
                params={"asset_class": "crypto", "status": "active"},
            )
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:
        logger.warning("fetch_crypto_assets failed: %s", exc)
        return _CACHE.get("assets") or {}

    by_sym: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = normalize_crypto_symbol(str(row.get("symbol") or ""))
        if not sym:
            continue
        by_sym[sym] = {
            "symbol": sym,
            "raw_symbol": row.get("symbol"),
            "tradable": bool(row.get("tradable")),
            "status": str(row.get("status") or ""),
            "fractionable": bool(row.get("fractionable")),
            "min_order_size": _f(row.get("min_order_size")),
            "min_trade_increment": _f(row.get("min_trade_increment")),
            "price_increment": _f(row.get("price_increment")),
            "quote_currency": _quote_currency(sym, row),
        }
    _CACHE["assets"] = by_sym
    _CACHE["fetched_at"] = now
    return by_sym


def get_crypto_asset(symbol: str, *, force: bool = False) -> Optional[dict[str, Any]]:
    sym = normalize_crypto_symbol(symbol)
    assets = fetch_crypto_assets(force=force)
    return assets.get(sym)


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _quote_currency(sym: str, row: dict) -> str:
    if "/" in sym:
        return sym.split("/", 1)[1]
    return str(row.get("quote_currency") or "USD")
