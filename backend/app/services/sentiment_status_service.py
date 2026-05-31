"""Sentiment subsystem status — honest proof of what is active vs inactive."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import settings
from app.database import AIReview, SymbolCandidate
from app.services.config_manager import ConfigManager


def _sentiment_display(config: dict, sources_payload: dict, diagnostics: dict) -> tuple[str, str, str]:
    """Return (display_title, display_subtitle, wiring_state)."""
    fin = sources_payload.get("sources", {}).get("finbert", {})
    news = sources_payload.get("sources", {}).get("news_feed", {})
    fin_active = bool(fin.get("active"))
    news_wired = bool(news.get("provider_wired"))
    scored_count = int(diagnostics.get("latest_scored_symbols_count") or 0)
    used_in_ranking = bool(diagnostics.get("sentiment_used_in_ranking"))
    max_pct = diagnostics.get("max_sentiment_adjustment_pct", 10)

    if not fin.get("wired"):
        return (
            "Configured but not wired end-to-end.",
            "Sentiment service imports or endpoints are incomplete.",
            "not_wired",
        )

    if fin_active and scored_count > 0 and used_in_ranking:
        return (
            f"Sentiment active: ranking modifier only, max ±{max_pct}%.",
            "Headlines scored via FinBERT; never permits trades or bypasses execution cage.",
            "active_ranking",
        )

    if (fin_active or news_wired) and scored_count == 0:
        return (
            "Sources active, no recent symbol sentiment yet.",
            "Run POST /api/sentiment/refresh or wait for scanner scoring to populate cache.",
            "sources_only",
        )

    if fin_active or news_wired:
        return (
            "Sources active, sentiment pipeline ready.",
            f"Ranking influence capped at ±{max_pct}%; advisory only.",
            "ready",
        )

    return (
        "Sentiment sources inactive.",
        "Configure Alpaca credentials and FinBERT (local or FINBERT_SERVICE_URL).",
        "inactive",
    )


def sentiment_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    sources_payload = sentiment_sources(session, cfg)
    from app.services.sentiment_service import sentiment_diagnostics

    diagnostics = sentiment_diagnostics(cfg)
    fin = sources_payload.get("sources", {}).get("finbert", {})
    display_title, display_subtitle, wiring_state = _sentiment_display(cfg, sources_payload, diagnostics)
    influence = bool((cfg.get("sentiment") or {}).get("influence_ranking", True))

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "display_title": display_title,
        "display_subtitle": display_subtitle,
        "wiring_state": wiring_state,
        "sentiment_affects_ranking": influence and bool(diagnostics.get("finbert_model_loaded")),
        "sentiment_affects_trading": False,
        "sentiment_can_place_trades": False,
        "sentiment_influence_ranking": influence,
        "sentiment_influence_trading": False,
        "overall_active": bool(fin.get("active")),
        "max_adjustment_pct": (cfg.get("sentiment") or {}).get("max_adjustment_pct", 10),
        "finbert": {
            "implemented": True,
            "worker_url_configured": diagnostics.get("finbert_worker_configured", False),
            "worker_connected": diagnostics.get("finbert_worker_connected", False),
            "model_loaded": diagnostics.get("finbert_model_loaded", False),
            "active": fin.get("active", False),
        },
        "message": display_subtitle,
        "sources": sources_payload.get("sources"),
        "diagnostics": diagnostics,
    }


def sentiment_sources(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    try:
        from app.services.sentiment_service import FinBERTScorer
        from app.services.finbert_client import finbert_health, finbert_service_url

        remote = finbert_health()
        worker_url = bool(finbert_service_url())
        worker_connected = remote.get("status") in ("ok", "degraded") and remote.get("configured")
        model_loaded = bool(remote.get("model_loaded")) or FinBERTScorer.is_available()
        finbert_active = model_loaded and (worker_connected or FinBERTScorer.is_available())
    except Exception:
        remote = {}
        worker_url = False
        worker_connected = False
        model_loaded = False
        finbert_active = False

    news_provider_wired = bool(settings.alpaca_configured)
    news_active = bool(news_provider_wired and finbert_active)

    from app.services.sentiment_service import get_sentiment_cache_snapshot, sentiment_ranking_enabled

    cache = get_sentiment_cache_snapshot()
    ranking_on = sentiment_ranking_enabled(cfg)

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "sources": {
            "finbert": {
                "active": finbert_active,
                "implemented": True,
                "wired": True,
                "worker_url_configured": worker_url,
                "worker_connected": worker_connected,
                "model_loaded": model_loaded,
                "model": "ProsusAI/finbert",
                "reason": (
                    "FinBERT microservice connected."
                    if worker_connected
                    else (
                        "FinBERT local transformers available."
                        if model_loaded and not worker_connected
                        else "Implemented; inactive until FINBERT_SERVICE_URL healthy or local transformers."
                    )
                ),
            },
            "news_feed": {
                "active": news_active,
                "wired": True,
                "primary_source": "alpaca_benzinga",
                "fallback_sources": ["finnhub", "alpha_vantage", "yahoo_rss"],
                "provider_wired": news_provider_wired,
                "sentiment_scoring_requires_finbert": True,
                "reason": (
                    "Alpaca News (Benzinga) ingester wired and FinBERT available — headline scoring active."
                    if news_active
                    else (
                        "Alpaca News provider is configured, but FinBERT is unavailable — news sentiment scoring is inactive."
                        if news_provider_wired
                        else "Implemented; inactive until Alpaca credentials configured."
                    )
                ),
            },
            "symbol_candidate_score": {
                "active": len(cache) > 0 and ranking_on,
                "wired": True,
                "reason": (
                    f"On-demand scoring cached for {len(cache)} symbol(s); ranking modifier only."
                    if cache
                    else "Computed on-demand by sentiment_service.score_symbol_sentiment().",
                ),
            },
            "gemini_advisor": {
                "active": settings.gemini_configured and bool(cfg.get("ai_enabled", True)),
                "wired": True,
                "reason": "Advisory reviews only — never places orders or changes config directly.",
                "endpoint": "/api/ai-advisor/status",
            },
        },
    }


def sentiment_latest(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.sentiment_service import get_sentiment_cache_snapshot

    cache = get_sentiment_cache_snapshot()
    db_rows = list(
        session.exec(
            select(SymbolCandidate).where(SymbolCandidate.sentiment_score.is_not(None)).limit(20)
        ).all()
    )
    cached_scores = [
        {
            "symbol": sym,
            "score": row.get("sentiment_score"),
            "alignment": row.get("sentiment_alignment"),
            "headline_count": row.get("headline_count"),
            "model_used": row.get("model_used"),
            "scored_at": row.get("scored_at"),
            "source": "sentiment_cache",
        }
        for sym, row in cache.items()
    ]
    db_scores = [
        {"symbol": r.symbol, "score": r.sentiment_score, "source": r.source or "symbol_candidate"}
        for r in db_rows
    ]
    merged = cached_scores or db_scores
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "symbol_scores": merged,
        "count": len(merged),
        "note": (
            "Live cache from score_symbol_sentiment(); ranking-only influence."
            if cached_scores
            else ("DB symbol_candidate rows only." if db_scores else "No scored symbols yet — run /api/sentiment/refresh.")
        ),
    }


def sentiment_source_health(session: Session) -> dict[str, Any]:
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        **sentiment_sources(session),
    }


def cfg_get_sentiment(cfg: dict) -> bool:
    return bool((cfg.get("sentiment") or {}).get("enabled", False))


def ai_advisor_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    from app.services.ai_budget_guard import AIBudgetGuard

    budget = AIBudgetGuard(session).status()
    configured = settings.gemini_configured
    ai_on = bool(cfg.get("ai_enabled", True))
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "gemini_configured": configured,
        "ai_enabled": ai_on,
        "advisor_active": configured and ai_on,
        "display_title": "Gemini Advisor: Active, advisory only"
        if configured and ai_on
        else "Gemini Advisor: Inactive",
        "display_subtitle": "Cannot trade, change live lock, or apply config directly.",
        "can_place_trades": False,
        "can_mutate_live_lock": False,
        "can_apply_config_directly": False,
        "role": "advisory_reviewer_only",
        "budget": budget,
        "latest_review": ai_advisor_latest_review(session),
    }


def ai_advisor_latest_review(session: Session) -> Optional[dict[str, Any]]:
    row = session.exec(select(AIReview).order_by(AIReview.created_at.desc())).first()
    if not row:
        return None
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "decision": row.decision,
        "confidence": row.confidence,
        "summary": row.summary,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }
