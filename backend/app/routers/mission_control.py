from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/mission-control", tags=["mission-control"])


@router.get("/status")
def get_status(session: Session = Depends(get_session)):
    from app.services.mission_control_service import mission_control_status

    return mission_control_status(session)
