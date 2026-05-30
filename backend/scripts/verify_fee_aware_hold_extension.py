"""Fee-aware max-hold: don't exit a fee-uncovered position on the clock alone.

Proves OpenPositionReviewService._fee_aware_max_hold:
- fee NOT covered + within extension window -> EXTEND (max_hold_extended_fee_not_covered)
- net positive after round-trip cost -> EXIT (max_hold_exit_fee_covered)
- past the absolute time ceiling -> EXIT even if fee not covered (emergency ceiling)
- past the hard ceiling -> EXIT even with a small profit (never extends forever)

Stop-loss / invalidation / loss-band exits are evaluated in review_position AFTER this
and override to exit immediately — structurally unaffected by the extension path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.open_position_review_service import OpenPositionReviewService


class _Pos:
    def __init__(self, qty, mark, entry, upl):
        self.qty = qty
        self.current_price = mark
        self.avg_entry_price = entry
        self.unrealized_pl = upl


class _Svc:
    """Minimal holder exposing pl_cfg + the bound method (no DB / no full service init)."""

    pl_cfg: dict = {}
    _fee_aware_max_hold = OpenPositionReviewService._fee_aware_max_hold


EFFECTIVE_MAX = 30.0  # minutes; hard ceiling = 30 + 3*60 = 210


def test_extend_when_fee_not_covered() -> None:
    # notional 100 * 40bps = $0.40 cost; upl $0.10 -> net -0.30 -> extend
    action, reason, status, ev = _Svc()._fee_aware_max_hold(_Pos(1.0, 100.0, 100.0, 0.10), 60.0, EFFECTIVE_MAX)
    assert action == "hold" and reason == "max_hold_extended_fee_not_covered", (action, reason, ev)
    print("fee-aware: fee-not-covered + valid -> EXTEND hold — PASS")


def test_exit_when_fee_covered() -> None:
    action, reason, status, ev = _Svc()._fee_aware_max_hold(_Pos(1.0, 100.0, 100.0, 5.0), 60.0, EFFECTIVE_MAX)
    assert action == "exit_recommended" and reason == "max_hold_exit_fee_covered", (action, reason, ev)
    print("fee-aware: net-positive after cost -> EXIT (fee covered) — PASS")


def test_exit_at_absolute_ceiling_even_if_fee_uncovered() -> None:
    # 5000 min >> absolute ceiling (72h=4320) -> exit regardless of fee
    action, reason, status, ev = _Svc()._fee_aware_max_hold(_Pos(1.0, 100.0, 100.0, 0.10), 5000.0, EFFECTIVE_MAX)
    assert action == "exit_recommended" and reason == "max_hold_exit_absolute_ceiling", (action, reason, ev)
    print("fee-aware: past absolute ceiling -> EXIT (emergency, no more extension) — PASS")


def test_never_extends_past_hard_ceiling() -> None:
    # 300 min > hard ceiling 210; small profit doesn't matter -> must exit, never extend
    action, reason, status, ev = _Svc()._fee_aware_max_hold(_Pos(1.0, 100.0, 100.0, 0.05), 300.0, EFFECTIVE_MAX)
    assert action == "exit_recommended", (action, reason, ev)
    print("fee-aware: past hard ceiling -> EXIT (never extends forever) — PASS")


if __name__ == "__main__":
    test_extend_when_fee_not_covered()
    test_exit_when_fee_covered()
    test_exit_at_absolute_ceiling_even_if_fee_uncovered()
    test_never_extends_past_hard_ceiling()
    print("ALL PASS: verify_fee_aware_hold_extension")
