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


@router.get("/signals")
def signals(symbol: str | None = None, timeframe: str = "5Min", session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).signals(symbol=symbol, timeframe=timeframe)


@router.get("/paper-order-proof")
def paper_order_proof(session: Session = Depends(get_session)):
    from app.services.paper_order_proof_service import PaperOrderProofService

    return PaperOrderProofService(session).summary()


@router.get("/diagnosis")
def diagnosis(session: Session = Depends(get_session)):
    from app.services.push_pull_diagnosis_service import PushPullDiagnosisService

    return PushPullDiagnosisService(session).why_no_order()


@router.get("/exit-monitor/status")
def exit_monitor(session: Session = Depends(get_session)):
    from app.services.exit_monitor_service import exit_monitor_status

    return exit_monitor_status(session)
