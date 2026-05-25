"""Confidence Level API — evidence scores, not live permission."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/confidence", tags=["confidence"])


@router.get("/summary")
def confidence_summary(session: Session = Depends(get_session)):
    from app.services.safe_responses import safe_confidence_summary

    return safe_confidence_summary(session)


@router.get("/by-strategy")
def confidence_by_strategy(session: Session = Depends(get_session)):
    from app.services.confidence_engine import ConfidenceEngine

    return ConfidenceEngine(session).by_strategy()


@router.get("/by-symbol")
def confidence_by_symbol(session: Session = Depends(get_session)):
    from app.services.confidence_engine import ConfidenceEngine

    return ConfidenceEngine(session).by_symbol()
