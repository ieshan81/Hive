from fastapi import APIRouter, Body, Depends, Query
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import sentiment_status

    return sentiment_status(session)


@router.get("/sources")
def sources(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import sentiment_sources

    return sentiment_sources(session)


@router.get("/latest")
def latest(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import sentiment_latest

    return sentiment_latest(session)


@router.get("/symbol/{symbol}")
def symbol_score(symbol: str, side: str = Query(default="buy")):
    """Live FinBERT + Alpaca news score for one symbol. Capped influence ±10%."""
    from app.services.sentiment_service import score_symbol_sentiment

    return {
        "status": "ok",
        **score_symbol_sentiment(symbol, side=side),
    }


@router.post("/refresh")
def refresh(payload: dict = Body(default_factory=dict)):
    """Force a sentiment recompute for given symbols (best-effort, cached internally)."""
    from app.services.sentiment_service import score_symbol_sentiment

    symbols = payload.get("symbols") or ["BTC/USD", "ETH/USD"]
    side = payload.get("side", "buy")
    return {
        "status": "ok",
        "refreshed": [score_symbol_sentiment(s, side=side) for s in symbols],
    }


@router.get("/pump-dump-alerts")
def pump_dump_alerts():
    """Return active pump-dump cooldowns. Never alone permits a trade."""
    from app.services.sentiment_service import _PUMP_DUMP_COOLDOWNS
    from datetime import datetime

    now = datetime.utcnow()
    active = [
        {"symbol": k, "cooldown_until": v.isoformat() + "Z", "minutes_remaining": int((v - now).total_seconds() / 60)}
        for k, v in _PUMP_DUMP_COOLDOWNS.items()
        if v > now
    ]
    return {"status": "ok", "active_count": len(active), "alerts": active}
