from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/mission-control", tags=["mission-control"])


@router.get("/status")
def get_status(session: Session = Depends(get_session)):
    from app.services.mission_control_snapshot_service import mission_control_status_fast

    return mission_control_status_fast(session)


@router.post("/refresh")
def refresh_status(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.mission_control_snapshot_service import refresh_mission_control_snapshot

    return refresh_mission_control_snapshot(session, background=True)
