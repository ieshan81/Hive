from fastapi import APIRouter, Depends
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
