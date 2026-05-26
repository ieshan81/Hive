from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/ai-manager", tags=["ai-manager"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.ai_manager_service import AIManagerService

    return AIManagerService(session).status()


@router.get("/memories")
def memories(limit: int = 40, session: Session = Depends(get_session)):
    from app.services.ai_manager_service import AIManagerService

    return AIManagerService(session).memories(limit)


@router.get("/lessons")
def lessons(limit: int = 30, session: Session = Depends(get_session)):
    from app.services.ai_manager_service import AIManagerService

    return AIManagerService(session).lessons(limit)


@router.get("/strategy-confidence")
def strategy_confidence(session: Session = Depends(get_session)):
    from app.services.ai_manager_service import AIManagerService

    return AIManagerService(session).strategy_confidence()
