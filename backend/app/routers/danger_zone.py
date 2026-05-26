"""Danger Zone — destructive operator actions (paper only, never enables live)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/danger-zone", tags=["danger-zone"])


@router.get("/nuke-everything/preview")
def nuke_preview(session: Session = Depends(get_session)):
    from app.services.danger_zone_service import DangerZoneService

    return DangerZoneService(session).nuke_preview()


@router.post("/nuke-everything")
def nuke_everything(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    phrase = str(body.get("confirmation") or body.get("confirmation_phrase") or "")
    if phrase.strip() != "NUKE CAGED HIVE":
        return {"status": "refused", "reason": "confirmation_phrase_mismatch", "required": "NUKE CAGED HIVE"}
    from app.services.danger_zone_service import DangerZoneService

    out = DangerZoneService(session).nuke_everything(body.get("operator", "operator"))
    session.commit()
    return out


@router.get("/ready-for-live-cleanup/preview")
def ready_preview(session: Session = Depends(get_session)):
    from app.services.danger_zone_service import DangerZoneService

    return DangerZoneService(session).ready_cleanup_preview()


@router.post("/ready-for-live-cleanup")
def ready_cleanup(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    phrase = str(body.get("confirmation") or body.get("confirmation_phrase") or "")
    if phrase.strip() != "READY CLEANUP":
        return {"status": "refused", "reason": "confirmation_phrase_mismatch", "required": "READY CLEANUP"}
    from app.services.danger_zone_service import DangerZoneService

    out = DangerZoneService(session).ready_for_live_cleanup(body.get("operator", "operator"))
    session.commit()
    return out
