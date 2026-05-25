"""Stale historical data must set date_warning and requested vs actual fields."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta

from sqlmodel import Session

from app.database import engine, init_db
from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService
from app.services.research_test_fixtures import seed_hourly_bars


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        old_end = datetime.utcnow() - timedelta(days=400)
        seed_hourly_bars(session, "ETH/USD", count=120, end_at=old_end)
        session.commit()
        hist = HistoricalDataService(session, cfg)
        bars, meta = hist.get_bars("ETH/USD", min_rows=30, lookback_days=90)
        assert bars, "expected bars from fixture"
        assert meta.get("date_warning"), f"expected date_warning, meta={meta}"
        assert meta.get("requested_start_date"), "requested_start_date required"
        assert meta.get("actual_end_date"), "actual_end_date required"
        assert meta.get("data_is_recent") is False
        print("verify_requested_vs_actual_date_warning: OK", meta.get("date_warning")[:80])


if __name__ == "__main__":
    main()
