"""Journal/activity wording must not claim a fill is pending when no order was submitted.

Proves the tick summary:
- says 'order submitted' only when an order actually went to the broker
- when a candidate was approved by the gate but NO order was submitted, it says the
  order was blocked before submission (with the reason) and never 'awaiting fill'
- surfaces the adaptive-budget block reason in plain language
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.push_pull_scan_service import _plain_tick_summary


def test_approved_but_no_order_is_not_awaiting_fill() -> None:
    s = _plain_tick_summary(
        symbols_scanned=20, active=5, blocked=2, fresh=18, stale=0, eligible_strats=3,
        push_signals=4, approved=1, skipped=3, orders=0,
        reasons=Counter({"adaptive_budget_blocked": 1}),
    )
    assert "awaiting" not in s.lower(), s
    assert "no order submitted" in s.lower(), s
    assert "adaptive budget blocked" in s.lower(), s
    print("wording: approved+no-order -> 'no order submitted (blocked...)' not 'awaiting fill' — PASS")


def test_order_submitted_wording() -> None:
    s = _plain_tick_summary(
        symbols_scanned=20, active=5, blocked=2, fresh=18, stale=0, eligible_strats=3,
        push_signals=4, approved=1, skipped=3, orders=1, reasons=Counter(),
    )
    assert "order submitted" in s.lower() and "awaiting" not in s.lower(), s
    print("wording: order submitted stated only when an order went to broker — PASS")


def test_no_candidate_wording() -> None:
    s = _plain_tick_summary(
        symbols_scanned=20, active=0, blocked=20, fresh=18, stale=0, eligible_strats=0,
        push_signals=0, approved=0, skipped=0, orders=0,
        reasons=Counter({"no_push_signal": 12, "spread_too_wide": 8}),
    )
    assert "awaiting" not in s.lower(), s
    print("wording: no-candidate tick never claims a pending fill — PASS")


if __name__ == "__main__":
    test_approved_but_no_order_is_not_awaiting_fill()
    test_order_submitted_wording()
    test_no_candidate_wording()
    print("ALL PASS: verify_journal_wording_accuracy")
