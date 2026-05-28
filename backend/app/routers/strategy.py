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
    from app.routers.push_pull import no_trade_reasons
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    live = no_trade_reasons(session)
    funnel = build_funnel_breakdown(session, max_evaluate=36, fetch_quotes=True)
    return {
        "status": "ok",
        "generated_at_utc": funnel.get("generated_at_utc"),
        "universe_funnel_answer": funnel.get("answer"),
        "universe_block_breakdown": funnel.get("block_breakdown"),
        "universe_funnel": funnel.get("funnel"),
        "available_symbols": funnel.get("available_symbols"),
        "evaluated_symbols": funnel.get("evaluated_symbols"),
        "eligible_count": funnel.get("eligible_count"),
        "live_scoring": live,
        "reason_breakdown": live.get("reason_breakdown"),
        "by_symbol": live.get("by_symbol"),
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
