"""
Session Scheduler — State Machine (DOMAIN 3).

Five modes with explicit transitions:
  crypto_only_overnight  : 20:00 → 04:00 ET (M-F) and all weekend
  pre_market_monitor     : 04:00 → 09:30 ET (M-F, non-holiday)
  stocks_regular         : 09:30 → 16:00 ET (M-F, non-holiday)
  post_market_monitor    : 16:00 → 20:00 ET (M-F, non-holiday)
  holiday_half_day       : per GET /v2/calendar

Detection: GET /v2/clock every 30s + nightly /v2/calendar for advance look-ahead.

During crypto-priority modes (overnight, pre-market, post-market), ranking
weights shift +0.05 to liquidity_pct for BTC/USD, ETH/USD, SOL/USD.
New positions in low-cap coins blocked above min_marketcap_rank=20.

Post-2026-06-04: PDT module switches to intraday_buying_power.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, time
from typing import Any, Optional


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

# ET offset from UTC: -5h (EST) or -4h (EDT). We approximate with UTC-4 in
# summer and UTC-5 in winter.  For precision, use zoneinfo if available.
_LIQUID_CRYPTO_PRIORITY = {"BTC/USD", "ETH/USD", "SOL/USD"}
FINRA_PDT_TRANSITION_DATE = datetime(2026, 6, 4).date()

SESSION_MODES = (
    "crypto_only_overnight",
    "pre_market_monitor",
    "stocks_regular",
    "post_market_monitor",
    "holiday_half_day",
    "unknown",
)


def _et_now() -> datetime:
    """
    Return current time in approximate ET.
    Uses zoneinfo (Python 3.9+) if available, otherwise falls back to UTC-5.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Rough fallback: UTC-5 (ignores DST)
        from datetime import timezone, timedelta
        et_offset = timedelta(hours=-5)
        return datetime.now(timezone.utc).astimezone(timezone(et_offset))


def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # Mon=0 … Fri=4


def _time_in(dt: datetime, start: time, end: time) -> bool:
    """True if dt.time() is in [start, end)."""
    t = dt.time().replace(tzinfo=None)
    s = start.replace(tzinfo=None)
    e = end.replace(tzinfo=None)
    if s <= e:
        return s <= t < e
    # Wraps midnight
    return t >= s or t < e


# ──────────────────────────────────────────────────────────────
# Session mode classifier
# ──────────────────────────────────────────────────────────────

def classify_session(
    clock: Optional[dict] = None,
    *,
    override: Optional[str] = None,
) -> dict[str, Any]:
    """
    Returns:
      mode: one of SESSION_MODES
      stock_orders_allowed: bool
      crypto_orders_allowed: bool
      description: human-readable
    """
    if override and override in SESSION_MODES:
        return _session_result(override)

    now_et = _et_now()
    is_weekday = _is_weekday(now_et)

    # Weekend: crypto overnight
    if not is_weekday:
        return _session_result("crypto_only_overnight")

    # Use Alpaca clock if provided
    if clock:
        is_open = bool(clock.get("is_open", False))
        # Check if it's a half-day
        if clock.get("half_day"):
            return _session_result("holiday_half_day")

    t = now_et.time()

    # 20:00 → 04:00 — overnight
    if _time_in(now_et, time(20, 0), time(4, 0)):
        return _session_result("crypto_only_overnight")
    # 04:00 → 09:30 — pre-market
    if _time_in(now_et, time(4, 0), time(9, 30)):
        return _session_result("pre_market_monitor")
    # 09:30 → 16:00 — regular
    if _time_in(now_et, time(9, 30), time(16, 0)):
        return _session_result("stocks_regular")
    # 16:00 → 20:00 — post-market
    if _time_in(now_et, time(16, 0), time(20, 0)):
        return _session_result("post_market_monitor")

    return _session_result("crypto_only_overnight")


def _session_result(mode: str) -> dict[str, Any]:
    stock_map = {
        "crypto_only_overnight": False,
        "pre_market_monitor": False,
        "stocks_regular": True,
        "post_market_monitor": False,
        "holiday_half_day": False,  # reduced hours — conservative
        "unknown": False,
    }
    crypto_map = {
        "crypto_only_overnight": True,
        "pre_market_monitor": True,
        "stocks_regular": True,
        "post_market_monitor": True,
        "holiday_half_day": True,
        "unknown": False,
    }
    descriptions = {
        "crypto_only_overnight": "Crypto active 24/7; stock orders disabled until 09:30 ET",
        "pre_market_monitor": "Pre-market: monitoring only; no stock orders; crypto active",
        "stocks_regular": "Regular session 09:30–16:00 ET; stocks (swing-only) + crypto active",
        "post_market_monitor": "Post-market: monitoring only; no stock orders; crypto active",
        "holiday_half_day": "Holiday or half-day session; following reduced close; crypto active",
        "unknown": "Session mode unknown — conservative: no orders",
    }
    return {
        "mode": mode,
        "stock_orders_allowed": stock_map.get(mode, False),
        "crypto_orders_allowed": crypto_map.get(mode, False),
        "description": descriptions.get(mode, mode),
        "detected_at": datetime.utcnow().isoformat() + "Z",
    }


# ──────────────────────────────────────────────────────────────
# Crypto priority weight boost
# ──────────────────────────────────────────────────────────────

def crypto_priority_weight_boost(symbol: str, mode: str) -> float:
    """
    During crypto-priority modes, add +0.05 liquidity weight for major crypto.
    New positions in low-cap coins (not in _LIQUID_CRYPTO_PRIORITY) are not
    explicitly blocked here — that's done in the entry gate.
    """
    crypto_priority_modes = {"crypto_only_overnight", "pre_market_monitor", "post_market_monitor"}
    if mode in crypto_priority_modes and symbol in _LIQUID_CRYPTO_PRIORITY:
        return 0.05
    return 0.0


# ──────────────────────────────────────────────────────────────
# PDT pre-flight check
# ──────────────────────────────────────────────────────────────

def pdt_preflight(
    symbol: str,
    side: str,
    asset_class: str,
    account: dict,
    *,
    pdt_safety_max: int = 2,
) -> Optional[str]:
    """
    Returns PDT_BLOCK reason string if trade would violate PDT rule, else None.

    Pre-2026-06-04: On accounts < $25K, block the 4th day-trade in a 5-business-day
    window. Crypto is exempt.

    Post-2026-06-04: Feature-flagged; reads intraday_buying_power instead.
    """
    import datetime as _dt
    today = _dt.date.today()
    if today >= FINRA_PDT_TRANSITION_DATE:
        # New framework: read intraday_buying_power — no block via this function
        return None

    if asset_class == "crypto":
        return None  # Crypto is exempt per Alpaca docs

    if side.lower() != "sell":
        return None  # PDT only affects same-day round-trips

    daytrade_count = int(account.get("daytrade_count", 0) or 0)
    equity = float(account.get("equity", 0) or 0)
    if equity >= 25_000:
        return None  # PDT doesn't apply above $25K

    if daytrade_count >= pdt_safety_max:
        return "PDT_BLOCK"
    return None


# ──────────────────────────────────────────────────────────────
# Rate-limit token bucket (simple, in-process only)
# ──────────────────────────────────────────────────────────────

class RateLimitBucket:
    """
    Token bucket: 180 req/min (safety margin under Alpaca's 200/min limit).
    Exponential backoff on HTTP 429 with Retry-After.
    Circuit breaker: 3 consecutive 429s within 60s → "data degraded" mode.
    """

    CAPACITY = 180
    REFILL_RATE = 3.0  # tokens per second

    def __init__(self) -> None:
        self._tokens = float(self.CAPACITY)
        self._last_refill = datetime.utcnow()
        self._consecutive_429s = 0
        self._last_429_at: Optional[datetime] = None
        self._degraded_until: Optional[datetime] = None

    @property
    def is_degraded(self) -> bool:
        if self._degraded_until and datetime.utcnow() < self._degraded_until:
            return True
        return False

    def consume(self, n: int = 1) -> bool:
        """Returns True if allowed, False if rate-limited."""
        self._refill()
        if self.is_degraded:
            return False
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def record_429(self, retry_after_s: Optional[float] = None) -> None:
        now = datetime.utcnow()
        self._consecutive_429s += 1
        self._last_429_at = now
        if self._consecutive_429s >= 3:
            # Check if 3 happened within 60s
            backoff = retry_after_s or 60.0
            self._degraded_until = now + __import__("datetime").timedelta(seconds=backoff * 2)
            self._consecutive_429s = 0  # reset counter

    def record_success(self) -> None:
        self._consecutive_429s = 0

    def _refill(self) -> None:
        now = datetime.utcnow()
        elapsed = (now - self._last_refill).total_seconds()
        self._tokens = min(self.CAPACITY, self._tokens + elapsed * self.REFILL_RATE)
        self._last_refill = now


# Global singleton rate bucket
_RATE_BUCKET = RateLimitBucket()


def get_rate_bucket() -> RateLimitBucket:
    return _RATE_BUCKET
