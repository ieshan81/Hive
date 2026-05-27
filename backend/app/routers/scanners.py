"""Scanner stack API — status, latest, health, run-once."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.database import get_session
from app.services import scanner_stack

router = APIRouter(prefix="/api/scanners", tags=["scanners"])


@router.get("/status")
def status():
    return {
        "status": "ok",
        "scanners": scanner_stack.list_scanners(),
        "health": scanner_stack.health_snapshot(),
    }


@router.get("/latest")
def latest():
    return scanner_stack.latest_outputs()


@router.get("/health")
def health():
    return scanner_stack.health_snapshot()


@router.get("/errors")
def errors():
    return {"status": "ok", "errors": scanner_stack.error_log()}


@router.post("/run-once")
def run_once(
    symbols: str = Query(default="BTC/USD,ETH/USD,SOL/USD,DOGE/USD"),
    session: Session = Depends(get_session),
):
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return scanner_stack.run_all(session, symbols=sym_list)
