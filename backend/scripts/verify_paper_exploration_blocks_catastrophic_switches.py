"""Catastrophic kill switches block even a valid paper-exploration probe, with a SPECIFIC
reason (CATASTROPHIC_KILL_SWITCH), never an opaque KILL_SWITCH_ACTIVE."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from app.trading_cage.paper_exploration_guard import (  # noqa: E402
    CATASTROPHIC_SWITCHES,
    can_override_kill_switch_for_paper_exploration,
)
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)
    probe = svc.build_probe_candidate(nm(), price=70000.0)

    for switch in ("manual_master", "max_drawdown", "weekly_drawdown", "weekly_loss", "system_health"):
        assert switch in CATASTROPHIC_SWITCHES, switch
        d = can_override_kill_switch_for_paper_exploration([{"switch_name": switch}], probe, cfg)
        assert d["allowed"] is False, (switch, d)
        assert d["denied_reason"] == "CATASTROPHIC_KILL_SWITCH", (switch, d)
        assert switch in d["catastrophic_switches"], (switch, d)

    # A catastrophic switch mixed with daily drawdown still blocks.
    d = can_override_kill_switch_for_paper_exploration(
        [{"switch_name": "daily_drawdown"}, {"switch_name": "max_drawdown"}], probe, cfg
    )
    assert d["allowed"] is False and d["denied_reason"] == "CATASTROPHIC_KILL_SWITCH", d
    print("verify_paper_exploration_blocks_catastrophic_switches: PASS")


if __name__ == "__main__":
    main()
