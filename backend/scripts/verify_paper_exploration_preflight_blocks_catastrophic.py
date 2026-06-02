"""run_preflight blocks a paper-exploration probe with a SPECIFIC CATASTROPHIC_KILL_SWITCH
reason when a catastrophic switch is active (manual master / max drawdown / weekly drawdown /
system health) — never opaque, never overridden."""

import copy
import types

from _alpha_factory_verify_common import session_with_config  # noqa: E402

import app.services.execution_preflight as pf_mod  # noqa: E402
from app.database import KillSwitchEvent  # noqa: E402
from app.services.execution_preflight import run_preflight  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402

pf_mod.is_paper_broker_url = lambda *a, **k: True  # type: ignore[assignment]


def _acct(drawdown_pct=1.0):
    return types.SimpleNamespace(equity=1000.0, daily_pl_pct=-4.0, drawdown_pct=drawdown_pct,
                                 buying_power=1000.0, cash=1000.0, raw_payload={})


def _run(cfg_over=None, drawdown_pct=1.0, event=None):
    session, cfg = session_with_config()
    if cfg_over:
        cfg = copy.deepcopy(cfg)
        for k, v in cfg_over.items():
            cfg.setdefault("kill", {})[k] = v
    if event:
        session.add(KillSwitchEvent(switch_name=event, active=True, message=f"{event} active"))
        session.commit()
    probe = PaperExplorationService(session, cfg).build_probe_candidate(nm(), price=70000.0)
    return run_preflight(session, cfg, cand=probe, cycle_run_id="t", portfolio_decision=None,
                         account=_acct(drawdown_pct), positions=[], open_order_symbols=set(),
                         alpaca=None, quote={})


def main() -> None:
    cases = {
        "manual_master": _run(cfg_over={"manual_master_active": True}),
        "max_drawdown": _run(drawdown_pct=20.0),       # >= 15% max_dd
        "weekly_drawdown": _run(event="weekly_drawdown"),
        "system_health": _run(event="system_health"),
    }
    for name, r in cases.items():
        assert r.block_reason_code == "CATASTROPHIC_KILL_SWITCH", (name, r.block_reason_code)
        cat = (r.evidence or {}).get("exploration_override_decision", {}).get("catastrophic_switches", [])
        assert name in cat, (name, cat)
        assert r.evidence.get("exploration_override_denied_reason") == "CATASTROPHIC_KILL_SWITCH", (name, r.evidence)
    print("verify_paper_exploration_preflight_blocks_catastrophic: PASS (manual/max/weekly/system all block)")


if __name__ == "__main__":
    main()
