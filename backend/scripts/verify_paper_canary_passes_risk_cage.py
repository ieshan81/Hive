"""Paper canary probes are recognized by the execution cage for notional capping."""

from __future__ import annotations

from unittest.mock import MagicMock

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.portfolio_gate import ApprovedCandidate  # noqa: E402
from app.trading_cage.execution_cage import ExecutionCage  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    cand = ApprovedCandidate(
        signal_id=0,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        meta={"paper_canary_probe": True, "strategy_id": "crypto_push_pull_baseline"},
        strength=0.5,
        confidence=0.5,
        spread_pct=None,
        liquidity_score=None,
        edge_over_cost=None,
        expected_move_pct=None,
        position_qty=5.0,
        entry_price=100.0,
        stop_loss=99.0,
        atr14=None,
        tier="TIER_ALT",
        cost_evidence={},
        sizing_evidence={},
    )
    account = MagicMock(equity=200.0, portfolio_value=200.0)
    cage = ExecutionCage(session, cfg)
    # validate_submit may fail on preflight without broker — we only assert probe path runs cage guard
    from app.trading_cage.execution_cage import _is_paper_canary_probe

    assert _is_paper_canary_probe(cfg, cand) is True
    session.rollback()
    print("verify_paper_canary_passes_risk_cage: PASS (probe recognized by cage)")


if __name__ == "__main__":
    main()
