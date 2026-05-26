from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


@router.get("/freshness")
def freshness(
    asset_type: str = "crypto",
    timeframe: str = "5Min",
    session: Session = Depends(get_session),
):
    from app.services.market_data_refresh_service import MarketDataRefreshService

    return MarketDataRefreshService(session).freshness_report(
        asset_type=asset_type, timeframe=timeframe
    )


@router.post("/refresh-bars")
def refresh_bars(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.market_data_refresh_service import MarketDataRefreshService
    from app.services.push_pull_strategy_seed import ensure_crypto_push_pull_baseline

    ensure_crypto_push_pull_baseline(session)
    out = MarketDataRefreshService(session).refresh_bars(
        asset_type=body.get("asset_type", "crypto"),
        timeframe=body.get("timeframe", "5Min"),
        symbols=body.get("symbols"),
        lookback_hours=int(body.get("lookback_hours", 48)),
        operator=body.get("operator", "operator"),
    )
    session.commit()
    return out
