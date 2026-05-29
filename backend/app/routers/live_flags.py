"""Live flag ledger API.

Live trading remains locked. POST routes record dry-runs/requests only and are
operator protected.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.live_flags_service import LiveFlagsService
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/live-flags", tags=["live-flags"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """READ ONLY: live lock status and ledger summary."""
    return LiveFlagsService(session).status()


@router.post("/dry-run")
def dry_run(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: preview blockers. Does not mutate DB/config."""
    return LiveFlagsService(session).dry_run(body)


@router.post("/request-change")
def request_change(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: record request ledger only. Does not unlock live."""
    out = LiveFlagsService(session).request_change(body)
    session.commit()
    return out


@router.post("/approve-change")
def approve_change(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: current build rejects live mutation and records why."""
    out = LiveFlagsService(session).approve_change(body)
    session.commit()
    return out

