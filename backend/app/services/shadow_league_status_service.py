"""Read-only Shadow League status for minimal UI."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.shadow_league_bundle_service import (
    shadow_trades_summary,
    strategy_promotion_ladder,
    why_no_trade,
)
from app.services.shadow_trade_service import shadow_league_enabled


def build_shadow_league_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.config_manager import ConfigManager

    cfg = config or ConfigManager(session).get_current_readonly()
    if not shadow_league_enabled(cfg):
        return {"status": "disabled", "enabled": False}
    summary = shadow_trades_summary(session, cfg)
    ladder = strategy_promotion_ladder(session, cfg)
    wnt = why_no_trade(session, cfg)
    closest = ladder.get("closest_to_paper_promotion") or {}
    return {
        "status": "ok",
        "enabled": True,
        "shadow_league_count": summary.get("shadow_league_count", 0),
        "open_shadow_trades": summary.get("open_shadow_trades", 0),
        "closest_to_paper_promotion": closest,
        "missing_evidence": closest.get("missing_evidence") or [],
        "by_level": ladder.get("by_level"),
        "why_no_trade_plain": wnt.get("plain"),
        "counts_as_broker_evidence": False,
        "live_trading_locked": True,
        "note": "Shadow league is learning-only; no broker orders.",
    }
