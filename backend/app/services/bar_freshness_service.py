"""Bar/quote freshness gates — stale data must not drive paper entries."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService, _parse_ts


# Push-pull entries require recent 5Min bars (not months-old research data).
MAX_BAR_STALENESS_HOURS = 48


class BarFreshnessService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.hist = HistoricalDataService(session, self.config)

    def check(self, symbol: str, timeframe: str = "5Min") -> dict[str, Any]:
        bars, meta = self.hist.get_bars(
            symbol,
            timeframe=timeframe,
            min_rows=10,
            lookback_days=3,
            max_staleness_hours=MAX_BAR_STALENESS_HOURS,
            force_refresh=False,
        )
        if not bars:
            return {
                "fresh": False,
                "executable": False,
                "bar_freshness": "stale",
                "quote_freshness": "unknown",
                "last_bar_at": None,
                "staleness_hours": None,
                "reason": "data_stale",
                "plain": "Price data stale — no recent bars",
                "meta": meta,
            }

        last_ts = _parse_ts(bars[-1]["timestamp"])
        age_h = (datetime.utcnow() - last_ts).total_seconds() / 3600.0
        staleness_days = meta.get("data_staleness_days")
        if staleness_days is not None and staleness_days > 3:
            age_h = max(age_h, float(staleness_days) * 24)

        fresh = age_h <= MAX_BAR_STALENESS_HOURS
        return {
            "fresh": fresh,
            "executable": fresh,
            "bar_freshness": "fresh" if fresh else "stale",
            "quote_freshness": "fresh" if fresh else "stale",
            "last_bar_at": last_ts.isoformat() + "Z",
            "staleness_hours": round(age_h, 1),
            "reason": None if fresh else "data_stale",
            "plain": "Bars fresh" if fresh else f"Data stale — last bar {round(age_h, 0)}h ago",
            "meta": meta,
            "bar_count": len(bars),
        }
