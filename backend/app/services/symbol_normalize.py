"""Symbol normalization — DOGE/USD ↔ DOGEUSD."""

from __future__ import annotations


def broker_symbol(display: str) -> str:
    """Alpaca-style symbol without slash."""
    return display.replace("/", "").upper()


def display_symbol(broker: str) -> str:
    s = broker.upper()
    if "/" in s:
        return s
    if s.endswith("USD") and len(s) > 3:
        base = s[:-3]
        return f"{base}/USD"
    return s


def symbol_variants(symbol: str) -> list[str]:
    s = symbol.strip()
    variants = {s, s.upper(), broker_symbol(s), display_symbol(s)}
    if "/" in s:
        variants.add(broker_symbol(s))
    else:
        variants.add(display_symbol(s))
    return [v for v in variants if v]


def symbols_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    va = {v.upper() for v in symbol_variants(a)}
    vb = {v.upper() for v in symbol_variants(b)}
    return bool(va & vb)
