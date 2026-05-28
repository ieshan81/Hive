"""Caged Hive Quant — canonical live API (research v2 runtime). No page-state cache."""

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api", tags=["cockpit"])


@router.get("/cockpit")
def get_cockpit(session: Session = Depends(get_session)):
    from app.v2.cockpit_service import build_cockpit

    return build_cockpit(session)


@router.get("/watchlist")
def get_watchlist(session: Session = Depends(get_session)):
    from app.v2.watchlist import live_full_watchlist

    return live_full_watchlist(session, force=True)


@router.get("/funnel")
def get_funnel(session: Session = Depends(get_session)):
    from app.v2.live_pipeline import live_funnel

    return live_funnel(session)


@router.post("/rebuild")
def post_rebuild(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Hard nuke + aggressive profile + paper ON + bar refresh + agent cycles."""
    from app.v2.rebuild import full_rebuild

    return full_rebuild(session, operator=str(body.get("operator") or "operator"))


@router.post("/agent/cycle")
def post_agent_cycle(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.v2.agent_engine import run_agent_cycle

    return run_agent_cycle(session, operator=str(body.get("operator") or "operator"))


@router.post("/weights/ai-rebalance")
def post_weights_ai_rebalance(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.dynamic_weights_service import suggest_weights_with_ai

    return suggest_weights_with_ai(session, context=body.get("context"))


@router.get("/weights")
def get_weights(session: Session = Depends(get_session)):
    from app.services.dynamic_weights_service import get_dynamic_weights

    return get_dynamic_weights(session)


@router.post("/paper/manual-buy")
def post_manual_buy(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.trader_console_service import manual_paper_buy

    actor = str((body or {}).get("actor") or _op or "operator")
    out = manual_paper_buy(session, body, actor=actor)
    session.commit()
    return out
