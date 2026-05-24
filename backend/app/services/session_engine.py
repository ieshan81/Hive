"""Market session engine — gates strategies by asset class and time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


@dataclass
class SessionState:
    us_stock_session: str  # open, premarket, afterhours, closed
    crypto_session: str  # open (24/7)
    is_weekend: bool
    is_night_mode: bool
    stock_trading_allowed: bool
    crypto_trading_allowed: bool
    mode: str  # stock_day, crypto_night, closed

    def to_dict(self) -> dict:
        return {
            "us_stock_session": self.us_stock_session,
            "crypto_session": self.crypto_session,
            "is_weekend": self.is_weekend,
            "is_night_mode": self.is_night_mode,
            "stock_trading_allowed": self.stock_trading_allowed,
            "crypto_trading_allowed": self.crypto_trading_allowed,
            "mode": self.mode,
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

        if is_weekend:
            us_session = "closed"
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
        is_night = us_session in ("closed", "afterhours", "premarket") or is_weekend
        stock_allowed = us_session == "open" and not is_weekend
        crypto_allowed = crypto_open

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
        )

    def asset_class_allowed(self, asset_class: str, session: SessionState) -> bool:
        if asset_class == "crypto":
            return session.crypto_trading_allowed
        return session.stock_trading_allowed
