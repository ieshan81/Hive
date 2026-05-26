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
    enabled = bool(cfg_get_sentiment(cfg))
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "sentiment_influence_ranking": False,
        "sentiment_influence_trading": False,
        "overall_active": False,
        "message": "Sentiment engines are not wired into live ranking or execution. Gemini advisor is separate.",
        "sources": sentiment_sources(session, cfg)["sources"],
    }


def sentiment_sources(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "sources": {
            "finbert": {
                "active": False,
                "wired": False,
                "reason": "FinBERT model not installed or integrated in backend.",
            },
            "reddit_social": {
                "active": False,
                "wired": False,
                "reason": "No Reddit/social scraping pipeline in codebase.",
            },
            "news_feed": {
                "active": False,
                "wired": False,
                "reason": "No news ingestion or headline sentiment pipeline.",
            },
            "symbol_candidate_score": {
                "active": False,
                "wired": True,
                "reason": "DB column exists but scores are null — placeholder only.",
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
