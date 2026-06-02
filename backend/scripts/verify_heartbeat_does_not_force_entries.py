"""The fast heartbeat manages exits every tick but NEVER forces a new entry.

- HeartbeatService never reports force_entries; exits managed every tick.
- On non-decision ticks, entries are blocked (HEARTBEAT_ONLY_BLOCKER); only the slower decision
  loop cadence may consider entries.
- The training loop injects the additive entry gate AND runs exits BEFORE entries (static proof).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.database  # noqa: F401,E402
from app.services.heartbeat_service import (  # noqa: E402
    HEARTBEAT_ONLY_BLOCKER,
    NO_BACKTEST_EVIDENCE_BLOCKER,
    HeartbeatService,
)

CFG = {"autonomous_paper_learning": {"heartbeat": {
    "enabled": True, "manage_exits_every_tick": True, "force_entries_every_candle": False,
    "decision_loop_interval_ticks": 4, "require_backtest_evidence_for_entry": True}}}

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    s = Session(eng)
    hb = HeartbeatService(s, CFG)

    # Invariant: never forces entries; always manages exits.
    st = hb.status()
    assert st["force_entries_every_candle"] is False, st
    assert hb.manages_exits_every_tick() is True, st

    # Heartbeat-only ticks (not on the decision cadence) block new entries.
    for tc in (1, 2, 3, 5, 6, 7):
        assert HEARTBEAT_ONLY_BLOCKER in hb.entry_gate_blockers(tick_count=tc), tc
    # Decision ticks (multiples of interval) are NOT heartbeat-blocked (entries may be considered).
    for tc in (0, 4, 8, 12):
        assert HEARTBEAT_ONLY_BLOCKER not in hb.entry_gate_blockers(tick_count=tc), tc

    # Even on a decision tick, with no backtest evidence entries are still blocked.
    assert NO_BACKTEST_EVIDENCE_BLOCKER in hb.entry_gate_blockers(tick_count=4), "no backtest evidence must block entries"

    # Static proof: the training loop injects the gate AND manages exits before entries.
    loop = (BACKEND / "app/services/fast_crypto_training_loop.py").read_text(encoding="utf-8")
    assert "HeartbeatService" in loop and "entry_gate_blockers" in loop, "loop must inject the heartbeat gate"
    assert loop.index("monitor_exits") < loop.index("scan_entries"), "exits must be managed before entries are scanned"
    s.close()
    print("verify_heartbeat_does_not_force_entries: PASS (exits managed every tick; entries only on decision loop + evidence)")


if __name__ == "__main__":
    main()
