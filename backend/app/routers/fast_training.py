"""Fast crypto training API — run-once + status; no in-process Railway loop."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop

router = APIRouter(prefix="/api/fast-training", tags=["fast-training"])


@router.get("/status")
def fast_training_status(session: Session = Depends(get_session)):
    return FastCryptoTrainingLoop(session).status()


@router.post("/run-once")
def fast_training_run_once(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    actor = str(body.get("actor") or "operator")
    out = FastCryptoTrainingLoop(session).run_once(actor=actor)
    session.commit()
    return out


@router.post("/start-loop")
def fast_training_start_loop(session: Session = Depends(get_session)):
    """Best-effort stub — production must use run-once + external scheduler."""
    return FastCryptoTrainingLoop(session).start_loop()
