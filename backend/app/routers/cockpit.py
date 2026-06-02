"""Caged Hive Quant — canonical live API (research v2 runtime). No page-state cache."""

from fastapi import APIRouter, Body, Depends, Query
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api", tags=["cockpit"])


@router.get("/cockpit")
def get_cockpit(session: Session = Depends(get_session), details: bool = Query(False)):
    if details:
        from app.v2.cockpit_service import build_cockpit

        return build_cockpit(session)
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: must not fetch provider data, score universe, call Gemini, or mutate DB.
    return build_mission_control_status(session)


@router.get("/cockpit/summary")
def get_cockpit_summary(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: canonical dashboard payload.
    return build_mission_control_status(session)


@router.get("/mission-control/status")
def get_mission_control_status(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: canonical dashboard payload.
    return build_mission_control_status(session)


@router.get("/mission-control/tiles")
def get_mission_control_tiles(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_tiles

    # READ ONLY fast-path: only the cockpit status tiles (account + execution safety),
    # skipping the heavy aggregations so the tiles stay fast under contention.
    return build_mission_control_tiles(session)


@router.get("/watchlist")
def get_watchlist(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY compatibility alias. Use POST /api/universe/refresh for live rebuilds.
    st = build_mission_control_status(session)
    candidates = (st.get("universe") or {}).get("top_candidates") or []
    return {
        "status": st.get("status"),
        "source": "mission_control_read_model",
        "generated_at_utc": st.get("generated_at_utc"),
        "all_symbols": [{"symbol": c.get("symbol"), "asset_type": c.get("asset_class")} for c in candidates if c.get("symbol")],
        "total": len(candidates),
    }


@router.get("/funnel")
def get_funnel(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY compatibility alias. Use POST /api/universe/refresh for live rebuilds.
    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "funnel": universe.get("funnel"),
        "shortlist": (st.get("eligible_entries_summary") or {}).get("top_candidates") or [],
        "block_breakdown": {
            b.get("code"): b.get("count") for b in universe.get("top_blockers") or [] if b.get("code")
        },
        "why_zero_shortlist": (st.get("why_no_trade_summary") or {}).get("plain"),
    }


@router.post("/rebuild")
def post_rebuild(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Hard nuke + aggressive profile + paper ON + bar refresh + agent cycles.

    GUARDED: refuses during an active validation run and without the confirmation phrase; the
    destructive rebuild is never reached on refusal (see rebuild_guard)."""
    from app.v2.rebuild import full_rebuild

    return full_rebuild(
        session,
        operator=str(body.get("operator") or "operator"),
        confirmation_phrase=str(body.get("confirmation") or body.get("confirmation_phrase") or ""),
        validation_run_override_reason=str(body.get("validation_run_override_reason") or ""),
        engines_stopped_ack=bool(body.get("engines_stopped_ack") or body.get("engines_stopped") or False),
    )


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
