"""Dynamic strategy weights and chart OHLC — operator-visible tuning."""

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.dynamic_weights_service import apply_weights, get_dynamic_weights, suggest_weights_with_ai
from app.services.ohlc_chart_service import ohlc_series

router = APIRouter(prefix="/api/strategy", tags=["dynamic-strategy"])


@router.get("/dynamic-weights")
def dynamic_weights(session: Session = Depends(get_session)):
    return get_dynamic_weights(session)


@router.post("/dynamic-weights")
def set_dynamic_weights(body: dict = Body(default={}), session: Session = Depends(get_session)):
    return apply_weights(
        session,
        universe_weights=body.get("universe_weights"),
        portfolio_weights=body.get("portfolio_weights"),
        min_rank_score=body.get("min_rank_score"),
        changed_by=str(body.get("changed_by") or "operator"),
        reason=str(body.get("reason") or "Operator weight update"),
    )


@router.post("/dynamic-weights/ai-rebalance")
def ai_rebalance_weights(body: dict = Body(default={}), session: Session = Depends(get_session)):
    return suggest_weights_with_ai(session, context=body.get("context"))


@router.get("/ohlc")
def chart_ohlc(
    symbol: str = "BTC/USD",
    timeframe: str = "5Min",
    limit: int = 120,
    session: Session = Depends(get_session),
):
    return ohlc_series(session, symbol, timeframe=timeframe, limit=min(500, max(20, limit)))
