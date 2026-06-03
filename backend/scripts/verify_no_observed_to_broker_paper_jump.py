"""No setup may jump from observed (L0) directly to broker paper — ladder + gates required."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.shadow_league_constants import LEVEL_OBSERVED, LEVEL_PAPER_CANDIDATE  # noqa: E402
from app.services.shadow_promotion_ladder_service import ShadowPromotionLadderService  # noqa: E402
from app.services.shadow_trade_service import ShadowTradeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = {
        "symbol": "ETH/USD",
        "asset_class": "crypto",
        "trade_quality_score": 0.4,
        "push_score": 0.008,
        "entry_allowed": False,
        "no_trade_reason": "NO_EDGE",
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
    }
    out = ShadowTradeService(session, cfg).consider_setup(row, paper_blocked_reason="NO_EDGE")
    obs = out.get("observation") or {}
    assert obs.get("shadow_trade_id") or obs.get("status") in ("exists", "skipped"), obs

    ladder = ShadowPromotionLadderService(session, cfg).ladder_summary()
    assert ladder.get("direct_broker_paper_forbidden") is True
    closest = ladder.get("closest_to_paper_promotion") or {}
    if closest.get("promotion_level") == LEVEL_PAPER_CANDIDATE:
        missing = closest.get("missing_evidence") or []
        assert "cage_preflight_pass" in missing or "alpha_paper_candidate_verdict" in missing, missing

    promo_src = Path(__file__).resolve().parents[1] / "app" / "services" / "shadow_promotion_ladder_service.py"
    assert "PaperExecutionService" not in promo_src.read_text(encoding="utf-8")
    print("verify_no_observed_to_broker_paper_jump: PASS")


if __name__ == "__main__":
    main()
