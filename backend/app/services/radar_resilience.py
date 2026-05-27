"""Graceful degradation for hybrid radar / crypto readiness — never 500 on Alpaca limits."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import AlpacaAdapter
from app.services.alpaca_crypto_assets import fetch_crypto_assets
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.universe_mode_service import get_universe_mode

_LAST_SUCCESS: dict[str, Any] = {"at": None, "payload": None}
_RATE_LIMIT_RETRY_AFTER_SEC = 90


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def alpaca_rate_limited(session: Session) -> bool:
    adapter = AlpacaAdapter(session)
    return bool(getattr(adapter, "broker_sync_rate_limited", False))


def record_radar_success(payload: dict[str, Any]) -> None:
    global _LAST_SUCCESS
    _LAST_SUCCESS = {"at": _now(), "payload": payload}


def last_successful_scan() -> dict[str, Any]:
    return {
        "last_successful_scan": _LAST_SUCCESS.get("at"),
        "cached_snapshot_available": bool(_LAST_SUCCESS.get("payload")),
    }


def degraded_meta(
    session: Session,
    *,
    reason: str,
    cached_data_used: bool = False,
    stale_symbols: Optional[list[str]] = None,
    unavailable_symbols: Optional[list[str]] = None,
    paper_trade_allowed: bool = False,
) -> dict[str, Any]:
    retry_after = None
    if reason == "alpaca_rate_limited":
        retry_after = _RATE_LIMIT_RETRY_AFTER_SEC
    return {
        "status": "degraded",
        "reason": reason,
        "cached_data_used": cached_data_used,
        "retry_after_seconds": retry_after,
        **last_successful_scan(),
        "stale_symbols": stale_symbols or [],
        "unavailable_symbols": unavailable_symbols or [],
        "execution_shortlist": [],
        "paper_trade_allowed": paper_trade_allowed,
        "paper_broker": True,
        "live_lock_status": "locked",
    }


def minimal_radar_counts(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    assets = fetch_crypto_assets(force=False) or {}
    usd_pairs = sorted(s for s in assets.keys() if s.endswith("/USD"))
    max_eval = int(cfg_get(cfg, "universe.max_scanned_symbols_per_cycle", 36) or 36)
    return {
        "available_usd_pairs": len(usd_pairs),
        "cached_usd_pairs": len(usd_pairs),
        "evaluated": min(len(usd_pairs), max_eval),
        "eligible": 0,
        "ranked": 0,
        "execution_shortlist": 0,
    }


def build_degraded_radar_snapshot(
    session: Session,
    config: Optional[dict],
    *,
    reason: str,
    error: Optional[str] = None,
    cached_data_used: bool = False,
) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    cached = _LAST_SUCCESS.get("payload") or {}
    counts = minimal_radar_counts(session, cfg)
    if cached_data_used and cached:
        counts = {**counts, **(cached.get("counts") or {})}

    return {
        "generated_at_utc": _now(),
        "active_mode": get_universe_mode(cfg),
        "pipeline": cached.get("pipeline") or {"funnel": {"available": counts["available_usd_pairs"], "cached": counts["cached_usd_pairs"], "eligible": 0, "ranked": 0, "execution_shortlist": 0}},
        "execution_shortlist": [],
        "ranked_candidates": [],
        "lesser_known_highlights": cached.get("lesser_known_highlights") or [],
        "tier_counts": cached.get("tier_counts") or {},
        "tier_samples": cached.get("tier_samples") or {},
        "funnel": cached.get("funnel") or {},
        "block_breakdown": cached.get("block_breakdown") or {},
        "answer": f"Radar degraded — {reason}. Using cached snapshot where available.",
        "counts": counts,
        "labels": cached.get("labels") or {},
        "error_type": error,
        **degraded_meta(
            session,
            reason=reason,
            cached_data_used=cached_data_used,
            paper_trade_allowed=False,
        ),
    }
