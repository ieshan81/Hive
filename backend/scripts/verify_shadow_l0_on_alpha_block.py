"""Alpha-blocked paper path may still create L0 shadow observation when quality floor passes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.shadow_trade_service import ShadowTradeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = {
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "trade_quality_score": 0.45,
        "push_score": 0.02,
        "entry_allowed": False,
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
        "no_trade_reason": "ALPHA_NOT_READY:no alpha scorecard",
    }
    out = ShadowTradeService(session, cfg).consider_setup(
        row,
        strategy_id="crypto_push_pull_baseline",
        paper_blocked_reason="ALPHA_NOT_READY:no alpha scorecard",
        paper_submitted=False,
    )
    assert out.get("observation"), f"expected L0 observation: {out}"
    assert (out.get("shadow_trade") or {}).get("status") in (
        "skipped",
        None,
    ) or out.get("shadow_trade", {}).get("shadow_trade_id"), out
    session.rollback()
    print("verify_shadow_l0_on_alpha_block: PASS")


if __name__ == "__main__":
    main()
