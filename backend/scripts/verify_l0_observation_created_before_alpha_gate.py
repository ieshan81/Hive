"""Alpha-blocked setup must create L0 observation when quality passes observation floor."""

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
        "trade_quality_score": 42.0,
        "push_score": 0.02,
        "entry_allowed": False,
        "no_trade_reason": "ALPHA_NOT_READY:no_alpha_scorecard",
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
    }
    out = ShadowTradeService(session, cfg).consider_setup(
        row,
        strategy_id="crypto_push_pull_baseline",
        paper_blocked_reason="ALPHA_NOT_READY:no_alpha_scorecard",
        paper_submitted=False,
    )
    assert out.get("observation"), f"expected L0: {out}"
    assert float(out.get("quality_on_scale") or 0) >= float(out.get("observation_floor") or 0), out
    session.rollback()
    print("verify_l0_observation_created_before_alpha_gate: PASS")


if __name__ == "__main__":
    main()
