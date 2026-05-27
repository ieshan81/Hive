"""Reddit read-only social scanner API."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token
from app.services.reddit_scanner_service import (
    reddit_latest,
    reddit_status,
    reddit_symbol,
    refresh_reddit_scan,
)

router = APIRouter(prefix="/api/social/reddit", tags=["social-reddit"])


@router.get("/status")
def status():
    return reddit_status()


@router.get("/latest")
def latest():
    return reddit_latest()


@router.get("/symbol/{symbol:path}")
def symbol(symbol: str):
    return reddit_symbol(symbol)


@router.post("/refresh")
def refresh(
    _op: str = Depends(require_operator_token),
):
    return refresh_reddit_scan()
