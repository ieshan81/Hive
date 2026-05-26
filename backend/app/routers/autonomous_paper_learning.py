"""Autonomous Paper Learning API — operator-gated, paper only."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/autonomous-paper-learning", tags=["autonomous-paper-learning"])


@router.get("/status")
def apl_status(session: Session = Depends(get_session)):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    return AutonomousPaperLearningService(session).status()


@router.post("/enable")
def apl_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).enable(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/pause")
def apl_pause(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).pause(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/disable-all-paper-trading")
def apl_disable_all(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).disable_all_paper_trading(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/run-one-cycle")
def apl_run_one(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).run_one_cycle(operator=body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/run-backtest-lab-now")
def apl_backtest_lab(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).run_backtest_lab_now(
        operator=body.get("operator", "operator"),
        limit=int(body.get("limit", 3)),
    )
    session.commit()
    return out


@router.get("/scheduler/status")
def scheduler_status(session: Session = Depends(get_session)):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    return AutonomousPaperScheduler(session).status()


@router.post("/scheduler/enable")
def scheduler_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    out = AutonomousPaperScheduler(session).enable(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/scheduler/pause")
def scheduler_pause(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    out = AutonomousPaperScheduler(session).pause(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/start-fresh")
def start_fresh(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.paper_learning_start_service import start_fresh_paper_learning

    out = start_fresh_paper_learning(session, operator=body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/tick")
def scheduler_tick(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    out = AutonomousPaperScheduler(session).tick(operator=body.get("operator", "cron"))
    session.commit()
    return out
