"""Synthetic bar fixtures for research verification (offline, no broker)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session

from app.database import HistoricalBar


def seed_hourly_bars(
    session: Session,
    symbol: str,
    *,
    count: int = 200,
    trend: float = 0.0,
    end_at: datetime | None = None,
) -> None:
    end = end_at or datetime.utcnow()
    for i in range(count):
        ts = end - timedelta(hours=count - i)
        base = 100.0 + trend * i
        session.add(
            HistoricalBar(
                symbol=symbol,
                asset_class="crypto",
                timeframe="1Hour",
                timestamp=ts,
                open=base,
                high=base + 1,
                low=base - 1,
                close=base + 0.2,
                volume=1000.0,
                source="test_fixture",
                synthetic=True,
            )
        )
    session.flush()
