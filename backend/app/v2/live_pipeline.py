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
    pipe = funnel.get("pipeline") or {}
    f = pipe.get("funnel") or funnel.get("funnel") or {}
    shortlist = pipe.get("shortlist") or funnel.get("shortlist") or []
    blockers = funnel.get("block_breakdown") or {}
    zero_reason = None
    if not shortlist:
        top = sorted(blockers.items(), key=lambda x: -x[1])[:3]
        if top:
            zero_reason = "; ".join(f"{k}: {v}" for k, v in top)
        else:
            zero_reason = "No symbol passed freshness + edge gates yet — run cycle to refresh bars."
    return {
        "status": funnel.get("status", "ok"),
        "watchlist": wl,
        "funnel": {
            "available": int(f.get("available") or wl.get("usd_pairs") or 0),
            "cached": int(f.get("cached") or 0),
            "fresh": int(f.get("fresh") or 0),
            "eligible": int(f.get("eligible") or funnel.get("eligible_count") or 0),
            "ranked": int(f.get("ranked") or funnel.get("ranked_count") or 0),
            "shortlist": int(f.get("execution_shortlist") or len(shortlist)),
        },
        "shortlist": shortlist[:10],
        "block_breakdown": blockers,
        "why_zero_shortlist": zero_reason,
        "evaluated_symbols": funnel.get("evaluated_symbols"),
        "degraded": bool(funnel.get("degraded")),
    }
