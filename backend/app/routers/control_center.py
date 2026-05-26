"""Control Center — merged Settings + Danger Zone API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.control_center_service import control_center_status

router = APIRouter(prefix="/api/control-center", tags=["control-center"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    return control_center_status(session)
