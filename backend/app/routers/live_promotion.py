"""Live promotion — locked; checklist only."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/live-promotion", tags=["live-promotion"])


@router.get("/checklist")
def promotion_checklist(session: Session = Depends(get_session)):
    from app.services.promotion_readiness_service import PromotionReadinessService

    return PromotionReadinessService(session).checklist()


@router.post("/validate-live-credentials")
def validate_credentials(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.promotion_readiness_service import PromotionReadinessService

    return PromotionReadinessService(session).validate_live_credentials_locked()


@router.post("/request-shift-to-live")
def request_shift(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.promotion_readiness_service import PromotionReadinessService

    return PromotionReadinessService(session).request_shift_to_live(body.get("operator_note", ""))
