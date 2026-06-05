"""Paper canary notional is capped at a small fraction of equity."""

from __future__ import annotations

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.paper_canary_gate_service import paper_canary_max_notional_usd, is_paper_canary_probe  # noqa: E402
from app.services.portfolio_gate import ApprovedCandidate  # noqa: E402
from app.trading_cage.execution_cage import _is_paper_canary_probe, _paper_canary_max_notional  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    equity = 200.0
    cap = paper_canary_max_notional_usd(cfg, equity)
    assert cap == 10.0, cap  # 5% of 200
    assert _paper_canary_max_notional(cfg, equity) == cap
    cand = ApprovedCandidate(
        signal_id=0,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        meta={"paper_canary_probe": True},
        strength=0.5,
        confidence=0.5,
        spread_pct=None,
        liquidity_score=None,
        edge_over_cost=None,
        expected_move_pct=None,
        position_qty=1.0,
        entry_price=100.0,
        stop_loss=99.0,
        atr14=None,
        tier="TIER_ALT",
        cost_evidence={},
        sizing_evidence={},
    )
    assert is_paper_canary_probe(cfg, cand)
    assert _is_paper_canary_probe(cfg, cand)
    session.rollback()
    print("verify_paper_canary_uses_tiny_size: PASS")


if __name__ == "__main__":
    main()
