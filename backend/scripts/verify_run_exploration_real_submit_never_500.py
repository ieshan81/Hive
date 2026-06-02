"""POST /api/alpha-factory/run-exploration with dry_run=false NEVER returns an uncaught 500.

Every failure mode (quote exception, execution exception, broker rejection, cage block) returns
HTTP 200 with structured JSON; only a real paper_order_submitted status reports submitted=true.
Live stays locked and the probe notional stays <= $5.
"""

import os

os.environ["HIVE_ALLOW_UNAUTHENTICATED_DEV"] = "1"  # operator dev-bypass (no secret in test env)

from _alpha_factory_verify_common import session_with_config  # noqa: E402

import app.services.alpaca_adapter as alpaca_mod  # noqa: E402
import app.services.paper_execution_service as pes_mod  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


class _FakeLog:
    def __init__(self, status, reject_reason=None, _id=7):
        self.status, self.reject_reason, self.id = status, reject_reason, _id


def main() -> None:
    # Activate paper-mode config in the (isolated) DB the app will read.
    session_with_config()
    # Always return a fixed eligible candidate + tame the broker/account/quote deps.
    PaperExplorationService.select_candidate = lambda self: nm()  # type: ignore[assignment]
    alpaca_mod.AlpacaAdapter.sync_account_cached = lambda self, *a, **k: None  # type: ignore[assignment]

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    body = {"operator": "verifier", "dry_run": False}

    def post():
        return client.post("/api/alpha-factory/run-exploration", json=body)

    # A) quote fetch raises -> structured blocked, HTTP 200.
    alpaca_mod.AlpacaAdapter.get_quote = lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("quote boom"))  # type: ignore[assignment]
    r = post()
    assert r.status_code == 200, ("quote", r.status_code, r.text[:200])
    j = r.json()
    assert j["submitted"] is False and j["block_reason"] == "quote_fetch_failed", j
    assert j["error_stage"] == "quote_fetch" and j["safe_human_message"], j

    # From here quotes succeed.
    alpaca_mod.AlpacaAdapter.get_quote = lambda self, *a, **k: {"mid": 100.0, "ask": 100.1}  # type: ignore[assignment]

    # B) execution submit raises -> structured error, HTTP 200, no order.
    pes_mod.PaperExecutionService.submit_candidate = lambda self, cand, **kw: (_ for _ in ()).throw(ValueError("exec boom"))  # type: ignore[assignment]
    r = post()
    assert r.status_code == 200, ("exec", r.status_code, r.text[:200])
    j = r.json()
    assert j["status"] == "error" and j["submitted"] is False, j
    assert j["error_stage"] == "paper_execution_submit" and j["exception_type"] == "ValueError", j

    # C) broker rejection -> blocked, not submitted.
    pes_mod.PaperExecutionService.submit_candidate = lambda self, cand, **kw: _FakeLog("paper_order_rejected", "BROKER_X")  # type: ignore[assignment]
    j = post().json()
    assert j["submitted"] is False and j["status"] == "blocked", j

    # D) cage block -> blocked, not submitted.
    pes_mod.PaperExecutionService.submit_candidate = lambda self, cand, **kw: _FakeLog("preflight_blocked", "KILL_SWITCH_ACTIVE")  # type: ignore[assignment]
    j = post().json()
    assert j["submitted"] is False and j["status"] == "blocked", j

    # E) genuine paper_order_submitted -> submitted true, tiny notional, live locked.
    def good(self, cand, **kw):
        assert cand.position_qty * cand.entry_price <= 5.0 + 1e-9, "notional must stay <= $5"
        assert (cand.meta or {}).get("near_miss_exploration_probe") is True
        return _FakeLog("paper_order_submitted", _id=99)

    pes_mod.PaperExecutionService.submit_candidate = good  # type: ignore[assignment]
    r = post()
    assert r.status_code == 200, ("ok", r.status_code, r.text[:200])
    j = r.json()
    assert j["submitted"] is True and j["orders_created"] == 1, j
    assert j["permission"]["real_money_entries_allowed"] is False, j
    print("verify_run_exploration_real_submit_never_500: PASS (no uncaught 500 across all failure modes)")


if __name__ == "__main__":
    main()
