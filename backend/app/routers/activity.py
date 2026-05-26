from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("/feed")
def feed(limit: int = 80, session: Session = Depends(get_session)):
    from app.services.activity_feed_service import activity_feed

    return activity_feed(session, limit=limit)


@router.get("/latest-tick-card")
def latest_tick_card(session: Session = Depends(get_session)):
    from app.services.activity_feed_service import latest_tick_card as build_card

    return build_card(session)
