"""Stale stock data may create shadow records but stock lane still blocks paper entries."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.shadow_trade_service import ShadowTradeService, classify_shadow_data_quality  # noqa: E402
from app.services.stock_lane_policy import stock_lane_entry_decision, stock_lane_mode  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = {
        "symbol": "AAPL",
        "asset_class": "stock",
        "trade_quality_score": 0.5,
        "push_score": 0.01,
        "entry_allowed": False,
        "bar_freshness": "stale",
        "quote_freshness": "stale",
        "market_open": True,
    }
    dq, _note = classify_shadow_data_quality(row, cfg)
    assert dq in ("stale", "not_broker_quality", "delayed"), dq
    mode = stock_lane_mode(cfg)
    lane = stock_lane_entry_decision(mode=mode, freshness_status="stale", market_open=True)
    assert lane.get("stock_entries_allowed") is False, lane

    svc = ShadowTradeService(session, cfg)
    out = svc.consider_setup(row, strategy_id="stock_push_pull_baseline", paper_blocked_reason="STOCK_BARS_STALE")
    st = out.get("shadow_trade") or {}
    assert st.get("shadow_trade_id") or st.get("status") in ("skipped",), out
    if st.get("data_quality"):
        assert st["data_quality"] != "execution_grade" or dq == "execution_grade"
    print("verify_stock_stale_creates_shadow_not_paper: PASS")


if __name__ == "__main__":
    main()
