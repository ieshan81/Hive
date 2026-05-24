from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel import Session

from app.database import get_session
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.ai_fund_manager import AIFundManager
from app.services.backtest_engine import BacktestEngine
from app.services.config_manager import ConfigManager
from app.services.dashboard_service import build_dashboard
from app.services.diagnostic_export import bundle_as_zip_bytes, export_diagnostic_bundle
from app.services.monte_carlo_engine import MonteCarloEngine
from app.services.strategy_engine import StrategyEngine

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/dashboard")
def get_dashboard(session: Session = Depends(get_session)):
    return build_dashboard(session)


@router.get("/health")
def health_check(session: Session = Depends(get_session)):
    from app.config import settings
    from app.database import SystemHealth

    health = session.get(SystemHealth, 1)
    warnings = []
    if not settings.alpaca_configured:
        warnings.append("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
    if not settings.gemini_configured:
        warnings.append("GEMINI_API_KEY not set")
    if not settings.database_url:
        warnings.append("DATABASE_URL not set")

    return {
        "status": "ok",
        "service": "caged-hive-quant-api",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "alpaca_connected": health.alpaca_connected if health else False,
        "warnings": warnings,
    }


@router.post("/cycle/run")
def run_cycle(session: Session = Depends(get_session)):
    from app.services.cycle_engine import CycleEngine

    result = CycleEngine(session).run()
    return result


@router.get("/session")
def get_session_state(session: Session = Depends(get_session)):
    from app.services.session_engine import SessionEngine
    from app.services.activity_logger import log_activity

    state = SessionEngine().detect()
    log_activity(session, "session_check", f"Session: {state.mode}", state.to_dict())
    return state.to_dict()


@router.post("/radar/refresh")
def refresh_radar(session: Session = Depends(get_session)):
    config = ConfigManager(session).get_current()
    from app.services.market_radar_service import MarketRadarService
    from app.services.session_engine import SessionEngine

    session_state = SessionEngine().detect()
    candidates = MarketRadarService(session, config).refresh(session_state)
    return {"status": "ok", "count": len(candidates), "mode": session_state.mode}


@router.post("/sync/alpaca")
def sync_alpaca(session: Session = Depends(get_session)):
    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"status": "error", "message": "Alpaca not configured"}
    account = adapter.sync_account()
    positions = adapter.sync_positions()
    return {
        "status": "ok" if account else "error",
        "account_synced": account is not None,
        "positions_count": len(positions),
    }


@router.post("/strategies/run/{strategy}")
def run_strategy(strategy: str, symbol: str = "NVDA", session: Session = Depends(get_session)):
    config = ConfigManager(session).get_current()
    engine = StrategyEngine(session, config)
    if strategy == "momentum_orb":
        signal = engine.run_momentum_orb(symbol)
    elif strategy == "mean_reversion_pairs":
        signal = engine.run_mean_reversion_pairs(symbol, "SPY")
    else:
        return {"status": "error", "message": f"Unknown strategy: {strategy}"}
    if signal is None:
        return {"status": "empty", "message": "No signal — missing bar data"}
    return {"status": "ok", "signal": signal.model_dump()}


@router.post("/backtest/run")
def run_backtest(symbol: str = "NVDA", session: Session = Depends(get_session)):
    config = ConfigManager(session).get_current()
    result = BacktestEngine(session, config).run_momentum_backtest(symbol)
    return {"status": result.status, "result": result.model_dump()}


@router.post("/monte-carlo/run")
def run_monte_carlo(session: Session = Depends(get_session)):
    config = ConfigManager(session).get_current()
    result = MonteCarloEngine(session, config).run()
    return {"status": result.status, "result": result.model_dump(), "warning": result.warning}


@router.post("/ai/review")
def trigger_ai_review(session: Session = Depends(get_session)):
    dashboard = build_dashboard(session)
    ai = AIFundManager(session)
    if not ai.configured:
        return {"status": "error", "message": "Gemini not configured"}
    review = ai.review("dashboard_snapshot", dashboard)
    if review is None:
        return {"status": "error", "message": "AI review failed"}
    return {"status": "ok", "review": review.model_dump()}


@router.get("/diagnostic-bundle")
def get_diagnostic_bundle(session: Session = Depends(get_session)):
    return export_diagnostic_bundle(session)


@router.get("/diagnostic-bundle/download")
def download_diagnostic_bundle(session: Session = Depends(get_session)):
    data = bundle_as_zip_bytes(session)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=hive-diagnostic-bundle.zip"},
    )
