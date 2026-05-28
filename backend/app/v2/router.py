"""V2 API — live cockpit, cycles, bootstrap (research rebuild path)."""

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/v2", tags=["v2"])


@router.get("/cockpit")
def v2_cockpit(session: Session = Depends(get_session)):
    from app.v2.cockpit_service import build_cockpit

    return build_cockpit(session)


@router.get("/watchlist")
def v2_watchlist(session: Session = Depends(get_session)):
    from app.v2.watchlist import live_full_watchlist

    return live_full_watchlist(force=True)


@router.get("/funnel")
def v2_funnel(session: Session = Depends(get_session)):
    from app.v2.live_pipeline import live_funnel

    return live_funnel(session)


@router.post("/cycle/run")
def v2_run_cycle(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.v2.cycle_runner import run_trading_cycle

    return run_trading_cycle(session, operator=str(body.get("operator") or "operator"))


@router.post("/bootstrap")
def v2_bootstrap(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """
    Research rebuild bootstrap: optional soft reset, refresh major watchlist bars,
  enable paper learning, run first cycle.
    """
    from app.services.market_data_refresh_service import MarketDataRefreshService
    from app.services.paper_learning_start_service import start_fresh_paper_learning
    from app.v2.cycle_runner import run_trading_cycle
    from app.v2.watchlist import MAJOR_CRYPTO

    operator = str(body.get("operator") or "operator")
    if body.get("nuke_first"):
        from app.services.danger_zone_service import DangerZoneService

        DangerZoneService(session).nuke_everything(operator=operator)

    from app.services.config_manager import ConfigManager

    config = ConfigManager(session).get_current()
    refresh = MarketDataRefreshService(session, config).refresh_bars(
        asset_type="crypto",
        timeframe="5Min",
        symbols=MAJOR_CRYPTO,
        lookback_hours=72,
        operator=operator,
    )
    start = start_fresh_paper_learning(session, operator=operator)
    cycle = run_trading_cycle(session, operator=operator)
    try:
        session.commit()
    except Exception:
        session.rollback()
    return {
        "status": "ok",
        "message": "V2 bootstrap complete — paper learning enabled, watchlist bars refreshed, cycle run.",
        "bars_refresh": refresh,
        "paper_learning": start,
        "cycle": cycle,
    }
