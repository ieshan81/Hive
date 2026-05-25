"""Memorial Day 2026-05-25: U.S. stocks CLOSED."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.session_engine import SessionEngine
from app.services.us_market_calendar import calendar_available_for, us_market_holiday


def main() -> None:
    d = date(2026, 5, 25)
    is_hol, name = us_market_holiday(d)
    assert is_hol and name == "Memorial Day", (is_hol, name)
    assert calendar_available_for(d)

    noon = datetime(2026, 5, 25, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    st = SessionEngine().detect(noon)
    assert st.us_stock_session == "closed", st.us_stock_session
    assert st.stock_trading_allowed is False
    assert st.crypto_session == "open"
    assert st.crypto_trading_allowed is True
    assert "Memorial Day" in (st.us_stock_close_reason or "")
    assert st.calendar_available is True

    print("ALL_MEMORIAL_DAY_CHECKS_PASSED")


if __name__ == "__main__":
    main()
