"""The exploration lane is paper-only: real money is never allowed and enabling live orders
hard-blocks exploration (it can never become a live path)."""

import copy

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    perm = svc.permission()
    assert perm["real_money_entries_allowed"] is False, perm
    assert perm["exit_management_allowed"] is True, perm

    # A built probe never carries a live intent and is tagged paper-exploration.
    cand = svc.build_probe_candidate(nm(), price=100.0)
    assert cand.meta.get("near_miss_exploration_probe") is True, cand.meta
    assert "EXPLORATION" in str(cand.meta.get("client_order_id")), cand.meta
    assert cand.side == "buy" and cand.signal_type == "entry", cand

    # Flip live orders on -> exploration is hard-blocked; real money still false.
    cfg_live = copy.deepcopy(cfg)
    cfg_live["execution"]["live_orders_enabled"] = True
    cfg_live["live_trading_enabled"] = True
    perm_live = PaperExplorationService(session, cfg_live).permission()
    assert perm_live["paper_exploration_allowed"] is False, perm_live
    assert perm_live["real_money_entries_allowed"] is False, perm_live
    assert perm_live["paper_exploration_block_reason"] == "live_not_forbidden", perm_live

    # A submit attempt under live config places no order.
    out = PaperExplorationService(session, cfg_live).submit_exploration_order(dry_run=True)
    assert out["submitted"] is False and out["orders_created"] == 0, out
    print("verify_paper_exploration_never_live: PASS")


if __name__ == "__main__":
    main()
