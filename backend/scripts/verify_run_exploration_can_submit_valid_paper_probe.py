"""When a broker-valid candidate exists (cap >= broker min) and the paper broker accepts, the
endpoint returns submitted=true with a paper_order_submitted status — and ONLY through the
official PaperExecutionService -> ExecutionCage path (no direct Alpaca order, never live)."""

import copy

from _alpha_factory_verify_common import session_with_config  # noqa: E402

import app.services.alpaca_adapter as alpaca_mod  # noqa: E402
import app.services.paper_execution_service as pes_mod  # noqa: E402
from app.services.paper_exploration_service import SUBMITTED_STATUSES, PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


class _FakeLog:
    def __init__(self, status, _id=101):
        self.status, self.reject_reason, self.id = status, None, _id
        self.broker_order_id = "paper-abc-123"


def main() -> None:
    session, cfg = session_with_config()
    # Operator opts the cap above the broker minimum so a probe is broker-valid.
    cfg = copy.deepcopy(cfg)
    cfg["alpha_factory"]["paper_exploration"]["exploration_max_notional_usd"] = 15.0

    alpaca_mod.AlpacaAdapter.get_quote = lambda self, *a, **k: {"mid": 70000.0, "ask": 70010.0}  # type: ignore
    alpaca_mod.AlpacaAdapter.sync_account_cached = lambda self, *a, **k: None  # type: ignore
    # Forbid any direct broker order outside PaperExecutionService.
    def forbid(*a, **k):
        raise AssertionError("DIRECT_ALPACA_ORDER_FORBIDDEN")
    alpaca_mod.AlpacaAdapter.submit_marketable_limit_ioc = forbid  # type: ignore
    alpaca_mod.AlpacaAdapter.submit_crypto_market_notional = forbid  # type: ignore

    calls = {"n": 0}

    def ok_submit(self, cand, **kw):
        calls["n"] += 1
        assert (cand.meta or {}).get("near_miss_exploration_probe") is True, "must be a marked probe"
        assert cand.position_qty * cand.entry_price <= 15.0 + 1e-9, "notional within cap"
        return _FakeLog("paper_order_submitted")

    pes_mod.PaperExecutionService.submit_candidate = ok_submit  # type: ignore

    svc = PaperExplorationService(session, cfg)
    # Provide one eligible + broker-valid candidate.
    svc.select_candidate_detailed = lambda: {  # type: ignore
        "selected": {**nm(), "exploration_eligible": True, "broker_valid_for_exploration": True,
                     "exploration_score": 0.7, "min_required_notional_usd": 10.2},
        "skipped_broker_invalid": [], "no_broker_valid_candidate": False,
    }
    out = svc.submit_exploration_order(dry_run=False)
    assert calls["n"] == 1, "must submit through PaperExecutionService.submit_candidate"
    assert out["submitted"] is True and out["status"] == "submitted", out
    assert out["execution_status"] in SUBMITTED_STATUSES, out
    assert out["orders_created"] == 1, out
    assert out["permission"]["real_money_entries_allowed"] is False, out
    print(f"verify_run_exploration_can_submit_valid_paper_probe: PASS (execution_status={out['execution_status']})")


if __name__ == "__main__":
    main()
