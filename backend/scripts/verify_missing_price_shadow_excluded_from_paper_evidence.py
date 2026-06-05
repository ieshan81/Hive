"""missing_price_data shadow closes never count as paper-canary evidence."""

from __future__ import annotations

from datetime import datetime, timedelta

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.paper_canary_gate_service import is_qualified_shadow_close, list_qualified_shadow_closes  # noqa: E402
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_CLOSED  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = ShadowTrade(
        shadow_trade_id="missing-px-1",
        validation_run_id="paper_validation_run_001",
        symbol="ETH/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_CLOSED,
        entry_reference_price=100.0,
        exit_reference_price=None,
        simulated_pnl_bps=0.0,
        setup_fingerprint="fp-missing",
        outcome_json={"exit_reason": "missing_price_data", "hold_seconds": 200, "price_source": "missing"},
        created_at=datetime.utcnow() - timedelta(hours=1),
        closed_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    ok, why = is_qualified_shadow_close(row, cfg)
    assert not ok and "missing_price" in why, (ok, why)
    _, excl = list_qualified_shadow_closes(session, cfg)
    assert excl["excluded_missing_price"] >= 1
    session.rollback()
    print("verify_missing_price_shadow_excluded_from_paper_evidence: PASS")


if __name__ == "__main__":
    main()
