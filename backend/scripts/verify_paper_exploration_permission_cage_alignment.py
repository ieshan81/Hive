"""Permission layer and cage agree: a valid marked probe passes a daily-drawdown kill switch,
a standard (non-probe) entry still blocks, real money stays locked, exits stay allowed."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import AccountSnapshot  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from app.services.kill_switch_service import KillSwitchService  # noqa: E402
from app.trading_cage.paper_exploration_guard import can_override_kill_switch_for_paper_exploration  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


class _Plain:
    """A standard (non-exploration) entry candidate — no probe meta."""
    meta = {}
    signal_type = "entry"
    side = "buy"


def main() -> None:
    session, cfg = session_with_config()
    # Daily drawdown only (non-catastrophic): standard entries blocked.
    session.add(AccountSnapshot(equity=1000.0, daily_pl_pct=-3.0, drawdown_pct=1.0, cash=1000.0, buying_power=1000.0))
    session.commit()

    svc = PaperExplorationService(session, cfg)
    ks = KillSwitchService(session, cfg)
    entries_ok, switches = ks.evaluate(equity=1000, daily_pl_pct=-3.0, drawdown_pct=1.0)
    assert entries_ok is False, "daily drawdown must block standard entries"
    assert {s["switch_name"] for s in switches} == {"daily_drawdown"}, switches

    perm = svc.permission()
    assert perm["paper_exploration_allowed"] is True, perm
    assert perm["paper_entries_allowed"] is False, perm  # standard entries still blocked
    assert perm["real_money_entries_allowed"] is False and perm["exit_management_allowed"] is True, perm

    # Cage-side canonical decision matches: valid probe overrides daily drawdown.
    probe = svc.build_probe_candidate(nm(), price=70000.0)
    d_probe = can_override_kill_switch_for_paper_exploration(switches, probe, cfg)
    assert d_probe["allowed"] is True, d_probe
    assert d_probe["standard_entries_still_blocked"] is True and d_probe["real_money_still_locked"] is True, d_probe

    # A standard (non-probe) entry is NEVER overridden — standard safety unchanged.
    d_plain = can_override_kill_switch_for_paper_exploration(switches, _Plain(), cfg)
    assert d_plain["allowed"] is False, d_plain
    assert d_plain["denied_reason"] == "EXPLORATION_PROBE_INVALID", d_plain
    print("verify_paper_exploration_permission_cage_alignment: PASS")


if __name__ == "__main__":
    main()
