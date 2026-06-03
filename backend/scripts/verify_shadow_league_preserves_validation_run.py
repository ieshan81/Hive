"""Shadow records must stay scoped to paper_validation_run_001 epoch."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID  # noqa: E402
from app.services.shadow_trade_service import ShadowTradeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = {
        "symbol": "SOL/USD",
        "asset_class": "crypto",
        "trade_quality_score": 0.48,
        "push_score": 0.012,
        "entry_allowed": False,
        "no_trade_reason": "BLOCKED",
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
    }
    out = ShadowTradeService(session, cfg).consider_setup(row, paper_blocked_reason="TEST_BLOCK")
    for key in ("observation", "shadow_trade"):
        block = out.get(key) or {}
        if block.get("shadow_trade_id"):
            from app.database import ShadowTrade
            from sqlmodel import select

            st = session.exec(
                select(ShadowTrade).where(ShadowTrade.shadow_trade_id == block["shadow_trade_id"])
            ).first()
            assert st and st.validation_run_id == PAPER_VALIDATION_RUN_ID, st
    print("verify_shadow_league_preserves_validation_run: PASS")


if __name__ == "__main__":
    main()
