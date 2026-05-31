"""Repeated SPREAD_WIDENED cools a symbol down so the scanner rotates to the next.

Proves:
- repeated SPREAD_WIDENED on a symbol trips an entry cooldown
- a different candidate is NOT cooled (rotation target available)
- the cooldown + counts are visible in diagnostics
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.services.spread_state_service import (
    is_entry_cooldown_active,
    record_spread_widened,
    spread_diagnostics,
)

CFG: dict = {}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_repeated_widened_cools_and_rotates() -> None:
    s = _mem()
    for _ in range(3):  # default threshold = 3
        record_spread_widened(s, CFG, "DOGE/USD")
        s.commit()

    active, ev = is_entry_cooldown_active(s, CFG, "DOGE/USD")
    assert active, ev
    # A different candidate is free to be evaluated (rotation target).
    other_active, _ = is_entry_cooldown_active(s, CFG, "SOL/USD")
    assert not other_active, "unrelated symbol must not be cooled down"
    print("spread-cooldown: 3x SPREAD_WIDENED cools DOGE; SOL still evaluable (rotation) — PASS")


def test_cooldown_visible_in_diagnostics() -> None:
    s = _mem()
    for _ in range(3):
        record_spread_widened(s, CFG, "DOGE/USD")
        s.commit()
    diag = spread_diagnostics(s, CFG)
    assert "DOGEUSD" in diag["spread_cooldown_symbols"], diag
    assert diag["spread_rotation_active"] is True, diag
    assert diag["spread_widened_count_by_symbol"].get("DOGEUSD", 0) >= 3, diag
    assert "DOGEUSD" in diag["spread_cooldown_until"], diag
    s.close()
    print("spread-cooldown: diagnostics expose count_by_symbol, cooldown_symbols/until, rotation_active — PASS")


def test_below_threshold_no_cooldown() -> None:
    s = _mem()
    record_spread_widened(s, CFG, "AVAX/USD")
    s.commit()
    active, _ = is_entry_cooldown_active(s, CFG, "AVAX/USD")
    assert not active, "single block must not cool down"
    s.close()
    print("spread-cooldown: a single SPREAD_WIDENED does not cool down (threshold respected) — PASS")


if __name__ == "__main__":
    test_repeated_widened_cools_and_rotates()
    test_cooldown_visible_in_diagnostics()
    test_below_threshold_no_cooldown()
    print("ALL PASS: verify_spread_widened_cooldown_rotation")
