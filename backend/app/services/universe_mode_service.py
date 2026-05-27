"""Universe mode — curated watchlist vs dynamic tradable universe."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.session_engine import SessionEngine
from app.services.universe_builder import build_merged_universe
from app.services.universe_sources_service import CURATED_CRYPTO, CURATED_STOCKS, universe_sources

MODES = ("hybrid_radar", "curated_watchlist", "dynamic_tradable")


def get_universe_mode(config: dict) -> str:
    mode = str(cfg_get(config, "universe.mode", "hybrid_radar") or "hybrid_radar").lower()
    if mode in ("dynamic", "dynamic_tradable"):
        return "dynamic_tradable"
    if mode in ("hybrid", "hybrid_radar", "radar"):
        return "hybrid_radar"
    if mode == "curated_watchlist":
        return "curated_watchlist"
    return "hybrid_radar"


def universe_mode_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    mode = get_universe_mode(cfg)
    sess = SessionEngine().detect()
    src = universe_sources(session, cfg)

    if mode == "hybrid_radar":
        from app.services.alpaca_crypto_assets import fetch_crypto_assets
        from app.services.hybrid_radar_service import hybrid_radar_snapshot

        assets = fetch_crypto_assets(force=False) or {}
        usd_pairs = [s for s in assets.keys() if s.endswith("/USD")]
        radar = hybrid_radar_snapshot(session, cfg, fetch_quotes=False)
        counts = radar.get("counts") or {}
        return {
            "status": radar.get("status", "ok"),
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "active_mode": mode,
            "mode_label": "Hybrid Radar",
            "mode_explanation": (
                "Full broker universe cached and ranked; execution uses a strict shortlist only."
            ),
            "can_switch_to_dynamic": True,
            "can_switch_to_curated": True,
            "config_key": "universe.mode",
            "session": sess.to_dict(),
            "display_counts": {
                "total": counts.get("available_usd_pairs", len(usd_pairs)),
                "active": counts.get("eligible", 0),
                "blocked": max(0, counts.get("evaluated", 0) - counts.get("eligible", 0)),
                "watch_only": counts.get("ranked", 0),
                "crypto": counts.get("available_usd_pairs", len(usd_pairs)),
                "stock": 0,
            },
            "radar_counts": counts,
            "broker_totals": src.get("source_counts"),
            "stocks_session_note": (
                "Stocks currently inactive — U.S. market is closed."
                if not sess.stock_trading_allowed
                else "U.S. stock session allows stock entries when other gates pass."
            ),
            "reason": radar.get("reason"),
        }

    lightweight = mode == "curated_watchlist"
    limit = 80 if lightweight else 120
    rows = build_merged_universe(session, cfg, limit=limit, lightweight=lightweight)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "active_mode": mode,
        "mode_label": {
            "hybrid_radar": "Hybrid Radar",
            "curated_watchlist": "Curated Watchlist",
            "dynamic_tradable": "Dynamic Tradable Universe",
        }.get(mode, mode),
        "mode_explanation": {
            "hybrid_radar": (
                "Full broker universe cached and ranked; execution uses a strict shortlist only."
            ),
            "curated_watchlist": (
                "Small operator-safe subset for lightweight scanning and rate-limit safety."
            ),
            "dynamic_tradable": (
                "Built live from Alpaca tradable assets plus eligibility and freshness filters."
            ),
        }.get(mode, ""),
        "can_switch_to_dynamic": True,
        "can_switch_to_curated": True,
        "config_key": "universe.mode",
        "session": sess.to_dict(),
        "display_counts": {
            "total": len(rows),
            "active": len([r for r in rows if r.get("status") == "Active"]),
            "blocked": len([r for r in rows if r.get("status") == "Blocked"]),
            "watch_only": len([r for r in rows if r.get("status") == "Watch-only"]),
            "crypto": len([r for r in rows if r.get("asset_type") == "Crypto"]),
            "stock": len([r for r in rows if r.get("asset_type") == "Stock"]),
        },
        "broker_totals": src.get("source_counts"),
        "stocks_session_note": (
            "Stocks currently inactive — U.S. market is closed."
            if not sess.stock_trading_allowed
            else "U.S. stock session allows stock entries when other gates pass."
        ),
    }


def universe_filters(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    pp = cfg.get("push_pull") or {}
    risk = cfg.get("risk") or {}
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "active_mode": get_universe_mode(cfg),
        "filters": {
            "max_spread_bps": pp.get("max_spread_bps", 50),
            "min_edge_after_cost_bps": pp.get("min_edge_after_cost_bps", 50),
            "max_bar_age_minutes": pp.get("max_bar_age_minutes", 120),
            "quote_max_age_seconds": (cfg.get("execution") or {}).get("quote_max_age_seconds", 30),
            "require_funded_quote_currency": True,
            "session_stock_entries": SessionEngine().detect().stock_trading_allowed,
            "session_crypto_entries": SessionEngine().detect().crypto_trading_allowed,
            "reconciliation_drift_halt_bps": risk.get("reconciliation_drift_halt_bps", 5),
        },
    }


def universe_block_reasons(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    mode = get_universe_mode(cfg)
    rows = build_merged_universe(session, cfg, limit=120, lightweight=(mode == "curated_watchlist"))
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for r in rows:
        if r.get("status") != "Blocked":
            continue
        reason = str(r.get("blocked_reason") or "unknown")
        key = _normalize_block_reason(reason)
        counts[key] += 1
        examples.setdefault(key, [])
        if len(examples[key]) < 3:
            examples[key].append(r.get("symbol"))

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "active_mode": mode,
        "blocked_total": sum(counts.values()),
        "reason_counts": dict(counts),
        "examples": examples,
    }


def _normalize_block_reason(reason: str) -> str:
    low = reason.lower()
    if "market is closed" in low or "market closed" in low:
        return "market_closed"
    if "stale" in low and "quote" in low:
        return "stale_quote"
    if "stale" in low or "no bars" in low:
        return "stale_bars"
    if "spread" in low:
        return "spread_too_wide"
    if "balance" in low or "usdc" in low or "usdt" in low:
        return "quote_currency_unfunded"
    if "edge" in low or "cost" in low:
        return "negative_edge_after_cost"
    return "other"
