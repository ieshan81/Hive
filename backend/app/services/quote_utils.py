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
