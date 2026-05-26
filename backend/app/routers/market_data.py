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
    symbols = body.get("symbols")
    if symbols is None and body.get("max_symbols") is None:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"]
    out = MarketDataRefreshService(session).refresh_bars(
        asset_type=body.get("asset_type", "crypto"),
        timeframe=body.get("timeframe", "5Min"),
        symbols=symbols,
        lookback_hours=int(body.get("lookback_hours", 48)),
        operator=body.get("operator", "operator"),
    )
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        return {"status": "error", "message": str(exc)[:300], **out}
    return out
