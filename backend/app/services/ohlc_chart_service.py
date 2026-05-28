"""OHLC series for chart widgets — DB first, Alpaca fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService


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
        candles.append(
            {
                "time": t,
                "open": float(b.get("open") or b.get("close") or 0),
                "high": float(b.get("high") or b.get("close") or 0),
                "low": float(b.get("low") or b.get("close") or 0),
                "close": float(b.get("close") or 0),
                "volume": float(b.get("volume") or 0),
            }
        )
    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles,
        "source": meta.get("source", "database"),
        "bar_count": len(candles),
        "last_close": candles[-1]["close"] if candles else None,
    }
