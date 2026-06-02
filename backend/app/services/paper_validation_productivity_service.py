"""Read-only paper-validation productivity truth.

Explains, in one place, why the bot is or is not producing candidates/trades — symbols scanned vs
scored vs blocked (by data / alpha / edge-after-cost / portfolio-risk / preflight), the current best
candidate, the exact next blocker, what evidence is missing, and whether the engine is watching,
waiting, or broken. Aggregates existing read models only: NO order path, NO mutation, NO live change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def build_productivity(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    if config is not None:
        cfg = config
    else:
        cfg = _safe(lambda: __import__("app.services.config_manager", fromlist=["ConfigManager"]).ConfigManager(session).get_current_readonly(), {})

    uni = _safe(lambda: __import__("app.services.universe_summary_service", fromlist=["build_universe_summary"]).build_universe_summary(session, cfg), {})
    funnel = uni.get("funnel_counts") or {}
    blockers = uni.get("blocker_summary") or []
    bd = {str(b.get("code")): int(b.get("count") or 0) for b in blockers if b.get("code")}

    explo = _safe(lambda: __import__("app.services.paper_exploration_service", fromlist=["PaperExplorationService"]).PaperExplorationService(session, cfg).status(), {})
    ds = _safe(lambda: __import__("app.services.autopilot_decision_state_service", fromlist=["AutopilotDecisionStateService"]).AutopilotDecisionStateService(session, cfg).state(), {})
    alpha = _safe(lambda: __import__("app.services.alpha_research_read_model_service", fromlist=["AlphaResearchReadModelService"]).AlphaResearchReadModelService(session, cfg).status(), {})

    scanned = int(funnel.get("available") or 0)
    scored = int(funnel.get("ranked") or 0)
    eligible = int(funnel.get("eligible") or 0)
    shortlist = int(funnel.get("execution_shortlist") or 0)
    paper_candidates = int(alpha.get("paper_candidate_count") or 0)

    def _sum(pred) -> int:
        return sum(v for k, v in bd.items() if pred(k.lower()))

    blocked_by_data = _sum(lambda k: "stale" in k or "no_quote" in k or "no_bar" in k or "data" in k)
    blocked_by_alpha = _sum(lambda k: "alpha" in k or "no_scorecard" in k)
    blocked_by_edge = _sum(lambda k: "edge" in k or "cost" in k)
    blocked_by_portfolio = _sum(lambda k: "portfolio" in k or "risk" in k or "exposure" in k or "cap" in k)
    blocked_by_preflight = _sum(lambda k: "preflight" in k or "kill_switch" in k or "spread" in k or "min_notional" in k)

    candidate = explo.get("current_exploration_candidate") or {}
    explo_block = explo.get("paper_exploration_block_reason")
    why_not = ds.get("why_not_trading")
    next_blocker = blockers[0] if blockers else None

    # Zero-candidate exact reason classification.
    if paper_candidates > 0:
        zero_reason = None
    elif scanned == 0:
        zero_reason = "NO_DATA_NO_SCAN"
    elif explo_block:
        zero_reason = f"EXPLORATION_BLOCKED:{explo_block}"
    elif blocked_by_data and blocked_by_data >= max(blocked_by_alpha, blocked_by_edge):
        zero_reason = "STALE_QUOTE_OR_BAR"
    elif blocked_by_alpha and blocked_by_alpha >= max(blocked_by_edge, blocked_by_portfolio):
        zero_reason = "NO_ALPHA_SCORECARD"
    elif blocked_by_edge:
        zero_reason = "NEGATIVE_EDGE_AFTER_COST"
    elif blocked_by_portfolio:
        zero_reason = "PORTFOLIO_OR_RISK_CAP"
    elif blocked_by_preflight:
        zero_reason = "PREFLIGHT_OR_KILL_SWITCH"
    elif candidate and str(candidate.get("verdict")) == "unproven":
        zero_reason = "EXPLORATION_CANDIDATE_UNPROVEN_INSUFFICIENT_SAMPLE"
    elif eligible == 0:
        zero_reason = "SCANNED_BUT_NONE_ELIGIBLE_YET"
    else:
        zero_reason = "WATCHING_NO_FORCED_ENTRY"

    # Engine state.
    if uni.get("status") not in ("ok", None) or (alpha.get("status") not in ("ok", None) and alpha):
        engine_state = "degraded"
    elif scanned == 0:
        engine_state = "waiting_for_scan"
    elif why_not == "heartbeat_only_tick_no_forced_entry" or (eligible == 0 and scanned > 0):
        engine_state = "watching"
    elif eligible > 0:
        engine_state = "evaluating_candidates"
    else:
        engine_state = "watching"

    return {
        "status": "ok",
        "generated_at": _now(),
        "validation_run_id": uni.get("validation_run_id"),
        "engine_state": engine_state,  # watching / waiting_for_scan / evaluating_candidates / degraded
        "symbols_scanned": scanned,
        "symbols_scored": scored,
        "symbols_eligible": eligible,
        "execution_shortlist": shortlist,
        "paper_candidates": paper_candidates,
        "blocked_breakdown": {
            "by_data": blocked_by_data,
            "by_alpha": blocked_by_alpha,
            "by_edge_after_cost": blocked_by_edge,
            "by_portfolio_or_risk": blocked_by_portfolio,
            "by_preflight_or_kill_switch": blocked_by_preflight,
            "raw": bd,
        },
        "current_best_candidate": (
            {
                "symbol": candidate.get("symbol"),
                "strategy_family": candidate.get("strategy_family"),
                "verdict": candidate.get("verdict"),
                "edge_after_cost_bps": candidate.get("edge_after_cost_bps"),
                "broker_valid_for_exploration": candidate.get("broker_valid_for_exploration"),
            }
            if candidate
            else None
        ),
        "exact_next_blocker": next_blocker,
        "zero_candidate_reason": zero_reason,
        "missing_evidence": (
            "Needs >=20 closed paper trades + PF>1.10 + positive after-cost expectancy to promote a paper candidate."
            if paper_candidates == 0
            else None
        ),
        "stock_lane": {
            "mode": (uni.get("policy") or {}).get("stock_lane_mode"),
            "stock_entries_allowed": (uni.get("policy") or {}).get("stock_entries_allowed"),
        },
        "crypto_active": (uni.get("policy") or {}).get("crypto_active"),
        "why_not_trading": why_not,
        "live_trading_locked": True,
        "orders_authority": "none",
        "note": "Read-only productivity truth — never trades. Heartbeat watches every candle; only "
                "evidence-backed, cage-approved candidates may trade.",
    }
