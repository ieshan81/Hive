"""run_preflight applies the SAME paper-exploration kill-switch override as ExecutionCage:
a valid marked probe passes the kill-switch stage under a daily-drawdown switch (with override
evidence), while a standard (non-probe) entry still blocks with KILL_SWITCH_ACTIVE."""

import types

from _alpha_factory_verify_common import session_with_config  # noqa: E402

import app.services.execution_preflight as pf_mod  # noqa: E402
from app.services.execution_preflight import run_preflight  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402

# Reach the kill-switch stage deterministically (broker-paper gate is env-dependent).
pf_mod.is_paper_broker_url = lambda *a, **k: True  # type: ignore[assignment]


def _account(daily_pl_pct=-4.0, drawdown_pct=1.0):
    return types.SimpleNamespace(equity=1000.0, daily_pl_pct=daily_pl_pct, drawdown_pct=drawdown_pct,
                                 buying_power=1000.0, cash=1000.0, raw_payload={})


def _preflight(session, cfg, cand):
    return run_preflight(
        session, cfg, cand=cand, cycle_run_id="t", portfolio_decision=None,
        account=_account(), positions=[], open_order_symbols=set(), alpaca=None, quote={},
    )


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    # Standard (non-probe) entry under daily drawdown -> KILL_SWITCH_ACTIVE (unchanged).
    plain = svc.build_probe_candidate(nm(), price=70000.0)
    plain.meta = {}  # strip probe markers -> standard entry
    plain.signal_type = "entry"
    r_plain = _preflight(session, cfg, plain)
    assert r_plain.block_reason_code == "KILL_SWITCH_ACTIVE", r_plain.block_reason_code

    # Valid marked probe under daily drawdown -> passes the kill-switch stage (blocks later at
    # SIGNAL_NOT_SELECTED), and carries the override evidence.
    probe = svc.build_probe_candidate(nm(), price=70000.0)
    r_probe = _preflight(session, cfg, probe)
    assert r_probe.block_reason_code != "KILL_SWITCH_ACTIVE", r_probe.block_reason_code
    assert r_probe.block_reason_code == "SIGNAL_NOT_SELECTED", r_probe.block_reason_code  # next gate, not kill switch
    ev = (r_probe.evidence or {}).get("paper_exploration_preflight_kill_switch_override")
    assert ev, ("override evidence missing", r_probe.evidence)
    assert ev["standard_entries_still_blocked"] is True, ev
    assert ev["real_money_still_locked"] is True, ev
    assert ev["exits_allowed"] is True, ev
    print("verify_paper_exploration_preflight_allows_daily_drawdown: PASS")


if __name__ == "__main__":
    main()
