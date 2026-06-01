"""Exploration orders route through the official cage (no bypass): the probe is recognised by
the cage overrides, the kill-switch override allows ONLY non-catastrophic switches, and a
blocked permission produces no order."""

import copy

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.trading_cage.execution_cage import (  # noqa: E402
    _exploration_kill_switch_override,
    _is_near_miss_exploration_probe,
    _paper_exploration_cost_override,
)
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)
    cand = svc.build_probe_candidate(nm(), price=100.0)

    # Cage recognises the probe (so it flows through cage overrides, not around the cage).
    assert _is_near_miss_exploration_probe(cfg, cand) is True, cand.meta
    # Exit truth present -> cage cost override applies in paper mode (near-breakeven near-miss).
    assert _paper_exploration_cost_override(cfg, cand) is True, cand.meta

    # Kill-switch override: daily drawdown alone is explorable; catastrophic switches are NOT.
    assert _exploration_kill_switch_override(cfg, cand, [{"switch_name": "daily_drawdown"}]) is True
    for bad in ("max_drawdown", "manual_master", "system_health", "weekly_drawdown"):
        assert _exploration_kill_switch_override(cfg, cand, [{"switch_name": bad}]) is False, bad

    # A non-probe candidate is never granted the override.
    cand.meta["near_miss_exploration_probe"] = False
    assert _exploration_kill_switch_override(cfg, cand, [{"switch_name": "daily_drawdown"}]) is False

    # Blocked permission (live forced on) -> submit places no order.
    cfg_live = copy.deepcopy(cfg)
    cfg_live["execution"]["live_orders_enabled"] = True
    out = PaperExplorationService(session, cfg_live).submit_exploration_order(dry_run=False)
    assert out["submitted"] is False and out["orders_created"] == 0, out
    print("verify_paper_exploration_uses_official_cage: PASS")


if __name__ == "__main__":
    main()
