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
        "timeframe": body.get("timeframe", "5Min"),
        "lookback_days": body.get("lookback_days", 90),
    }
    return ResearchLabService(session).run_backtest(payload)


@router.post("/promotion-verdict")
def promotion_verdict(body: dict = Body(default={})):
    """Pure DSR + walk-forward gate on a list of returns. No DB writes."""
    from app.services.dsr_engine import build_promotion_verdict

    returns = [float(r) for r in (body.get("returns") or [])]
    n_trials = int(body.get("n_trials", 1))
    return {"status": "ok", **build_promotion_verdict(returns, n_trials)}


@router.get("/result/{run_id}")
def result(run_id: str, session: Session = Depends(get_session)):
    from app.services.research_backtest_engine import ResearchBacktestEngine
    from app.services.config_manager import ConfigManager

    cfg = ConfigManager(session).get_current()
    runs = ResearchBacktestEngine(session, cfg).list_runs(200)
    match = next((r for r in runs if str(r.get("id")) == str(run_id) or str(r.get("run_id")) == str(run_id)), None)
    if not match:
        return {"status": "not_found", "run_id": run_id}
    return {"status": "ok", "run": match}
