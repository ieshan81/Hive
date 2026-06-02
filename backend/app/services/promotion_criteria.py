"""Single authoritative source for promotion criteria.

Two clearly-named, non-conflicting concepts (NO new thresholds invented — both read existing config):

* operational_readiness_check  — early operational signal that the paper plumbing works
  (default 7 paper days / 5 closed trades). This is NOT a live-ready signal and never controls
  live / pre-live promotion.
* promotion_to_pre_live_criteria — the STRICTER gate that actually governs live / pre-live
  promotion (default 90 calendar days / 100 closed trades / max drawdown).

Live / pre-live promotion is governed ONLY by promotion_to_pre_live_criteria. Live always stays
locked regardless of any criterion here.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.engine_config import cfg_get

# The authoritative criteria set that controls live / pre-live promotion.
CONTROLS_LIVE_PRE_LIVE = "promotion_to_pre_live_criteria"


def operational_readiness_criteria(config: dict) -> dict[str, Any]:
    c = dict((config or {}).get("promotion_readiness") or {})
    return {
        "name": "operational_readiness_check",
        "purpose": "Early operational signal that paper plumbing works — NOT a live-ready signal.",
        "min_paper_days": int(c.get("min_paper_days", 7)),
        "min_closed_paper_trades": int(c.get("min_closed_paper_trades", 5)),
        "min_expectancy_pct": float(c.get("min_expectancy_pct", 0.0)),
        "max_drawdown_pct": float(c.get("max_drawdown_pct", 15.0)),
        "controls_live_pre_live_promotion": False,
    }


def promotion_to_pre_live_criteria(config: dict) -> dict[str, Any]:
    c = dict(cfg_get(config, "promotion.criteria.paper_to_pre_live", {}) or {})
    return {
        "name": "promotion_to_pre_live_criteria",
        "purpose": "Authoritative gate that governs live / pre-live promotion.",
        "min_calendar_days": int(c.get("min_calendar_days", 90)),
        "min_closed_trades": int(c.get("min_closed_trades", 100)),
        "max_drawdown_pct": float(c.get("max_drawdown_pct", 15.0)),
        "controls_live_pre_live_promotion": True,
    }


def authoritative_promotion_criteria(config: dict, *, session: Any = None) -> dict[str, Any]:
    """The single source of truth all promotion consumers + diagnostics report."""
    op = operational_readiness_criteria(config)
    pre = promotion_to_pre_live_criteria(config)
    run_id: Optional[str] = None
    if session is not None:
        try:
            from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch

            epoch = get_latest_reset_epoch(session) or {}
            run_id = epoch.get("validation_run_id") or (PAPER_VALIDATION_RUN_ID if epoch else None)
        except Exception:
            run_id = None
    return {
        "criteria_source": "promotion_criteria.authoritative_promotion_criteria",
        "active_validation_run_id": run_id,
        "operational_readiness_check": op,
        "promotion_to_pre_live_criteria": pre,
        "controls_live_pre_live_promotion": CONTROLS_LIVE_PRE_LIVE,
        "live_pre_live_governed_by": pre["name"],
        "shift_to_live_allowed": False,
        "live_trading_locked": True,
        "note": (
            "operational_readiness_check is an early signal only; live / pre-live promotion is "
            "governed solely by promotion_to_pre_live_criteria (the stricter policy)."
        ),
    }
