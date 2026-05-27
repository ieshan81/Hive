"""News scanner — Alpaca/Finnhub/RSS optional; derived sentiment only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.finbert_client import classify_batch, finbert_service_url
from app.services.sentiment_service import AlpacaNewsIngester, FinBERTScorer

_CACHE: dict[str, Any] = {"at": None, "articles": []}


def news_status(session: Session) -> dict[str, Any]:
    from app.config import settings

    provider_wired = bool(settings.alpaca_api_key)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "provider_wired": provider_wired,
        "finbert_service": bool(finbert_service_url()),
        "finbert_local": FinBERTScorer.is_available(),
        "primary_source": "alpaca_benzinga",
        "fallback_sources": ["finnhub", "alpha_vantage", "yahoo_rss"],
    }


def refresh_news(session: Session, symbols: Optional[list[str]] = None) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    syms = symbols or ["BTC/USD", "ETH/USD", "SOL/USD", "HYPE/USD", "RENDER/USD"]
    articles: list[dict] = []
    for sym in syms[:8]:
        try:
            rows = AlpacaNewsIngester.get_headlines(sym, limit=5)
            for row in rows or []:
                articles.append(
                    {
                        "symbol": sym,
                        "headline": (row.get("headline") or "")[:300],
                        "url": row.get("url"),
                        "published_at": row.get("published_at"),
                        "source": row.get("source", "alpaca_news"),
                    }
                )
        except Exception:
            pass

    finbert_items = []
    for i, a in enumerate(articles[:32]):
        if a.get("headline"):
            finbert_items.append(
                {
                    "id": f"news-{i}",
                    "symbol": a.get("symbol", ""),
                    "source": "news",
                    "text": a["headline"],
                }
            )

    scored = classify_batch(finbert_items) if finbert_items else []
    by_id = {s["id"]: s for s in scored}
    for i, a in enumerate(articles[:32]):
        sc = by_id.get(f"news-{i}") or {}
        a["sentiment_label"] = sc.get("label", "neutral")
        a["sentiment_score"] = sc.get("score", 0.0)

    _CACHE["articles"] = articles
    _CACHE["at"] = datetime.utcnow().isoformat() + "Z"
    return {
        "status": "ok",
        "generated_at_utc": _CACHE["at"],
        "count": len(articles),
        "articles": articles,
        "sentiment_max_adjustment_pct": (cfg.get("sentiment") or {}).get("max_adjustment_pct", 10),
    }


def news_latest(session: Session) -> dict[str, Any]:
    if _CACHE.get("articles"):
        return {
            "status": "ok",
            "generated_at_utc": _CACHE.get("at"),
            "articles": _CACHE["articles"],
            "count": len(_CACHE["articles"]),
        }
    return refresh_news(session)


def news_symbol(session: Session, symbol: str) -> dict[str, Any]:
    latest = news_latest(session)
    sym = symbol.upper()
    rows = [a for a in latest.get("articles") or [] if sym in str(a.get("symbol", "")).upper()]
    return {"status": "ok", "symbol": sym, "articles": rows, "count": len(rows)}
