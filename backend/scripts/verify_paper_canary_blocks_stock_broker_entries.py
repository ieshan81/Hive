"""Paper canary blocks stock symbols from broker entry path."""

from __future__ import annotations

from unittest.mock import patch

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_canary_gate_service import PaperCanaryGateService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    cfg.setdefault("execution", {})["paper_orders_enabled"] = True
    svc = PaperCanaryGateService(session, cfg)
    fake_promo = {
        "aggregate_gate_passed": True,
        "candidate_symbol": "AAPL",
        "gate": {"aggregate_gate_passed": True, "gate_failures": []},
        "audit": {"candidate_strategy_id": "stock_push_pull_baseline"},
    }
    with patch.object(svc, "evaluate_and_promote", return_value=fake_promo):
        out = svc.try_submit_canary_order(operator="verify")
    assert out["block_reason"] in ("stock_broker_blocked", "crypto_only"), out
    session.rollback()
    print("verify_paper_canary_blocks_stock_broker_entries: PASS")


if __name__ == "__main__":
    main()
