"""Autonomous backtesting lab — aliases for research lab + AI manager."""

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token
from app.services.research_lab_service import ResearchLabService

router = APIRouter(prefix="/api/backtesting", tags=["backtesting"])


@router.get("/status")
def backtesting_status(session: Session = Depends(get_session)):
    ResearchLabService(session).ensure_library()
    out = ResearchLabService(session).status()
    return {"status": "ok", **out}


@router.get("/runs")
def backtesting_runs(limit: int = 50, session: Session = Depends(get_session)):
    from app.services.research_backtest_engine import ResearchBacktestEngine
    from app.services.config_manager import ConfigManager

    cfg = ConfigManager(session).get_current()
    runs = ResearchBacktestEngine(session, cfg).list_runs(limit)
    return {"status": "ok", "runs": runs, "count": len(runs)}


@router.post("/run-push-pull")
def run_push_pull_backtest(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    payload = {
        **body,
        "strategy_id": body.get("strategy_id", "crypto_push_pull_baseline"),
        "symbols": body.get("symbols", ["BTC/USD", "ETH/USD"]),
    }
    return ResearchLabService(session).run_backtest(payload)
