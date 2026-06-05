"""max_open_cap_release shadow closes never count as positive paper-canary evidence."""

from __future__ import annotations

from datetime import datetime, timedelta

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.paper_canary_gate_service import is_qualified_shadow_close, list_qualified_shadow_closes  # noqa: E402
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_CLOSED  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = ShadowTrade(
        shadow_trade_id="cap-rel-1",
        validation_run_id="paper_validation_run_001",
        symbol="SOL/USD",
        asset_class="crypto",
        promotion_level=LEVEL_SHADOW_TRADE,
        status=STATUS_CLOSED,
        entry_reference_price=50.0,
        exit_reference_price=51.0,
        simulated_pnl_bps=20.0,
        setup_fingerprint="fp-cap",
        outcome_json={"exit_reason": "max_open_cap_release", "hold_seconds": 10, "price_source": "quote_mid"},
        created_at=datetime.utcnow() - timedelta(minutes=30),
        closed_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    ok, why = is_qualified_shadow_close(row, cfg)
    assert not ok, (ok, why)
    _, excl = list_qualified_shadow_closes(session, cfg)
    assert excl["excluded_cap_release"] >= 1
    session.rollback()
    print("verify_cap_release_shadow_excluded_from_positive_evidence: PASS")


if __name__ == "__main__":
    main()
