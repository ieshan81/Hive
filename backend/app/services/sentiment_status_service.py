"""Sentiment subsystem status — honest proof of what is active vs inactive."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import settings
from app.database import AIReview, SymbolCandidate
from app.services.config_manager import ConfigManager


def sentiment_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    sources_payload = sentiment_sources(session, cfg)
    fin = sources_payload.get("sources", {}).get("finbert", {})
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "sentiment_affects_ranking": bool((cfg.get("sentiment") or {}).get("influence_ranking")),
        "sentiment_affects_trading": False,
        "sentiment_can_place_trades": False,
        "sentiment_influence_ranking": bool((cfg.get("sentiment") or {}).get("influence_ranking")),
        "sentiment_influence_trading": False,
        "overall_active": bool(fin.get("active")),
        "max_adjustment_pct": (cfg.get("sentiment") or {}).get("max_adjustment_pct", 10),
        "finbert": {
            "implemented": True,
            "worker_url_configured": fin.get("worker_url_configured", False),
            "worker_connected": fin.get("worker_connected", False),
            "model_loaded": fin.get("model_loaded", False),
            "active": fin.get("active", False),
        },
        "message": "Sentiment adjusts ranking only (capped). Never permits trades.",
        "sources": sources_payload.get("sources"),
    }


def sentiment_sources(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    import os
    try:
        from app.services.sentiment_service import FinBERTScorer
        from app.services.finbert_client import finbert_health

        from app.services.finbert_client import finbert_service_url

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

    # News provider can be configured even when FinBERT is unavailable; we keep truth explicit:
    # provider_wired may be true, but sentiment_scoring is inactive without FinBERT.
    news_provider_wired = bool(settings.alpaca_configured)
    news_active = bool(news_provider_wired and finbert_active)

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
                    if finbert_active
                    else "Implemented; inactive until FINBERT_SERVICE_URL healthy or local transformers."
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
                "active": False,
                "wired": True,
                "reason": "Computed on-demand by sentiment_service.score_symbol_sentiment().",
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
    cfg = config or ConfigManager(session).get_current()
    rows = list(
        session.exec(
            select(SymbolCandidate).where(SymbolCandidate.sentiment_score.is_not(None)).limit(20)
        ).all()
    )
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "symbol_scores": [
            {"symbol": r.symbol, "score": r.sentiment_score, "source": r.source}
            for r in rows
        ],
        "count": len(rows),
        "note": "Empty list is expected — sentiment scoring is not active.",
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
