from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token
from app.services.trader_console_service import manual_paper_buy, trader_console_status

router = APIRouter(prefix="/api/trader-console", tags=["trader-console"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    return trader_console_status(session)


@router.post("/manual-buy")
def manual_buy(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor = str((body or {}).get("actor") or _op or "operator")
    out = manual_paper_buy(session, body, actor=actor)
    session.commit()
    return out
