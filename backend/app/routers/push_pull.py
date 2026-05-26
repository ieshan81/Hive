from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/push-pull", tags=["push-pull"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).status()


@router.get("/latest-tick")
def latest_tick(session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).latest_tick()


@router.get("/decisions")
def decisions(limit: int = 50, session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).decisions(limit)


@router.get("/lessons")
def lessons(limit: int = 40, session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).lessons(limit)
