"""Candle Lab API — technical analysis with annotated levels."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.technical_candle_analysis_service import TechnicalCandleAnalysisService

router = APIRouter(prefix="/api/candle-lab", tags=["candle-lab"])


@router.get("/status")
def candle_lab_status(session: Session = Depends(get_session)):
    return TechnicalCandleAnalysisService(session).status()


@router.post("/analyze")
def candle_lab_analyze(body: dict = Body(default={}), session: Session = Depends(get_session)):
    symbol = str(body.get("symbol") or "DOGE/USD")
    tf = str(body.get("timeframe") or "5Min")
    return TechnicalCandleAnalysisService(session).analyze(symbol, timeframe=tf)


@router.get("/analyze/{symbol}")
def candle_lab_analyze_get(symbol: str, timeframe: str = "5Min", session: Session = Depends(get_session)):
    return TechnicalCandleAnalysisService(session).analyze(symbol, timeframe=timeframe)
