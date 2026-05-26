"""Trading cage API — deterministic paper path status."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/trading-cage", tags=["trading-cage"])


@router.get("/status")
def trading_cage_status(session: Session = Depends(get_session)):
    from app.trading_cage.paper_loop import PaperLoop

    return PaperLoop(session).status()


@router.get("/paper-guard")
def paper_guard(session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.trading_cage.paper_guard import paper_guard_status

    cfg = ConfigManager(session).get_current()
    return {"status": "ok", **paper_guard_status(cfg)}


@router.get("/strategy-performance")
def strategy_performance(session: Session = Depends(get_session)):
    from app.services.strategy_performance_service import StrategyPerformanceService

    return StrategyPerformanceService(session).summary()
