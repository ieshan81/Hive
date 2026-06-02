"""Both layers agree: under a daily-drawdown switch, a valid $12 paper probe is NOT blocked by
KILL_SWITCH_ACTIVE at the ExecutionCage kill-switch stage OR the run_preflight kill-switch stage.
This is the end-to-end alignment that removes the production permission/cage/preflight mismatch."""

import types

from _alpha_factory_verify_common import session_with_config  # noqa: E402

import app.services.execution_preflight as pf_mod  # noqa: E402
from app.database import AccountSnapshot  # noqa: E402
from app.services.execution_preflight import run_preflight  # noqa: E402
from app.services.kill_switch_service import KillSwitchService  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from app.trading_cage.paper_exploration_guard import can_override_kill_switch_for_paper_exploration  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402

pf_mod.is_paper_broker_url = lambda *a, **k: True  # type: ignore[assignment]


def main() -> None:
    session, cfg = session_with_config()
    # Daily-drawdown account snapshot so the permission layer (DB-based) also sees the block.
    session.add(AccountSnapshot(equity=1000.0, daily_pl_pct=-4.0, drawdown_pct=1.0, cash=1000.0, buying_power=1000.0))
    session.commit()
    svc = PaperExplorationService(session, cfg)
    assert svc.max_notional_usd == 12.0, svc.max_notional_usd  # $12 cap
    assert svc.broker_validity(nm())["broker_valid"] is True, "BTC at $12 must be broker-valid"

    account = types.SimpleNamespace(equity=1000.0, daily_pl_pct=-4.0, drawdown_pct=1.0,
                                    buying_power=1000.0, cash=1000.0, raw_payload={})
    ks = KillSwitchService(session, cfg)
    entries_ok, switches = ks.evaluate(equity=1000, daily_pl_pct=-4.0, drawdown_pct=1.0)
    assert entries_ok is False and {s["switch_name"] for s in switches} == {"daily_drawdown"}, switches

    probe = svc.build_probe_candidate(nm(), price=70000.0)

    # Layer 1 — ExecutionCage canonical override: allowed (not KILL_SWITCH_ACTIVE).
    cage_decision = can_override_kill_switch_for_paper_exploration(switches, probe, cfg, account)
    assert cage_decision["allowed"] is True, cage_decision

    # Layer 2 — run_preflight: passes the kill-switch stage (no KILL_SWITCH_ACTIVE / catastrophic).
    r = run_preflight(session, cfg, cand=probe, cycle_run_id="t", portfolio_decision=None,
                      account=account, positions=[], open_order_symbols=set(), alpaca=None, quote={})
    assert r.block_reason_code not in ("KILL_SWITCH_ACTIVE", "CATASTROPHIC_KILL_SWITCH"), r.block_reason_code
    assert (r.evidence or {}).get("paper_exploration_preflight_kill_switch_override"), r.evidence

    # Safety invariants intact at both layers.
    perm = svc.permission()
    assert perm["real_money_entries_allowed"] is False, perm
    assert perm["paper_entries_allowed"] is False, perm           # standard entries still blocked
    assert perm["exit_management_allowed"] is True, perm
    print("verify_run_exploration_real_submit_no_kill_switch_mismatch: PASS (cage + preflight aligned)")


if __name__ == "__main__":
    main()
