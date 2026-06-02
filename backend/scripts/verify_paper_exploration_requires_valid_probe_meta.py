"""A probe must carry full valid meta to get the override: probe flag, EXPLORATION coid, full
exit plan, entry side, paper mode. Missing any of these -> invalid (no override)."""

import copy

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from app.trading_cage.paper_exploration_guard import (  # noqa: E402
    can_override_kill_switch_for_paper_exploration,
    is_valid_paper_exploration_probe,
)
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)
    base = svc.build_probe_candidate(nm(), price=70000.0)
    assert is_valid_paper_exploration_probe(base, cfg)["valid"] is True

    def mutated(**meta_over):
        c = svc.build_probe_candidate(nm(), price=70000.0)
        c.meta = {**(c.meta or {}), **meta_over}
        return c

    # No probe flag.
    c = mutated(near_miss_exploration_probe=False, paper_exploration_probe=False)
    r = is_valid_paper_exploration_probe(c, cfg)
    assert r["valid"] is False and "has_probe_meta" in r["blockers"], r

    # No EXPLORATION client_order_id.
    c = mutated(client_order_id="NORMAL-123")
    r = is_valid_paper_exploration_probe(c, cfg)
    assert r["valid"] is False and "client_order_id_starts_exploration" in r["blockers"], r

    # Missing exit plan.
    c = mutated(dynamic_exit_levels={"stop_loss": 1.0})
    r = is_valid_paper_exploration_probe(c, cfg)
    assert r["valid"] is False and "exit_plan_present" in r["blockers"], r

    # Live orders enabled -> invalid even with a perfect probe.
    cfg_live = copy.deepcopy(cfg)
    cfg_live["execution"]["live_orders_enabled"] = True
    r = is_valid_paper_exploration_probe(base, cfg_live)
    assert r["valid"] is False and "live_orders_disabled" in r["blockers"], r
    d = can_override_kill_switch_for_paper_exploration([{"switch_name": "daily_drawdown"}], base, cfg_live)
    assert d["allowed"] is False and d["denied_reason"] == "EXPLORATION_PROBE_INVALID", d
    print("verify_paper_exploration_requires_valid_probe_meta: PASS")


if __name__ == "__main__":
    main()
