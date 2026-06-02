"""Fast, read-only Universe summary (the fast path behind GET /api/universe/summary).

The full /api/universe/status runs build_mission_control_status (~15s) which makes the UI fall back
to a false-zero. This builds ONLY the universe funnel + cached source proof + policy, with no heavy
scan, no slow Alpaca discovery, no order/broker path. Source counts are NEVER reported as plain 0
when unknown — they are null/unknown instead. Read-only; never mutates orders/trades/live.

Count semantics are kept explicitly separate:
  source_counts   — what the bot can see (Alpaca assets / curated watchlist)
  display_counts  — what the UI displays (configured watchlist universe)
  freshness_counts— bars/quotes readiness (cached/fresh/stale/unknown)
  funnel_counts   — scan funnel (available/eligible/ranked/execution_shortlist/to_trade)
A zero eligible/shortlist NEVER implies a zero source — they are different layers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _age_seconds(iso_ts: Optional[str], now: datetime) -> Optional[float]:
    if not iso_ts:
        return None
    try:
        s = str(iso_ts).replace("Z", "")
        for sign in ("+", "-"):
            if sign in s[10:]:
                s = s[:10] + s[10:].split(sign)[0]
                break
        return round((now - datetime.fromisoformat(s)).total_seconds(), 1)
    except (ValueError, TypeError):
        return None


def build_universe_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    now = datetime.utcnow()

    if config is not None:
        cfg = config
    else:
        try:
            from app.services.config_manager import ConfigManager

            # Read-only: the fast path must never migrate/write config.
            cfg = ConfigManager(session).get_current_readonly()
        except Exception:
            cfg = {}  # fast path must never crash on config read

    # --- fast funnel (a handful of indexed queries; NOT the full mission-control build) ---
    try:
        from app.services.mission_control_read_model import _universe_summary

        universe = _universe_summary(session)
    except Exception:
        universe = {}  # fast path must never crash; degrade to unknown, never a fake zero
    funnel = universe.get("funnel") or {}

    # --- cached source proof only (no slow discovery; unknown -> null, never a fake 0) ---
    from app.services.universe_sources_service import CURATED_CRYPTO, CURATED_STOCKS
    crypto_assets: dict = {}
    try:
        from app.services.alpaca_crypto_assets import fetch_crypto_assets

        crypto_assets = fetch_crypto_assets(force=False) or {}
    except Exception:
        crypto_assets = {}
    has_crypto = bool(crypto_assets)
    usd_pairs = [s for s in crypto_assets if str(s).endswith("/USD")]
    source_counts = {
        "alpaca_crypto_assets": len(crypto_assets) if has_crypto else None,
        "alpaca_crypto_tradable": (sum(1 for a in crypto_assets.values() if a.get("tradable")) if has_crypto else None),
        "alpaca_crypto_usd_pairs": len(usd_pairs) if has_crypto else None,
        "alpaca_stock_assets": None,  # unknown on the fast path (no live stock discovery)
        "curated_crypto": len(CURATED_CRYPTO),
        "curated_stock": len(CURATED_STOCKS),
    }

    # --- display universe (configured watchlist — stable; what the UI shows) ---
    display_counts = {
        "total": len(CURATED_CRYPTO) + len(CURATED_STOCKS),
        "crypto": len(CURATED_CRYPTO),
        "stock": len(CURATED_STOCKS),
    }

    # --- freshness + funnel (scan layers — separate from source/display) ---
    blockers = {b.get("code"): b.get("count") for b in (universe.get("top_blockers") or []) if b.get("code")}
    freshness_counts = {
        "cached": funnel.get("cached"),
        "fresh": funnel.get("fresh"),
        "stale": blockers.get("stale_bar"),  # known stale-bar blocker count, else null
        "unknown": None,
    }
    eligible = int(funnel.get("eligible") or 0)
    available = int(funnel.get("available") or 0)
    funnel_counts = {
        "available": funnel.get("available"),
        "eligible": funnel.get("eligible"),
        "ranked": funnel.get("scored"),
        "execution_shortlist": funnel.get("shortlisted"),
        "to_trade": funnel.get("shortlisted"),
    }

    # --- policy (fast: lane mode + crypto-active; no heavy IEX probe here) ---
    from app.services.stock_lane_policy import stock_lane_mode
    lane_mode = stock_lane_mode(cfg)
    crypto_active = True
    try:
        from app.services.session_engine import SessionEngine

        crypto_active = bool(SessionEngine().detect().crypto_trading_allowed)
    except Exception:
        pass
    policy = {
        "stock_lane_mode": lane_mode,
        "stock_entries_allowed": lane_mode in ("paper_allowed_with_fresh_data", "sip_required"),
        "crypto_active": crypto_active,
    }

    # --- validation run ---
    run_id = None
    try:
        from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch

        epoch = get_latest_reset_epoch(session) or {}
        run_id = epoch.get("validation_run_id") or (PAPER_VALIDATION_RUN_ID if epoch else None)
    except Exception:
        pass

    source_nonzero = any(isinstance(v, int) and v > 0 for v in source_counts.values()) or available > 0
    last_scan = universe.get("last_scan_at")
    return {
        "status": "ok",
        "endpoint_kind": "fast_path",
        "generated_at": _now(),
        "validation_run_id": run_id,
        "source_counts": source_counts,
        "display_counts": display_counts,
        "freshness_counts": freshness_counts,
        "funnel_counts": funnel_counts,
        "policy": policy,
        "blocker_summary": universe.get("top_blockers") or [],
        "zero_eligible_explanation": (
            f"{available} symbols scanned; {eligible} eligible — see blocker_summary."
            if eligible == 0 and available > 0
            else None
        ),
        "source_nonzero_but_eligible_zero": bool(source_nonzero and eligible == 0),
        "last_successful_scan_at": last_scan,
        "data_age_seconds": _age_seconds(last_scan, now),
        "status_latency_risk": True,  # the heavy /api/universe/status can exceed the UI timeout — prefer this
        "counts_meaning": {
            "source_counts": "what the bot can see (Alpaca assets / curated watchlist)",
            "display_counts": "configured watchlist universe shown in the UI",
            "freshness_counts": "bars/quotes readiness (cached/fresh/stale/unknown)",
            "funnel_counts": "scan funnel (available/eligible/ranked/execution_shortlist/to_trade)",
            "note": "eligible/shortlist are strict-gate layers — a zero there does NOT mean zero source/display.",
        },
        "live_trading_locked": True,
        "orders_authority": "none",
    }
