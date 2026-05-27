"""News scanner API."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.news_scanner_service import news_latest, news_status, news_symbol, refresh_news
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    return news_status(session)


@router.get("/latest")
def latest(session: Session = Depends(get_session)):
    return news_latest(session)


@router.get("/symbol/{symbol:path}")
def symbol(symbol: str, session: Session = Depends(get_session)):
    return news_symbol(session, symbol)


@router.post("/refresh")
def refresh(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    return refresh_news(session)
