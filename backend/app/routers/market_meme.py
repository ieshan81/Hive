"""Meme volatility spike detector API."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.config_manager import ConfigManager
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/market/meme-spike", tags=["meme-spike"])


@router.get("/status")
def meme_spike_status(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return MemeVolatilitySpikeDetector(session, cfg).status()


@router.post("/evaluate")
def meme_spike_evaluate(body: dict = Body(default={}), session: Session = Depends(get_session), _op_guard: str = Depends(require_operator_token)):
    cfg = ConfigManager(session).get_current()
    symbols = body.get("symbols") or ["DOGE/USD", "SHIB/USD"]
    timeframes = body.get("timeframes")
    out = MemeVolatilitySpikeDetector(session, cfg).evaluate_many(symbols, timeframes)
    session.commit()
    return out


@router.get("/recent")
def meme_spike_recent(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return {"status": "ok", "evaluations": MemeVolatilitySpikeDetector(session, cfg).recent()}
