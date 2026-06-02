"""Explicit stock-lane policy gate.

Equities must not enter paper validation under weak data assumptions. The lane mode decides whether
stock PAPER ENTRIES are permitted at all; crypto is a separate 24/7 lane and is never affected here.

Modes:
* disabled                     — stock lane fully off (no entries; readiness may still be viewed).
* readiness_only               — DEFAULT for paper_validation_run_001: readiness checks only, no entries.
* paper_allowed_with_fresh_data— stock paper entries allowed only when market open + bars fresh.
* sip_required                 — like above, but additionally requires an approved SIP feed.

Entry blockers: STOCK_LANE_POLICY_BLOCKED / STOCK_BARS_STALE / STOCK_FEED_NOT_APPROVED /
STOCK_MARKET_CLOSED. This module only ever BLOCKS stock entries — it never enables live, never
loosens crypto, and never fabricates candidates.
"""

from __future__ import annotations

from typing import Any, Optional

VALID_MODES = ("disabled", "readiness_only", "paper_allowed_with_fresh_data", "sip_required")
DEFAULT_MODE = "readiness_only"
APPROVED_SIP_FEEDS = ("sip",)


def stock_lane_mode(config: Optional[dict] = None) -> str:
    """Resolve the active stock-lane mode: env/settings override → config → default readiness_only."""
    try:
        from app.config import settings

        env = str(getattr(settings, "stock_lane_mode", "") or "").strip().lower()
        if env in VALID_MODES:
            return env
    except Exception:
        pass
    try:
        from app.services.engine_config import cfg_get

        cfg = str(cfg_get(config or {}, "stock_lane.mode", "") or "").strip().lower()
        if cfg in VALID_MODES:
            return cfg
    except Exception:
        pass
    return DEFAULT_MODE


def stock_lane_entry_decision(
    *,
    mode: str,
    freshness_status: Optional[str],
    market_open: bool,
    feed: Optional[str] = None,
    subscription: Optional[str] = None,
) -> dict[str, Any]:
    """Decide whether stock PAPER ENTRIES are permitted under the policy + data conditions.

    Returns {stock_entries_allowed, blocker, reason, mode}. Crypto is unaffected (never evaluated here).
    """
    m = (mode or DEFAULT_MODE).lower()
    feed_l = (feed or "").lower()

    if m in ("disabled", "readiness_only"):
        return _blocked(m, "STOCK_LANE_POLICY_BLOCKED",
                        f"Stock lane policy is '{m}' — stock paper entries are not permitted (crypto unaffected).")

    if not market_open:
        return _blocked(m, "STOCK_MARKET_CLOSED", "U.S. stock market is closed — no stock paper entries.")
    if freshness_status != "fresh":
        return _blocked(m, "STOCK_BARS_STALE",
                        f"Stock bars are '{freshness_status}' — entries require fresh bars.")
    if m == "sip_required" and feed_l not in APPROVED_SIP_FEEDS:
        return _blocked(m, "STOCK_FEED_NOT_APPROVED",
                        f"Policy requires an approved SIP feed; active feed is '{feed_l or 'unknown'}'.")

    return {
        "mode": m,
        "stock_entries_allowed": True,
        "blocker": None,
        "reason": f"Stock paper entries permitted under '{m}' (market open, bars fresh"
                  + (", SIP approved" if m == "sip_required" else "") + ").",
        "live_trading_locked": True,
    }


def _blocked(mode: str, code: str, reason: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "stock_entries_allowed": False,
        "blocker": code,
        "reason": reason,
        "live_trading_locked": True,
    }
