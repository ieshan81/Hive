"""Symbol Identity / Logo API."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlmodel import Session

from app.database import get_session
from app.services import symbol_identity_service

router = APIRouter(prefix="/api/symbols", tags=["symbol-identity"])


@router.get("/identity")
def identity_status():
    return symbol_identity_service.status()


@router.get("/metadata")
def symbol_metadata(symbols: str = Query(default=""), session: Session = Depends(get_session)):
    """Fast per-symbol metadata for hover cards (no slow discovery). symbols=BTC/USD,ETH/USD,AAPL"""
    from app.services.symbol_metadata_service import metadata_many

    syms = [s.strip() for s in str(symbols or "").split(",") if s.strip()]
    return metadata_many(session, syms)


@router.get("/identity/{symbol:path}")
def identity_for(symbol: str, allow_network: bool = Query(default=True)):
    return symbol_identity_service.get_identity(symbol, allow_network=allow_network)


@router.post("/identity/batch")
def identity_batch(symbols: list[str] = Body(default=[]), allow_network: bool = Query(default=True)):
    return {
        "status": "ok",
        "count": len(symbols),
        "items": symbol_identity_service.get_many(symbols, allow_network=allow_network),
    }


@router.post("/identity/refresh")
def identity_refresh(symbols: list[str] | None = Body(default=None)):
    return symbol_identity_service.refresh_cache(symbols)


@router.get("/identity-errors")
def identity_errors():
    return {"status": "ok", "errors": symbol_identity_service.error_snapshot()}
