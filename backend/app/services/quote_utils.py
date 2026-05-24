"""Shared quote/spread helpers — single source of truth for spread math."""

from __future__ import annotations

from typing import Optional


def normalize_prices(bid: float, ask: float, reference_price: Optional[float] = None) -> tuple[float, float]:
    """Correct cent/dollar mismatches using a reference price (e.g. last bar close)."""
    if reference_price is None or reference_price <= 0:
        return bid, ask
    mid = (bid + ask) / 2
    if mid <= 0:
        return bid, ask
    ratio = mid / reference_price
    if ratio > 5:
        return bid / 100.0, ask / 100.0
    if ratio < 0.05:
        return bid * 100.0, ask * 100.0
    return bid, ask


def spread_from_bid_ask(bid: float | None, ask: float | None) -> tuple[float | None, str]:
    """
    Compute spread from bid/ask.
    Returns (spread_pct_decimal, spread_display).
    spread_pct_decimal is e.g. 0.00095 for 0.095%.
    """
    if bid is None or ask is None:
        return None, "No quote"
    if bid <= 0 or ask <= 0:
        return None, "Invalid quote"
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None, "Invalid quote"
    spread_pct = (ask - bid) / mid
    return spread_pct, f"{spread_pct * 100:.3f}%"


def eligibility_from_spread(
    spread_pct: float | None,
    max_spread: float,
    tradable: bool,
    quote_label: str,
) -> str:
    if not tradable:
        return "blocked"
    if quote_label in ("No quote", "Invalid quote") or spread_pct is None:
        return "unknown"
    if spread_pct > max_spread:
        return "blocked"
    if spread_pct > max_spread * 0.6:
        return "caution"
    return "eligible"


def liquidity_from_volume(volume: float | None) -> float | None:
    if volume is None or volume <= 0:
        return None
    import math

    return min(100.0, math.log10(volume + 1) * 20)


def volatility_score_from_bars(bars: list[dict]) -> float | None:
    if len(bars) < 5:
        return None
    closes = [b["close"] for b in bars]
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    from app.services import quant_math

    vol = quant_math.volatility(returns)
    if vol is None:
        return None
    return round(min(100.0, vol * 2000), 2)


def spread_score(spread_pct: float | None, max_spread: float) -> float | None:
    if spread_pct is None:
        return None
    if spread_pct <= 0:
        return 100.0
    return round(max(0.0, min(100.0, (1.0 - spread_pct / max_spread) * 100)), 2)
