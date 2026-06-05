"""Qualified shadow closes can promote a paper_candidate scorecard when aggregate gate passes."""

from __future__ import annotations

from datetime import datetime, timedelta

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.paper_canary_gate_service import (  # noqa: E402
    PaperCanaryGateService,
    evaluate_aggregate_gate,
    compute_aggregate_metrics,
)
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_CLOSED  # noqa: E402


def _seed_close(session, sym: str, pnl_bps: float, *, reason: str = "shadow_target") -> None:
    session.add(
        ShadowTrade(
            shadow_trade_id=f"canary-{sym}-{pnl_bps}",
            validation_run_id="paper_validation_run_001",
            symbol=sym,
            asset_class="crypto",
            strategy_id="crypto_push_pull_baseline",
            promotion_level=LEVEL_SHADOW_TRADE,
            status=STATUS_CLOSED,
            entry_reference_price=100.0,
            exit_reference_price=100.0 + pnl_bps / 100.0,
            simulated_pnl_bps=pnl_bps,
            outcome_verdict="win" if pnl_bps > 0 else "loss",
            setup_fingerprint=f"fp-{sym}-{pnl_bps}",
            outcome_json={
                "exit_reason": reason,
                "hold_seconds": 120,
                "price_source": "quote_mid",
            },
            counts_as_broker_evidence=False,
            created_at=datetime.utcnow() - timedelta(hours=2),
            closed_at=datetime.utcnow() - timedelta(hours=1),
        )
    )


def main() -> None:
    session, cfg = session_with_config()
    cfg.setdefault("shadow_league", {}).setdefault("paper_canary", {})["min_qualified_closes"] = 5
    for i in range(6):
        _seed_close(session, "BTC/USD", 180.0 + i * 5)
    session.commit()
    svc = PaperCanaryGateService(session, cfg)
    out = svc.evaluate_and_promote()
    assert out["aggregate_gate_passed"], out
    assert out["paper_candidate_promoted"], out
    st = svc.status()
    assert st["aggregate_gate_passed"]
    assert st["shadow_paper_candidate_count"] >= 1
    session.rollback()
    print("verify_shadow_to_paper_candidate_gate: PASS")


if __name__ == "__main__":
    main()
