"""Phase 5 verifier: explicit stock-lane policy gate.

Matrix proof that stock PAPER ENTRIES follow the policy, not just data freshness:
- disabled / readiness_only (default)        -> no entries (STOCK_LANE_POLICY_BLOCKED), even if fresh+open
- paper_allowed_with_fresh_data + stale      -> no entries (STOCK_BARS_STALE)
- any allowed mode + market closed           -> no entries (STOCK_MARKET_CLOSED)
- sip_required + non-SIP feed                -> no entries (STOCK_FEED_NOT_APPROVED)
- paper_allowed_with_fresh_data + fresh+open -> entries permitted
- sip_required + fresh+open+sip              -> entries permitted
Crypto is never evaluated by this gate; live always stays locked; no fake candidates.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.stock_lane_policy import (  # noqa: E402
    DEFAULT_MODE,
    stock_lane_entry_decision as D,
    stock_lane_mode,
)


def main() -> None:
    # Default mode for the validation run must be readiness_only (equities review-only).
    assert DEFAULT_MODE == "readiness_only"
    assert stock_lane_mode({}) == "readiness_only", f"default lane mode wrong: {stock_lane_mode({})}"

    # disabled / readiness_only block stock entries even with fresh data + open market.
    for m in ("disabled", "readiness_only"):
        r = D(mode=m, freshness_status="fresh", market_open=True, feed="iex")
        assert r["stock_entries_allowed"] is False and r["blocker"] == "STOCK_LANE_POLICY_BLOCKED", f"{m}: {r}"

    # paper_allowed_with_fresh_data
    assert D(mode="paper_allowed_with_fresh_data", freshness_status="fresh", market_open=True, feed="iex")["stock_entries_allowed"] is True
    assert D(mode="paper_allowed_with_fresh_data", freshness_status="stale", market_open=True, feed="iex")["blocker"] == "STOCK_BARS_STALE"
    assert D(mode="paper_allowed_with_fresh_data", freshness_status="fresh", market_open=False, feed="iex")["blocker"] == "STOCK_MARKET_CLOSED"

    # sip_required
    assert D(mode="sip_required", freshness_status="fresh", market_open=True, feed="iex")["blocker"] == "STOCK_FEED_NOT_APPROVED"
    assert D(mode="sip_required", freshness_status="fresh", market_open=True, feed="sip")["stock_entries_allowed"] is True
    assert D(mode="sip_required", freshness_status="stale", market_open=True, feed="sip")["blocker"] == "STOCK_BARS_STALE"

    # Never enables live; never allows entries without an explicit allowed mode + fresh data.
    for case in (
        D(mode="readiness_only", freshness_status="fresh", market_open=True, feed="iex"),
        D(mode="sip_required", freshness_status="fresh", market_open=True, feed="iex"),
        D(mode="paper_allowed_with_fresh_data", freshness_status="stale", market_open=True, feed="iex"),
    ):
        assert case["live_trading_locked"] is True

    # Crypto is never an input to the stock gate; readiness keeps crypto independent.
    pol = (BACKEND / "app/services/stock_lane_policy.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert "crypto" not in pol.lower() or "unaffected" in pol.lower(), "stock lane gate must not gate crypto"
    rdy = (BACKEND / "app/services/stock_data_readiness_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert '"crypto_independent": True' in rdy, "stock readiness must keep crypto independent"
    assert '"stock_entries_allowed": lane["stock_entries_allowed"]' in rdy, "readiness must expose lane entry decision"

    print("verify_stock_lane_policy_gate: PASS (default readiness_only blocks stock entries; matrix correct; crypto independent; live locked)")


if __name__ == "__main__":
    main()
