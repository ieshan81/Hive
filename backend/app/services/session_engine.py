"""Market session engine — gates strategies by asset class and time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.services.us_market_calendar import calendar_available_for, us_market_holiday

NY = ZoneInfo("America/New_York")

STOCK_STRATEGIES = frozenset({"momentum_orb", "mean_reversion_pairs"})
CRYPTO_STRATEGIES = frozenset({"crypto_night_momentum", "crypto_push_pull"})


@dataclass
class SessionState:
    us_stock_session: str  # open, premarket, afterhours, closed
    crypto_session: str  # open (24/7)
    is_weekend: bool
    is_night_mode: bool
    stock_trading_allowed: bool
    crypto_trading_allowed: bool
    mode: str  # stock_day, crypto_night, closed
    calendar_available: bool = True
    us_stock_close_reason: str | None = None

    def to_dict(self) -> dict:
        us_display = (
            "Calendar unavailable"
            if not self.calendar_available
            else ("OPEN" if self.us_stock_session == "open" else "CLOSED")
        )
        crypto_display = "OPEN" if self.crypto_session == "open" else "CLOSED"
        return {
            "us_stock_session": self.us_stock_session,
            "crypto_session": self.crypto_session,
            "is_weekend": self.is_weekend,
            "is_night_mode": self.is_night_mode,
            "stock_trading_allowed": self.stock_trading_allowed,
            "crypto_trading_allowed": self.crypto_trading_allowed,
            "mode": self.mode,
            "calendar_available": self.calendar_available,
            "us_stock_close_reason": self.us_stock_close_reason,
            "us_stocks_display": us_display,
            "crypto_display": crypto_display,
        }


class SessionEngine:
    PREMARKET = time(4, 0)
    MARKET_OPEN = time(9, 30)
    MARKET_CLOSE = time(16, 0)
    AFTERHOURS_END = time(20, 0)

    def detect(self, now: datetime | None = None) -> SessionState:
        now = now or datetime.now(NY)
        if now.tzinfo is None:
            now = now.replace(tzinfo=NY)
        else:
            now = now.astimezone(NY)

        t = now.time()
        is_weekend = now.weekday() >= 5
        cal_ok = calendar_available_for(now.date())
        holiday, holiday_name = us_market_holiday(now.date()) if cal_ok else (False, None)
        close_reason: str | None = None

        if not cal_ok:
            us_session = "closed"
            close_reason = "Calendar unavailable"
        elif holiday:
            us_session = "closed"
            close_reason = holiday_name
        elif is_weekend:
            us_session = "closed"
            close_reason = "Weekend"
        elif t < self.PREMARKET:
            us_session = "closed"
        elif t < self.MARKET_OPEN:
            us_session = "premarket"
        elif t < self.MARKET_CLOSE:
            us_session = "open"
        elif t < self.AFTERHOURS_END:
            us_session = "afterhours"
        else:
            us_session = "closed"

        crypto_open = True  # Alpaca crypto 24/7
        is_night = us_session in ("closed", "afterhours", "premarket") or is_weekend or holiday or not cal_ok
        stock_allowed = cal_ok and us_session == "open" and not is_weekend and not holiday
        crypto_allowed = crypto_open
        if us_session == "closed" and not close_reason and not cal_ok:
            close_reason = "Calendar unavailable"
        elif us_session == "closed" and not close_reason and t >= self.MARKET_CLOSE and t < self.AFTERHOURS_END:
            close_reason = "After regular session"
        elif us_session == "closed" and not close_reason:
            close_reason = "Outside regular session"

        if stock_allowed:
            mode = "stock_day"
        elif crypto_allowed and is_night:
            mode = "crypto_night"
        else:
            mode = "closed"

        return SessionState(
            us_stock_session=us_session,
            crypto_session="open" if crypto_open else "closed",
            is_weekend=is_weekend,
            is_night_mode=is_night,
            stock_trading_allowed=stock_allowed,
            crypto_trading_allowed=crypto_allowed,
            mode=mode,
            calendar_available=cal_ok,
            us_stock_close_reason=close_reason,
        )

    def strategy_allowed(self, strategy_id: str, session: SessionState) -> bool:
        if strategy_id in STOCK_STRATEGIES:
            return session.stock_trading_allowed
        if strategy_id in CRYPTO_STRATEGIES:
            return session.crypto_trading_allowed
        return session.stock_trading_allowed or session.crypto_trading_allowed

    def asset_class_allowed(self, asset_class: str, session: SessionState) -> bool:
        if asset_class == "crypto":
            return session.crypto_trading_allowed
        return session.stock_trading_allowed
