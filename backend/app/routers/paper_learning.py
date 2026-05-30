"""Aggressive paper learning API — enable/disable and experiment evaluation only."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from app.database import OrderRecord, get_session
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/paper-learning", tags=["paper-learning"])


def _block_ai(body: dict) -> None:
    from app.services.ai_boundaries import is_ai_actor

    if is_ai_actor((body or {}).get("actor", "")):
        raise HTTPException(403, "AI cannot control paper learning endpoints")


@router.get("/status")
def paper_learning_status(session: Session = Depends(get_session)):
    return AggressivePaperLearningService(session).status()


@router.post("/enable")
def paper_learning_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    out = AggressivePaperLearningService(session).enable(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/disable")
def paper_learning_disable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    out = AggressivePaperLearningService(session).disable(body.get("operator", "operator"))
    session.commit()
    return out


@router.get("/config")
def paper_learning_config(session: Session = Depends(get_session)):
    svc = AggressivePaperLearningService(session)
    return {"status": "ok", "config": svc.cfg}


@router.post("/config/update")
def paper_learning_config_update(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
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
def paper_learning_evaluate(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
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
def paper_learning_run_cycle(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
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


@router.post("/run-training-cycle")
def run_training_cycle(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    from app.services.training_execution_service import TrainingExecutionService

    orders_before = len(session.exec(select(OrderRecord)).all())
    out = TrainingExecutionService(session).run_training_cycle()
    session.commit()
    out["orders_before"] = orders_before
    out["orders_after"] = len(session.exec(select(OrderRecord)).all())
    out["broker_mode"] = "paper"
    out["live_trading_locked"] = True
    return out


@router.post("/execute-approved")
def execute_approved(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    from app.services.training_execution_service import TrainingExecutionService

    svc = TrainingExecutionService(session)
    decision_id = body.get("decision_id")
    if decision_id:
        out = svc.execute_approved_decision(int(decision_id))
    else:
        out = svc.execute_pending_approved(limit=int(body.get("limit", 1)))
    session.commit()
    return out


@router.get("/open-training-positions")
def open_training_positions(session: Session = Depends(get_session)):
    from app.services.training_execution_service import TrainingExecutionService

    return {
        "status": "ok",
        "positions": TrainingExecutionService(session).open_training_positions(),
        "broker_mode": "paper",
        "live_trading_locked": True,
    }


@router.post("/monitor-exits")
def monitor_exits(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    from app.services.training_execution_service import TrainingExecutionService

    out = TrainingExecutionService(session).monitor_exits()
    session.commit()
    return out


@router.get("/training-memories")
def training_memories(session: Session = Depends(get_session)):
    from app.services.training_execution_service import TrainingExecutionService

    return {"status": "ok", "memories": TrainingExecutionService(session).list_training_memories()}
