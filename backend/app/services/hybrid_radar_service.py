"""Hybrid Radar Mode — full universe scan, cache, tiering, funnel, shortlist."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_crypto_assets import fetch_crypto_assets
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.radar_resilience import (
    alpaca_rate_limited,
    build_degraded_radar_snapshot,
    record_radar_success,
)
from app.services.symbol_tier_service import (
    TIER_ALT,
    TIER_BLOCKED,
    TIER_MAJOR,
    TIER_MEME_SUPPORTED,
    TIER_WATCH,
    SymbolTierService,
)
from app.services.universe_mode_service import get_universe_mode
from app.services.universe_ranking_service import rank_universe
from app.services.universe_strategy_discovery_service import build_funnel_breakdown
from app.services.universe_sources_service import universe_sources

logger = logging.getLogger(__name__)

TIER_LABELS = {
    TIER_MAJOR: "tier_1_major_liquid",
    TIER_ALT: "tier_2_alt_momentum",
    TIER_MEME_SUPPORTED: "tier_2_alt_momentum",
    TIER_WATCH: "tier_3_watch_speculative",
    TIER_BLOCKED: "tier_4_blocked",
}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def hybrid_radar_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    mode = get_universe_mode(cfg)
    src = universe_sources(session, cfg)
    try:
        funnel = build_funnel_breakdown(
            session,
            cfg,
            max_evaluate=int(cfg_get(cfg, "universe.max_scanned_symbols_per_cycle", 36) or 36),
            fetch_quotes=False,
        )
    except Exception as exc:
        logger.warning("hybrid_radar_status degraded: %s", exc)
        funnel = {"status": "degraded", "reason": "radar_build_failed", "answer": str(exc)[:200]}
    status = funnel.get("status", "ok")
    return {
        "status": status if status in ("ok", "degraded") else "degraded",
        "generated_at_utc": _now(),
        "active_mode": mode,
        "mode_label": "Hybrid Radar" if mode == "hybrid_radar" else mode.replace("_", " ").title(),
        "pipeline": funnel.get("pipeline"),
        "funnel": funnel.get("funnel"),
        "available_symbols": funnel.get("available_symbols", 0),
        "evaluated_symbols": funnel.get("evaluated_symbols", 0),
        "eligible_count": funnel.get("eligible_count", 0),
        "ranked_count": funnel.get("ranked_count", 0),
        "execution_shortlist_count": funnel.get("execution_shortlist_count", 0),
        "block_breakdown": funnel.get("block_breakdown"),
        "answer": funnel.get("answer"),
        "broker_totals": src.get("source_counts"),
        "reason": funnel.get("reason"),
        "config": {
            "max_execution_shortlist": int(cfg_get(cfg, "universe.max_execution_shortlist", 3) or 3),
            "max_scanned_symbols_per_cycle": int(
                cfg_get(cfg, "universe.max_scanned_symbols_per_cycle", 36) or 36
            ),
            "speculative_paper_exploration": bool(
                cfg_get(cfg, "universe.speculative_paper_exploration", True)
            ),
        },
    }


def hybrid_radar_snapshot(
    session: Session, config: Optional[dict] = None, *, fetch_quotes: bool = True
) -> dict[str, Any]:
    """Full radar payload for UI — cache, tiers, ranked, shortlist. Never raises."""
    cfg = config or ConfigManager(session).get_current()
    rate_limited = alpaca_rate_limited(session)
    if rate_limited:
        fetch_quotes = False

    try:
        from app.services.scan_limits import scan_limit, slice_limit, zero_means_unlimited

        max_eval = scan_limit(cfg, "universe.max_scanned_symbols_per_cycle", 36)
        max_short_raw = cfg_get(cfg, "universe.max_execution_shortlist", 3)
        max_short = 9999 if zero_means_unlimited(max_short_raw) else max(1, int(max_short_raw))
        max_ranked = scan_limit(cfg, "universe.max_ranked_symbols_per_cycle", 20)

        assets = fetch_crypto_assets(force=False) or {}
        usd_pairs = sorted(s for s in assets.keys() if s.endswith("/USD"))
        tier_svc = SymbolTierService(cfg, broker_supported_symbols=set(usd_pairs))

        funnel = build_funnel_breakdown(session, cfg, max_evaluate=max_eval, fetch_quotes=fetch_quotes)
        pipe = funnel.get("pipeline") or {}
        all_ranked = pipe.get("all_ranked") or []
        ranked = rank_universe(all_ranked, config=cfg)[:max_ranked]
        shortlist = slice_limit([r for r in ranked if not r.get("dropped")], max_short)
        if funnel.get("degraded") or rate_limited:
            shortlist = []

        eligible_count = int(funnel.get("eligible_count") or 0)
        paper_trade_allowed = bool(
            not funnel.get("degraded")
            and not rate_limited
            and eligible_count > 0
            and bool(shortlist)
        )
        tier_counts: dict[str, int] = {}
        tier_samples: dict[str, list[str]] = {}
        for sym in usd_pairs[:max_eval]:
            info = tier_svc.classify(sym)
            label = TIER_LABELS.get(info.tier, info.tier)
            tier_counts[label] = tier_counts.get(label, 0) + 1
            tier_samples.setdefault(label, [])
            if len(tier_samples[label]) < 5:
                tier_samples[label].append(sym)

        payload = {
            "status": "degraded" if (funnel.get("degraded") or rate_limited) else "ok",
            "generated_at_utc": _now(),
            "active_mode": get_universe_mode(cfg),
            "reason": "alpaca_rate_limited" if rate_limited else funnel.get("reason"),
            "cached_data_used": bool(funnel.get("cached_data_used")),
            "retry_after_seconds": funnel.get("retry_after_seconds"),
            "stale_symbols": funnel.get("stale_symbols") or [],
            "unavailable_symbols": funnel.get("unavailable_symbols") or [],
            "paper_trade_allowed": paper_trade_allowed,
            "pipeline": pipe,
            "execution_shortlist": shortlist,
            "labels": {
                "available": "Radar scanned available assets",
                "cached": "Cached assets",
                "fresh": "Fresh data count",
                "eligible": "Eligible assets",
                "ranked": "Top ranked candidates",
                "shortlist": "Execution shortlist",
            },
            "counts": {
                "available_usd_pairs": len(usd_pairs),
                "cached_usd_pairs": len(usd_pairs),
                "evaluated": funnel.get("evaluated_symbols", 0),
                "eligible": funnel.get("eligible_count", 0),
                "ranked": len([r for r in ranked if not r.get("dropped")]),
                "execution_shortlist": len(shortlist),
            },
            "funnel": funnel.get("funnel"),
            "block_breakdown": funnel.get("block_breakdown"),
            "answer": funnel.get("answer"),
            "tier_counts": tier_counts,
            "tier_samples": tier_samples,
            "ranked_candidates": ranked[:max_ranked],
            "lesser_known_highlights": [
                r for r in ranked
                if r.get("symbol") in ("HYPE/USD", "RENDER/USD", "FIL/USD", "ONDO/USD", "GRT/USD", "ARB/USD")
            ][:8],
        }
        if payload["status"] == "ok":
            record_radar_success(payload)
        return payload
    except Exception as exc:
        logger.exception("hybrid_radar_snapshot failed: %s", exc)
        reason = "alpaca_rate_limited" if rate_limited else "radar_build_failed"
        return build_degraded_radar_snapshot(
            session,
            cfg,
            reason=reason,
            error=type(exc).__name__,
            cached_data_used=True,
        )


def universe_tiers(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    assets = fetch_crypto_assets(force=False) or {}
    usd_pairs = sorted(s for s in assets.keys() if s.endswith("/USD"))
    tier_svc = SymbolTierService(cfg, broker_supported_symbols=set(usd_pairs))
    buckets: dict[str, list[dict]] = {
        "tier_1_major_liquid": [],
        "tier_2_alt_momentum": [],
        "tier_3_watch_speculative": [],
        "tier_4_blocked": [],
    }
    for sym in usd_pairs:
        info = tier_svc.classify(sym)
        label = TIER_LABELS.get(info.tier, "tier_4_blocked")
        buckets.setdefault(label, []).append(
            {
                "symbol": sym,
                "tier": label,
                "trade_eligible": info.trade_eligible,
                "order_path_allowed": info.order_path_allowed,
                "watch_only_reason": info.watch_only_reason,
            }
        )
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "tiers": buckets,
        "counts": {k: len(v) for k, v in buckets.items()},
    }
