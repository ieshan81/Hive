"""Phase 4 verifier: one authoritative promotion-criteria source, consistently reported.

Proves: operational_readiness_check (7/5) and promotion_to_pre_live_criteria (90/100) are distinct
and clearly labeled; the authoritative summary says live/pre-live promotion is governed ONLY by the
stricter pre-live criteria; PromotionService, PromotionReadinessService, and the diagnostics bundle
all read the same source; a 7/5 system cannot be marked live-ready; live stays locked.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.promotion_criteria import (  # noqa: E402
    authoritative_promotion_criteria,
    operational_readiness_criteria,
    promotion_to_pre_live_criteria,
)


def main() -> None:
    # Defaults (empty config) — must match the repo's documented thresholds, no new values invented.
    op = operational_readiness_criteria({})
    pre = promotion_to_pre_live_criteria({})
    assert op["min_paper_days"] == 7 and op["min_closed_paper_trades"] == 5, f"operational defaults wrong: {op}"
    assert op["controls_live_pre_live_promotion"] is False, "operational check must NOT control live"
    assert pre["min_calendar_days"] == 90 and pre["min_closed_trades"] == 100, f"pre-live defaults wrong: {pre}"
    assert pre["controls_live_pre_live_promotion"] is True, "pre-live criteria must control live"

    auth = authoritative_promotion_criteria({})
    assert auth["controls_live_pre_live_promotion"] == "promotion_to_pre_live_criteria"
    assert auth["live_pre_live_governed_by"] == "promotion_to_pre_live_criteria"
    assert auth["shift_to_live_allowed"] is False and auth["live_trading_locked"] is True
    assert auth["operational_readiness_check"]["min_closed_paper_trades"] == 5
    assert auth["promotion_to_pre_live_criteria"]["min_closed_trades"] == 100

    # All three consumers read the same authoritative source (static check).
    ps = (BACKEND / "app/services/promotion_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    pr = (BACKEND / "app/services/promotion_readiness_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    bundle = (BACKEND / "app/services/diagnostic_bundle_latest.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert "authoritative_promotion_criteria" in ps, "PromotionService not using authoritative source"
    assert "promotion_to_pre_live_criteria" in pr and "authoritative_promotion_criteria" in pr, \
        "PromotionReadinessService not using authoritative source"
    assert "authoritative_promotion_criteria" in bundle and "promotion_criteria.json" in bundle, \
        "diagnostics bundle not reporting authoritative criteria"

    # 7/5 alone cannot mark the system live-ready — pre-live REQUEST requires the stricter gate.
    assert "ready_for_tiny_live_request = operational_ready and pre_live_ready" in pr, \
        "readiness must require stricter pre-live criteria for live-readiness"
    assert "pre_live_ready = days >= pre[\"min_calendar_days\"] and len(closed) >= pre[\"min_closed_trades\"]" in pr, \
        "pre_live_ready must use the 90/100 stricter criteria"

    print("verify_promotion_criteria_single_source: PASS (single source; pre-live (90/100) governs live; 7/5 operational-only; live locked)")


if __name__ == "__main__":
    main()
