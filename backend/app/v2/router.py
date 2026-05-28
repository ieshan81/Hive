"""V2 API — hard nuke, rebuild, live cockpit, aggressive agent cycles."""

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/v2", tags=["v2"])


@router.get("/cockpit")
def v2_cockpit(session: Session = Depends(get_session)):
    from app.v2.cockpit_service import build_cockpit

    return build_cockpit(session)


@router.get("/watchlist")
def v2_watchlist(session: Session = Depends(get_session)):
    from app.v2.watchlist import live_full_watchlist

    return live_full_watchlist(session, force=True)


@router.get("/funnel")
def v2_funnel(session: Session = Depends(get_session)):
    from app.v2.live_pipeline import live_funnel

    return live_funnel(session)


@router.post("/nuke")
def v2_hard_nuke(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.v2.rebuild import hard_nuke

    return hard_nuke(session, operator=str(body.get("operator") or "operator"))


@router.post("/rebuild")
def v2_full_rebuild(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Hard nuke + aggressive profile + paper ON + bar refresh + 2 agent cycles."""
    from app.v2.rebuild import full_rebuild

    return full_rebuild(session, operator=str(body.get("operator") or "operator"))


@router.post("/cycle/run")
def v2_run_cycle(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.v2.agent_engine import run_agent_cycle

    return run_agent_cycle(session, operator=str(body.get("operator") or "operator"))


@router.post("/bootstrap")
def v2_bootstrap(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Alias for /rebuild — always hard nuke unless nuke_first=false explicitly."""
    from app.v2.rebuild import full_rebuild, hard_nuke

    operator = str(body.get("operator") or "operator")
    if body.get("nuke_first") is False:
        from app.v2.agent_engine import run_agent_cycle
        from app.services.paper_learning_start_service import start_fresh_paper_learning

        start = start_fresh_paper_learning(session, operator=operator)
        cycle = run_agent_cycle(session, operator=operator)
        return {"status": "ok", "paper_learning": start, "cycle": cycle}
    return full_rebuild(session, operator=operator)
