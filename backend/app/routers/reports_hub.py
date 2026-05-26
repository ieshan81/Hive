from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/diagnostic-bundle/status")
def diagnostic_bundle_status(session: Session = Depends(get_session)):
    from app.services.reports_hub_service import ReportsHubService

    return ReportsHubService(session).diagnostic_bundle_status()


@router.get("/audit-trail")
def audit_trail(limit: int = 50, session: Session = Depends(get_session)):
    from app.services.reports_hub_service import ReportsHubService

    return ReportsHubService(session).audit_trail(limit)


@router.get("/system-log")
def system_log(limit: int = 100, session: Session = Depends(get_session)):
    from app.services.reports_hub_service import ReportsHubService

    return ReportsHubService(session).system_log(limit)
