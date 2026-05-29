"""TradingView display-only API."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token
from app.services.tradingview_integration_service import TradingViewIntegrationService

router = APIRouter(prefix="/api/tradingview", tags=["tradingview"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """READ ONLY: display-only integration status."""
    return TradingViewIntegrationService(session).status()


@router.get("/overlays")
def overlays(session: Session = Depends(get_session)):
    """READ ONLY: stored display overlays/events."""
    return TradingViewIntegrationService(session).overlays()


@router.get("/chart")
def chart(
    symbol: str = "BTC/USD",
    timeframe: str = "5Min",
    limit: int = 120,
    session: Session = Depends(get_session),
):
    """READ ONLY: cached chart bars for display fallback; no provider fetches."""
    return TradingViewIntegrationService(session).chart(
        symbol=symbol,
        timeframe=timeframe,
        limit=min(max(limit, 20), 300),
    )


@router.post("/webhook")
def webhook(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: accept display event only; never submit orders."""
    out = TradingViewIntegrationService(session).webhook(body)
    session.commit()
    return out

