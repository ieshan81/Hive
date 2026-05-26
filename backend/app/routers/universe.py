from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.universe_service import universe_status

    return universe_status(session)


@router.get("/scan-summary")
def scan_summary(session: Session = Depends(get_session)):
    from app.services.universe_service import universe_scan_summary

    return universe_scan_summary(session)
