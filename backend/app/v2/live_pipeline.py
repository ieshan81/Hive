"""Six-stage funnel — computed live per request (research workflow)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.universe_strategy_discovery_service import build_funnel_breakdown
from app.v2.watchlist import live_crypto_watchlist


def live_funnel(session: Session, config: Optional[dict] = None, *, max_evaluate: int = 36) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    wl = live_crypto_watchlist(force=True)
    funnel = build_funnel_breakdown(
        session,
        cfg,
        max_evaluate=max_evaluate,
        fetch_quotes=False,
    )
    from app.services.push_pull_scoring_service import score_active_universe
    from app.services.scan_limits import scan_limit

    eval_limit = scan_limit(cfg, "universe.max_scanned_symbols_per_cycle", max_evaluate)
    scored = score_active_universe(session, cfg, limit=eval_limit)
    scored_fresh = int(scored.get("fresh_count") or 0)
    scored_eligible = int(scored.get("eligible_count") or 0)
    scored_breakdown = scored.get("no_trade_reason_breakdown") or {}

    pipe = funnel.get("pipeline") or {}
    f = pipe.get("funnel") or funnel.get("funnel") or {}
    shortlist = pipe.get("shortlist") or funnel.get("shortlist") or []
    if scored_eligible:
        shortlist = [row for row in (scored.get("scores") or []) if row.get("entry_allowed")]
    blockers = funnel.get("block_breakdown") or {}
    if scored_breakdown:
        blockers = {**blockers, **scored_breakdown}
    zero_reason = None
    if not shortlist:
        top = sorted(blockers.items(), key=lambda x: -x[1])[:3]
        if top:
            labels = funnel.get("block_breakdown_labels") or {}
            zero_reason = "; ".join(
                f"{labels.get(k, k.replace('_', ' '))}: {v}" if labels.get(k) else f"{k}: {v}"
                for k, v in top
            )
        else:
            zero_reason = "No symbol passed freshness + edge gates yet — run cycle to refresh bars."
    fresh_n = max(int(f.get("fresh") or 0), scored_fresh)
    eligible_n = max(int(f.get("eligible") or funnel.get("eligible_count") or 0), scored_eligible)
    return {
        "status": funnel.get("status", "ok"),
        "watchlist": wl,
        "funnel": {
            "available": int(f.get("available") or wl.get("usd_pairs") or 0),
            "cached": int(f.get("cached") or f.get("available") or wl.get("usd_pairs") or 0),
            "fresh": fresh_n,
            "eligible": eligible_n,
            "ranked": int(scored.get("symbols_scored") or f.get("ranked") or funnel.get("ranked_count") or 0),
            "shortlist": len(shortlist) if shortlist else eligible_n,
        },
        "shortlist": shortlist[:10],
        "block_breakdown": blockers,
        "why_zero_shortlist": zero_reason,
        "evaluated_symbols": funnel.get("evaluated_symbols"),
        "degraded": bool(funnel.get("degraded")),
    }
