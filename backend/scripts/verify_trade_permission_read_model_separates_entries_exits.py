"""Cockpit trade-permission read model separates new ENTRIES from EXITS.

The kill switch / daily drawdown gate blocks new entries only; exits are never blocked
while the paper broker is connected. This proves the read model reports that truth and
never reports the bot as fully unable to act when only entries are paused.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
import app.services.mission_control_read_model as mc

CFG = {
    "execution": {"paper_orders_enabled": True, "live_orders_enabled": False},
    "autonomous_paper_learning": {"mode_enabled": True, "scheduler_enabled": True},
}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _patch(monkey_entries_allowed: bool):
    mc.is_paper_broker_url = lambda: True
    mc.env_pause_status = lambda: {}
    mc.live_lock_status = lambda cfg: {"live_lock_status": "locked"}

    class _Kill:
        def __init__(self, *a, **k):
            pass

        def status(self):
            return {
                "entries_allowed": monkey_entries_allowed,
                "active_switches": ([] if monkey_entries_allowed else [{"switch_name": "daily_drawdown", "message": "Daily drawdown limit hit."}]),
            }

    mc.KillSwitchService = _Kill


def test_entries_and_exits_both_open_when_healthy() -> None:
    _patch(True)
    s = _mem()
    out = mc._execution_safety(s, CFG)
    for k in ("broker_connected", "paper_mode_active", "live_trading_locked",
              "new_entries_allowed", "exits_allowed", "kill_switch_blocks_exits",
              "entries_exits_summary", "blocker_codes"):
        assert k in out, f"missing field {k}"
    assert out["new_entries_allowed"] is True, out["new_entries_allowed"]
    assert out["exits_allowed"] is True, out["exits_allowed"]
    assert out["kill_switch_blocks_exits"] is False, out
    assert out["paper_mode_active"] is True and out["live_trading_locked"] is True, out
    s.close()
    print("trade-permission: healthy -> entries AND exits allowed, live locked — PASS")


def test_kill_switch_blocks_entries_not_exits() -> None:
    _patch(False)  # daily drawdown kill switch active
    s = _mem()
    out = mc._execution_safety(s, CFG)
    assert out["kill_switch_active"] is True, out
    assert out["new_entries_allowed"] is False, out["new_entries_allowed"]   # entries paused
    assert out["exits_allowed"] is True, out["exits_allowed"]                 # KEY: exits still allowed
    assert out["kill_switch_blocks_exits"] is False, out
    assert "exit" in out["entries_exits_summary"].lower(), out["entries_exits_summary"]
    assert "kill_switch_active" in out["blocker_codes"], out["blocker_codes"]
    s.close()
    print("trade-permission: kill switch pauses ENTRIES only, EXITS stay open — PASS")


if __name__ == "__main__":
    test_entries_and_exits_both_open_when_healthy()
    test_kill_switch_blocks_entries_not_exits()
    print("ALL PASS: verify_trade_permission_read_model_separates_entries_exits")
