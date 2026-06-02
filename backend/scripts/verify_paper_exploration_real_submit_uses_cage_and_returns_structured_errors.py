"""Real-submit exploration uses ONLY the official cage path and returns structured errors.

Proves:
  - the broker submit goes through PaperExecutionService.submit_candidate (no direct Alpaca order),
  - a thrown execution exception becomes a structured error (status=error, error_stage,
    safe_human_message), never an uncaught crash,
  - a broker/cage rejection is never reported as submitted (no fake submit),
  - live config hard-blocks the lane before any submit,
  - the probe notional stays <= the $5 cap.
"""

import copy

from _alpha_factory_verify_common import session_with_config  # noqa: E402

import app.services.alpaca_adapter as alpaca_mod  # noqa: E402
import app.services.paper_execution_service as pes_mod  # noqa: E402
from app.services.paper_exploration_service import SUBMITTED_STATUSES, PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


class _FakeLog:
    def __init__(self, status, reject_reason=None, _id=1):
        self.status = status
        self.reject_reason = reject_reason
        self.id = _id


def _patch_select(svc):
    svc.select_candidate = lambda: nm()  # type: ignore[assignment]


def _forbid_direct_alpaca():
    def boom(*a, **k):
        raise AssertionError("DIRECT_ALPACA_ORDER_FORBIDDEN — must go through PaperExecutionService")
    alpaca_mod.AlpacaAdapter.submit_marketable_limit_ioc = boom  # type: ignore[assignment]
    alpaca_mod.AlpacaAdapter.submit_crypto_market_notional = boom  # type: ignore[assignment]
    alpaca_mod.AlpacaAdapter.sync_account_cached = lambda self, *a, **k: None  # type: ignore[assignment]
    alpaca_mod.AlpacaAdapter.get_quote = lambda self, *a, **k: {"mid": 100.0, "ask": 100.1}  # type: ignore[assignment]


def main() -> None:
    session, cfg = session_with_config()
    _forbid_direct_alpaca()

    # 1) Cage path used + success classified from a real paper_order_submitted status.
    calls = {"n": 0}

    def ok_submit(self, cand, **kw):
        calls["n"] += 1
        assert (cand.meta or {}).get("near_miss_exploration_probe") is True, "must pass a marked probe to the cage"
        assert cand.position_qty * cand.entry_price <= 5.0 + 1e-9, "notional must stay <= $5"
        return _FakeLog("paper_order_submitted", _id=42)

    pes_mod.PaperExecutionService.submit_candidate = ok_submit  # type: ignore[assignment]
    svc = PaperExplorationService(session, cfg)
    _patch_select(svc)
    out = svc.submit_exploration_order(dry_run=False)
    assert calls["n"] == 1, "must route through PaperExecutionService.submit_candidate"
    assert out["submitted"] is True and out["status"] == "submitted", out
    assert out["execution_status"] in SUBMITTED_STATUSES, out

    # 2) Execution exception -> structured error, never a raise.
    def raise_submit(self, cand, **kw):
        raise RuntimeError("simulated execution explosion")

    pes_mod.PaperExecutionService.submit_candidate = raise_submit  # type: ignore[assignment]
    svc2 = PaperExplorationService(session, cfg)
    _patch_select(svc2)
    err = svc2.submit_exploration_order(dry_run=False)
    assert err["status"] == "error" and err["submitted"] is False, err
    assert err["error_stage"] == "paper_execution_submit", err
    assert err["block_reason"] == "paper_execution_exception", err
    assert err["exception_type"] == "RuntimeError", err
    assert err["safe_human_message"], err
    assert err["orders_created"] == 0, err

    # 3) Broker/cage rejection -> never reported as submitted (no fake submit).
    for status in ("paper_order_rejected", "preflight_blocked"):
        pes_mod.PaperExecutionService.submit_candidate = (  # type: ignore[assignment]
            lambda self, cand, _s=status, **kw: _FakeLog(_s, reject_reason="REASON_X")
        )
        svc3 = PaperExplorationService(session, cfg)
        _patch_select(svc3)
        r = svc3.submit_exploration_order(dry_run=False)
        assert r["submitted"] is False and r["status"] == "blocked", (status, r)
        assert r["orders_created"] == 0, r

    # 4) Live config hard-blocks before any submit (no live path).
    calls["n"] = 0
    pes_mod.PaperExecutionService.submit_candidate = ok_submit  # would set calls if reached
    cfg_live = copy.deepcopy(cfg)
    cfg_live["execution"]["live_orders_enabled"] = True
    svc4 = PaperExplorationService(session, cfg_live)
    _patch_select(svc4)
    live = svc4.submit_exploration_order(dry_run=False)
    assert live["submitted"] is False, live
    assert live["permission"]["real_money_entries_allowed"] is False, live
    assert calls["n"] == 0, "live config must block before reaching the broker submit"
    print("verify_paper_exploration_real_submit_uses_cage_and_returns_structured_errors: PASS")


if __name__ == "__main__":
    main()
