"""Strategy status — live scoring path proof."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.strategy_status_service import candidate_rankings, strategy_status

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/status")
def get_strategy_status(session: Session = Depends(get_session)):
    return strategy_status(session)


@router.get("/candidate-rankings")
def get_candidate_rankings(session: Session = Depends(get_session)):
    return candidate_rankings(session)


# ─────────────────────────────────────────────────────────────────────────
# Spec-required aliases  (GET /api/strategy/push-pull/...)
# These delegate to the push_pull router so the live scoring path is the
# canonical engine, not a placeholder.
# ─────────────────────────────────────────────────────────────────────────

@router.get("/push-pull/scores")
def pp_scores(session: Session = Depends(get_session)):
    from app.routers.push_pull import live_scores

    return live_scores(session)


@router.get("/push-pull/candidates")
def pp_candidates(session: Session = Depends(get_session)):
    from app.routers.push_pull import live_candidates

    return live_candidates(session)


@router.get("/push-pull/no-trade-reasons")
def pp_reasons(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    breakdown = {b.get("code"): b.get("count") for b in universe.get("top_blockers") or [] if b.get("code")}
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "universe_funnel_answer": (st.get("why_no_trade_summary") or {}).get("plain"),
        "universe_block_breakdown": breakdown,
        "universe_funnel": universe.get("funnel"),
        "available_symbols": (universe.get("funnel") or {}).get("available", 0),
        "evaluated_symbols": (universe.get("funnel") or {}).get("scored", 0),
        "eligible_count": (universe.get("funnel") or {}).get("eligible", 0),
        "live_scoring": {"status": "read_model_only"},
        "reason_breakdown": breakdown,
        "by_symbol": {},
        "read_model_only": True,
    }

@router.get("/push-pull/latest")
def pp_latest(session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).latest_tick()


@router.get("/push-pull/verdict")
def push_pull_verdict(session: Session = Depends(get_session)):
    """Fast verdict for legacy UI polls — uses cockpit truth, not heavy discovery."""
    from app.v2.cockpit_service import build_cockpit_summary

    c = build_cockpit_summary(session)
    ctrl = c.get("control") or {}
    return {
        "status": "ok",
        "current_status": "ready" if ctrl.get("bot_can_place") else "blocked",
        "should_paper_trade_now": bool(ctrl.get("can_place_paper_orders")),
        "funnel_answer": c.get("ai_cockpit_message"),
        "plain_verdict": c.get("ai_cockpit_message"),
        "funnel": c.get("funnel"),
        "shortlist_count": (c.get("funnel") or {}).get("shortlist", 0),
    }
