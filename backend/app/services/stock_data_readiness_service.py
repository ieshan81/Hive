"""Read-only stock market-data readiness probe.

Per-symbol truth about whether stock bars are actually available from the configured Alpaca
feed (IEX on Basic plans), with the exact blocker when they are not. Submits no order, stores
nothing, never enables live. Used by GET /api/stock-data/readiness, the engine map, and the
diagnostic bundle so a 0-bar stock feed is surfaced clearly instead of silently failing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

# Core symbols the validation run cares about (the ones that showed "Insufficient bars: 0").
DEFAULT_STOCK_SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"]

# Truthful blocker codes (no fake "scanned ok" when bars are missing).
BLOCKER_CODES = {
    "STOCK_DATA_UNAVAILABLE",
    "STOCK_FEED_UNSUPPORTED",
    "STOCK_BARS_TOO_RECENT",
    "STOCK_MARKET_CLOSED",
    "STOCK_SUBSCRIPTION_LIMIT",
    "INSUFFICIENT_STOCK_BARS",
}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _classify(bars_n: int, market_open: bool, err: Optional[str], min_bars: int) -> Optional[str]:
    """Return a blocker code, or None when the symbol is ready."""
    if err:
        low = err.lower()
        # Subscription wording first (the canonical Basic-plan "subscription does not permit
        # querying recent SIP data" error), then feed-access wording, then recency.
        if any(t in low for t in ("subscription", "not permitted", "permit")):
            return "STOCK_SUBSCRIPTION_LIMIT"
        if any(t in low for t in ("sip", "feed", "not authorized", "403", "forbidden")):
            return "STOCK_FEED_UNSUPPORTED"
        if "recent" in low or "too new" in low:
            return "STOCK_BARS_TOO_RECENT"
        return "STOCK_DATA_UNAVAILABLE"
    if bars_n <= 0:
        return "STOCK_MARKET_CLOSED" if not market_open else "STOCK_DATA_UNAVAILABLE"
    if bars_n < min_bars:
        return "INSUFFICIENT_STOCK_BARS"
    return None


def _next_action(code: Optional[str], feed: str) -> str:
    return {
        None: "Stock bars available — scanner can score this symbol.",
        "STOCK_MARKET_CLOSED": "U.S. market closed — stocks resume at next open; crypto continues 24/7.",
        "STOCK_SUBSCRIPTION_LIMIT": "Use feed=iex on Basic plan, or upgrade the Alpaca market-data subscription for SIP.",
        "STOCK_FEED_UNSUPPORTED": f"Feed '{feed}' not authorized — switch to iex or enable the SIP subscription.",
        "STOCK_BARS_TOO_RECENT": "Increase alpaca_stock_data_delay_minutes so the request end-time is older.",
        "INSUFFICIENT_STOCK_BARS": "Backfill more history / widen the lookback window before scoring.",
        "STOCK_DATA_UNAVAILABLE": "Verify Alpaca data API status and feed/delay config.",
    }.get(code, "Review stock data feed configuration.")


def stock_data_readiness(
    session: Session,
    config: Optional[dict] = None,
    *,
    symbols: Optional[list[str]] = None,
    timeframe: str = "5Min",
    min_bars: int = 2,
    probe_limit: int = 60,
) -> dict[str, Any]:
    from app.services.alpaca_adapter import (
        AlpacaAdapter,
        configured_stock_feed_name,
        stock_data_delay_minutes,
    )

    feed = configured_stock_feed_name()
    delay = stock_data_delay_minutes()

    # Market session (read-only) — resilient if SessionEngine import/detect fails.
    market_open = False
    market_session = "unknown"
    try:
        from app.services.session_engine import SessionEngine

        sess = SessionEngine().detect()
        market_open = bool(getattr(sess, "stock_trading_allowed", False))
        market_session = getattr(sess, "us_stock_session", None) or ("open" if market_open else "closed")
    except Exception:
        pass

    syms = [s.strip().upper() for s in (symbols or DEFAULT_STOCK_SYMBOLS) if s and s.strip()]
    adapter = AlpacaAdapter(session)
    configured = bool(getattr(adapter, "configured", False))

    per_symbol: list[dict[str, Any]] = []
    ready_count = 0
    any_bars = False
    any_feed_error = False
    for sym in syms:
        bars_n = 0
        latest = None
        err: Optional[str] = None
        if not configured:
            err = "alpaca_not_configured"
        else:
            try:
                bars = adapter.get_bars(sym, timeframe=timeframe, limit=probe_limit, asset_class="stock")
                bars_n = len(bars)
                if bars:
                    latest = bars[-1].get("timestamp")
                    any_bars = True
            except Exception as exc:  # read-only probe — never raises out
                err = str(exc)[:200]
        code = _classify(bars_n, market_open, err, min_bars)
        if code in ("STOCK_SUBSCRIPTION_LIMIT", "STOCK_FEED_UNSUPPORTED"):
            any_feed_error = True
        if code is None:
            ready_count += 1
        per_symbol.append(
            {
                "symbol": sym,
                "requested_feed": feed,
                "bars_returned": bars_n,
                "latest_bar_time": latest,
                "market_session": market_session,
                "data_delay_minutes": delay,
                "readiness_status": "ready" if code is None else "blocked",
                "failure_reason": code,
                "next_action": _next_action(code, feed),
            }
        )

    # Infer subscription level from observed behaviour (no secrets, no account call).
    if any_bars:
        subscription = f"{feed}_active"
    elif any_feed_error:
        subscription = "basic_plan_sip_unsupported"
    elif not market_open:
        subscription = "unknown_market_closed"
    elif not configured:
        subscription = "not_configured"
    else:
        subscription = "unknown"

    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "stock_data_feed": feed,
        "stock_data_delay_minutes": delay,
        "stock_subscription_level_detected": subscription,
        "market_session": market_session,
        "market_open": market_open,
        "symbols_total": len(syms),
        "symbols_ready": ready_count,
        "symbols_blocked": len(syms) - ready_count,
        "all_blocked": ready_count == 0 and len(syms) > 0,
        "symbols": per_symbol,
        # Crypto is a separate 24/7 lane and is unaffected by stock data readiness.
        "crypto_independent": True,
        "live_trading_locked": True,
        "orders_authority": "none",
    }
