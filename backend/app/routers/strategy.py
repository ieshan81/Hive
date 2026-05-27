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

    return no_trade_reasons(session)


@router.get("/push-pull/latest")
def pp_latest(session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).latest_tick()
