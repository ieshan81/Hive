"""OHLC series for chart widgets — DB first, Alpaca fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService


def _sanitize_candle(c: dict[str, float], ref_price: float) -> dict[str, float]:
    """Clamp corrupt wicks so charts autoscale to real price action."""
    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    if ref_price <= 0:
        ref_price = cl or o or 1.0
    max_wick_pct = 0.06
    body_hi = max(o, cl)
    body_lo = min(o, cl)
    cap_hi = max(body_hi * (1 + max_wick_pct), ref_price * 1.08)
    cap_lo = min(body_lo * (1 - max_wick_pct), ref_price * 0.92)
    if h > cap_hi:
        h = cap_hi
    if l < cap_lo:
        l = cap_lo
    if h < body_hi:
        h = body_hi
    if l > body_lo:
        l = body_lo
    return {"open": o, "high": h, "low": l, "close": cl, "volume": c.get("volume", 0)}


def ohlc_series(
    session: Session,
    symbol: str,
    *,
    timeframe: str = "5Min",
    limit: int = 120,
    config: Optional[dict] = None,
) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    hist = HistoricalDataService(session, cfg)
    bars, meta = hist.get_bars(
        symbol,
        timeframe=timeframe,
        min_rows=min(30, limit // 2),
        lookback_days=14,
        max_staleness_hours=96,
        force_refresh=False,
    )
    if not bars:
        return {
            "status": "empty",
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": [],
            "message": meta.get("error") or "No bars — run market data refresh",
        }
    tail = bars[-limit:]
    closes = [float(b.get("close") or b.get("open") or 0) for b in tail if b.get("close") or b.get("open")]
    ref_price = sorted(closes)[len(closes) // 2] if closes else 0.0
    candles = []
    for b in tail:
        ts = b.get("timestamp")
        if isinstance(ts, datetime):
            t = int(ts.timestamp())
        else:
            try:
                t = int(datetime.fromisoformat(str(ts).replace("Z", "")).timestamp())
            except Exception:
                t = int(datetime.utcnow().timestamp())
        raw = {
            "time": t,
            "open": float(b.get("open") or b.get("close") or 0),
            "high": float(b.get("high") or b.get("close") or 0),
            "low": float(b.get("low") or b.get("close") or 0),
            "close": float(b.get("close") or 0),
            "volume": float(b.get("volume") or 0),
        }
        candles.append(_sanitize_candle(raw, ref_price))
    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles,
        "source": meta.get("source", "database"),
        "bar_count": len(candles),
        "last_close": candles[-1]["close"] if candles else None,
    }
