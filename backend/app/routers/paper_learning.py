"""Aggressive paper learning API — enable/disable and experiment evaluation only."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from app.database import OrderRecord, get_session
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService

router = APIRouter(prefix="/api/paper-learning", tags=["paper-learning"])


def _block_ai(body: dict) -> None:
    actor = (body or {}).get("actor", "")
    if str(actor).lower() in ("ai", "ai_advisory"):
        raise HTTPException(403, "AI cannot control paper learning endpoints")


@router.get("/status")
def paper_learning_status(session: Session = Depends(get_session)):
    return AggressivePaperLearningService(session).status()


@router.post("/enable")
def paper_learning_enable(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai(body)
    out = AggressivePaperLearningService(session).enable(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/disable")
def paper_learning_disable(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai(body)
    out = AggressivePaperLearningService(session).disable(body.get("operator", "operator"))
    session.commit()
    return out


@router.get("/config")
def paper_learning_config(session: Session = Depends(get_session)):
    svc = AggressivePaperLearningService(session)
    return {"status": "ok", "config": svc.cfg}


@router.post("/config/update")
def paper_learning_config_update(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai(body)
    patch = body.get("config") or body
    out = AggressivePaperLearningService(session).update_config(patch)
    session.commit()
    return out


@router.get("/eligible-strategies")
def paper_learning_eligible(session: Session = Depends(get_session)):
    svc = AggressivePaperLearningService(session)
    return {"status": "ok", "eligible": svc.eligible_strategies()}


@router.post("/evaluate")
def paper_learning_evaluate(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai(body)
    orders_before = len(session.exec(select(OrderRecord)).all())
    svc = AggressivePaperLearningService(session)
    out = svc.evaluate(
        body.get("strategy_id", "crypto_mean_reversion"),
        body.get("symbol", "BTC/USD"),
        side=body.get("side", "buy"),
        signal_id=body.get("signal_id"),
    )
    session.commit()
    out["orders_unchanged"] = svc.assert_no_new_orders(orders_before)
    return out


@router.post("/run-cycle")
def paper_learning_run_cycle(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai(body)
    svc = AggressivePaperLearningService(session)
    if not svc.cfg.get("mode_enabled"):
        return {"status": "skipped", "message": "Paper learning disabled"}
    monitor = svc.monitor_open_experiments()
    session.commit()
    return {"status": "ok", "monitor": monitor, "message": "Monitor only — orders via caged execution"}


@router.get("/decisions")
def paper_learning_decisions(session: Session = Depends(get_session)):
    return {"status": "ok", "decisions": AggressivePaperLearningService(session).list_decisions()}


@router.get("/outcomes")
def paper_learning_outcomes(session: Session = Depends(get_session)):
    return {"status": "ok", "outcomes": AggressivePaperLearningService(session).list_outcomes()}


@router.get("/memories")
def paper_learning_memories(session: Session = Depends(get_session)):
    return {"status": "ok", "memories": AggressivePaperLearningService(session).list_memories()}
