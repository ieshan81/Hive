from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


@router.get("/quote-freshness")
def quote_freshness(
    asset_type: str = "crypto",
    symbols: str | None = None,
    session: Session = Depends(get_session),
):
    from app.services.quote_freshness_service import QuoteFreshnessService

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    if not sym_list:
        from app.services.market_data_refresh_service import MarketDataRefreshService

        sym_list = MarketDataRefreshService(session)._resolve_symbols(asset_type, None, fast=True)
    rows = [QuoteFreshnessService(session).check(s) for s in sym_list]
    fresh_n = sum(1 for r in rows if r.get("executable"))
    return {
        "status": "ok",
        "symbols": rows,
        "fresh_count": fresh_n,
        "stale_count": len(rows) - fresh_n,
        "count": len(rows),
    }


@router.get("/freshness")
def freshness(
    asset_type: str = "crypto",
    timeframe: str = "5Min",
    symbols: str | None = None,
    session: Session = Depends(get_session),
):
    from app.services.market_data_refresh_service import MarketDataRefreshService

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    return MarketDataRefreshService(session).freshness_report(
        asset_type=asset_type, timeframe=timeframe, symbols=sym_list
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
