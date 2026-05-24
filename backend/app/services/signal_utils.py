"""Signal classification helpers."""

from __future__ import annotations

from app.database import StrategySignal

TRADEABLE_TYPES = frozenset({"entry", "exit"})


def is_tradeable_signal(sig: StrategySignal) -> bool:
    st = (sig.signal_type or "entry").lower()
    if st == "observation":
        return False
    if st in TRADEABLE_TYPES and sig.signal not in ("hold", "observe"):
        return True
    return sig.signal in ("buy", "sell") and st != "observation"
