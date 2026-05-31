"""Exit spread policy is separate from entry spread: exits are never trapped.

Proves:
- an entry (buy) is classified as not-an-exit, so the strict entry SPREAD_WIDENED gate stays
- a stop-loss / hard exit bypasses the spread gate entirely (never trapped, even at 5% spread)
- a soft (time-stop) exit is allowed within a widened tolerance, then delays, then ESCALATES
  after repeated failed attempts and freezes new entries; resolving the exit clears the freeze
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.services.spread_state_service import (
    classify_exit_urgency,
    clear_failed_exit,
    evaluate_exit_spread,
    unresolved_exit_freeze,
)

CFG: dict = {}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_entry_vs_exit_classification() -> None:
    assert classify_exit_urgency({}, "entry", "buy") is None  # entry keeps strict gate
    assert classify_exit_urgency({"exit_reason": "stop_loss"}, "exit", "sell") == "hard"
    assert classify_exit_urgency({"exit_reason": "invalidation"}, "exit", "sell") == "hard"
    assert classify_exit_urgency({"exit_reason": "max_hold"}, "exit", "sell") == "soft"
    print("exit-spread: entry -> None (strict gate kept); stop/invalidation -> hard; max_hold -> soft — PASS")


def test_hard_exit_never_trapped() -> None:
    s = _mem()
    dec = evaluate_exit_spread(s, CFG, symbol="LTC/USD", urgency="hard", spread=0.05, max_spread=0.005)
    assert dec.action == "allow" and dec.code == "EXIT_SPREAD_BYPASS_HARD", dec
    print("exit-spread: stop-loss/hard exit bypasses spread gate at 5% spread (never trapped) — PASS")


def test_soft_exit_delays_then_escalates_then_clears() -> None:
    s = _mem()
    # Within 3x tolerance (0.005*3 = 0.015) -> allowed immediately.
    d0 = evaluate_exit_spread(s, CFG, symbol="LTC/USD", urgency="soft", spread=0.012, max_spread=0.005)
    assert d0.action == "allow", d0

    actions = []
    for _ in range(3):  # beyond tolerance; escalates at the 3rd attempt
        d = evaluate_exit_spread(s, CFG, symbol="LTC/USD", urgency="soft", spread=0.05, max_spread=0.005)
        s.commit()
        actions.append(d.action)
    assert actions[0] == "delay" and actions[-1] == "escalate", actions

    frozen, syms = unresolved_exit_freeze(s, CFG)
    assert frozen and "LTCUSD" in syms, (frozen, syms)

    clear_failed_exit(s, "LTC/USD")
    s.commit()
    frozen2, _ = unresolved_exit_freeze(s, CFG)
    assert not frozen2, "freeze should clear once the exit resolves"
    s.close()
    print(f"exit-spread: soft exit delay->escalate {actions}, froze entries, cleared on resolve — PASS")


if __name__ == "__main__":
    test_entry_vs_exit_classification()
    test_hard_exit_never_trapped()
    test_soft_exit_delays_then_escalates_then_clears()
    print("ALL PASS: verify_exit_spread_escalation")
