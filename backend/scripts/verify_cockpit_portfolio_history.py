"""Crash-safe portfolio history / timestamp resolution for the cockpit.

Proves:
- safe_record_timestamp walks the fallback chain (created_at -> opened_at -> ... )
  and returns None (never raises) when every field is missing
- a row whose created_at is None still resolves via a later field
- build_equity_curve returns a non-empty, time-sorted equity curve with drawdown
  and never crashes on rows with missing timestamps
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.timestamp_safety import (
    build_equity_curve,
    safe_record_timestamp,
    safe_timestamp_iso,
)


def test_fallback_chain() -> None:
    base = datetime(2026, 5, 30, 12, 0, 0)
    # created_at missing -> falls back to opened_at
    assert safe_record_timestamp({"created_at": None, "opened_at": base}) == base
    # only an order-time present
    assert safe_record_timestamp({"filled_at": base}) == base
    # ISO string tolerated (with Z)
    assert safe_record_timestamp({"created_at": "2026-05-30T12:00:00Z"}) == base
    # nothing present -> None, no crash
    assert safe_record_timestamp({"foo": 1}) is None
    assert safe_timestamp_iso({"foo": 1}) is None
    print("portfolio-history: timestamp fallback chain resolves / degrades safely — PASS")


def test_equity_curve_nonempty_and_sorted() -> None:
    t0 = datetime(2026, 5, 30, 9, 0, 0)
    trades = [
        {"created_at": t0 + timedelta(hours=2), "realized_pnl": -1.0},   # out of order on purpose
        {"created_at": t0, "realized_pnl": 3.0},
        {"opened_at": t0 + timedelta(hours=1), "pnl": 2.0},              # created_at missing -> opened_at
        {"realized_pnl": 5.0},                                          # no timestamp -> skipped
    ]
    curve = build_equity_curve(trades, starting_equity=100.0)
    assert curve["point_count"] == 3, curve
    assert curve["skipped_no_timestamp"] == 1, curve
    ts = [p["t"] for p in curve["points"]]
    assert ts == sorted(ts), curve  # time-sorted
    # 100 + 3 + 2 - 1 = 104
    assert curve["current_equity"] == 104.0, curve
    assert curve["max_drawdown_pct"] >= 0.0, curve
    print("portfolio-history: equity curve non-empty, sorted, drawdown computed — PASS")


def test_no_crash_on_all_none() -> None:
    curve = build_equity_curve([{"x": 1}, {"y": 2}], starting_equity=50.0)
    assert curve["point_count"] == 0 and curve["current_equity"] == 50.0, curve
    print("portfolio-history: all-missing-timestamp input does not crash — PASS")


if __name__ == "__main__":
    test_fallback_chain()
    test_equity_curve_nonempty_and_sorted()
    test_no_crash_on_all_none()
    print("ALL PASS: verify_cockpit_portfolio_history")
