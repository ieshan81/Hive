"""Strategy change proposals — operator approval required."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/strategy-proposals", tags=["strategy-proposals"])


@router.get("")
def list_proposals(status: str | None = None, session: Session = Depends(get_session)):
    from app.services.strategy_proposal_service import StrategyProposalService

    return {"status": "ok", "proposals": StrategyProposalService(session).list_proposals(status=status)}


@router.post("/{proposal_id}/approve")
def approve_proposal(
    proposal_id: int,
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.strategy_proposal_service import StrategyProposalService

    out = StrategyProposalService(session).approve(proposal_id, body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/{proposal_id}/reject")
def reject_proposal(
    proposal_id: int,
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.strategy_proposal_service import StrategyProposalService

    out = StrategyProposalService(session).reject(proposal_id, body.get("operator", "operator"))
    session.commit()
    return out
