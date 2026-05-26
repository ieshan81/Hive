"""Strategy status — live scoring path proof."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.strategy_status_service import candidate_rankings, strategy_status

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/status")
def get_strategy_status(session: Session = Depends(get_session)):
    return strategy_status(session)


@router.get("/candidate-rankings")
def get_candidate_rankings(session: Session = Depends(get_session)):
    return candidate_rankings(session)
