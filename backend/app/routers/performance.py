from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    from app.services.performance_service import performance_summary

    return performance_summary(session)


@router.get("/equity-curve")
def equity_curve(limit: int = 120, session: Session = Depends(get_session)):
    from app.services.performance_service import equity_curve as equity_curve_data

    return equity_curve_data(session, limit=limit)
