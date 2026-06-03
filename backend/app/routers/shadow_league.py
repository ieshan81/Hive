"""Shadow Trading League — read-only status API."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/shadow-league", tags=["shadow-league"])


@router.get("/status")
def shadow_league_status(session: Session = Depends(get_session)):
    from app.services.shadow_league_status_service import build_shadow_league_status

    return build_shadow_league_status(session)
