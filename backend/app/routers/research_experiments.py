"""Targeted push-pull research experiments."""

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token
from app.services.targeted_experiment_service import (
    experiment_latest,
    experiment_status,
    run_targeted_experiment,
)

router = APIRouter(prefix="/api/research/targeted-experiment", tags=["research-experiments"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    return experiment_status(session)


@router.get("/latest")
def latest(session: Session = Depends(get_session)):
    return experiment_latest(session)


@router.post("/run")
def run(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    return run_targeted_experiment(session, body, operator=_op)
