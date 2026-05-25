"""Fast crypto training API — run-once + status; no in-process Railway loop."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop
from app.services.fast_training_exit_only_service import FastTrainingExitOnlyService
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/fast-training", tags=["fast-training"])


@router.get("/status")
def fast_training_status(session: Session = Depends(get_session)):
    return FastCryptoTrainingLoop(session).status()


@router.post("/run-once")
def fast_training_run_once(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor = str(body.get("actor") or "operator")
    out = FastCryptoTrainingLoop(session).run_once(actor=actor)
    session.commit()
    return out


@router.post("/enable")
def fast_training_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    operator = str(body.get("operator") or "operator")
    out = FastCryptoTrainingLoop(session).enable(operator=operator)
    session.commit()
    return out


@router.post("/disable")
def fast_training_disable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    operator = str(body.get("operator") or "operator")
    out = FastCryptoTrainingLoop(session).disable(operator=operator)
    session.commit()
    return out


@router.post("/monitor-exits")
def fast_training_monitor_exits(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    out = FastCryptoTrainingLoop(session).monitor_exits()
    session.commit()
    return out


@router.get("/exit-only/status")
def fast_training_exit_only_status(session: Session = Depends(get_session)):
    return FastTrainingExitOnlyService(session).status()


@router.post("/exit-only/enable")
def fast_training_exit_only_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    out = FastTrainingExitOnlyService(session).enable(str(body.get("operator") or "operator"))
    session.commit()
    return out


@router.post("/exit-only/disable")
def fast_training_exit_only_disable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    out = FastTrainingExitOnlyService(session).disable(str(body.get("operator") or "operator"))
    session.commit()
    return out


@router.post("/exit-only/run")
def fast_training_exit_only_run(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    out = FastTrainingExitOnlyService(session).run_exits(actor=str(body.get("actor") or "operator"))
    session.commit()
    return out


@router.post("/start-loop")
def fast_training_start_loop(session: Session = Depends(get_session)):
    """Best-effort stub — production must use run-once + external scheduler."""
    return FastCryptoTrainingLoop(session).start_loop()
