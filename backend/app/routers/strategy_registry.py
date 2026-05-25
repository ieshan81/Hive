"""Strategy Promotion Pipeline API — deterministic gate only."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from app.database import (
    OrderRecord,
    StrategyAllocation,
    StrategyEligibilityWindow,
    StrategyLifecycleEvent,
    StrategyMemoryLink,
    StrategyRegistry,
    StrategyRejection,
    StrategyScorecard,
    StrategyValidationResult,
    SystemValidationAudit,
    get_session,
)
from app.services.config_manager import ConfigManager
from app.services.strategy_conflict_service import StrategyConflictService
from app.services.strategy_memory_validation_service import StrategyMemoryValidationService
from app.services.strategy_registry_service import StrategyRegistryService
from app.services.strategy_scorecard_service import StrategyScorecardService
from app.services.strategy_validation_gate import StrategyValidationGate
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/strategies", tags=["strategy-registry"])


def _block_ai_actor(body: dict) -> None:
    actor = (body or {}).get("actor") or (body or {}).get("decided_by") or ""
    if str(actor).lower() in ("ai", "ai_advisory", "ai_review"):
        raise HTTPException(403, "AI cannot invoke promotion endpoints")


@router.get("/registry")
def get_registry(session: Session = Depends(get_session)):
    return {"status": "ok", "strategies": StrategyRegistryService(session).list_registry()}


@router.get("/active")
def get_active(session: Session = Depends(get_session)):
    from app.services.strategy_registry_export import list_active_registry

    return {"status": "ok", "strategies": list_active_registry(session)}


@router.get("/paper-candidates")
def get_paper_candidates(session: Session = Depends(get_session)):
    return {
        "status": "ok",
        "strategies": StrategyRegistryService(session).list_registry(stage="paper_candidate"),
    }


@router.get("/rejected")
def get_rejected(session: Session = Depends(get_session)):
    return {
        "status": "ok",
        "strategies": StrategyRegistryService(session).list_registry(stage="rejected"),
    }


@router.get("/conflicts")
def get_conflicts(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return {"status": "ok", "conflicts": StrategyConflictService(session, cfg).list_conflicts()}


@router.get("/allocations")
def get_allocations(session: Session = Depends(get_session)):
    rows = session.exec(select(StrategyAllocation).order_by(StrategyAllocation.created_at.desc()).limit(50)).all()
    return {
        "status": "ok",
        "allocations": [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "risk_budget_pct": r.risk_budget_pct,
                "max_position_usd": r.max_position_usd,
                "max_open_positions": r.max_open_positions,
            }
            for r in rows
        ],
    }


@router.get("/imported")
def strategies_imported(session: Session = Depends(get_session)):
    from app.services.strategy_import_service import StrategyImportService

    strategies = StrategyImportService(session).list_imported()
    return {
        "status": "ok",
        "imported_count": len(strategies),
        "strategies": strategies,
        "message": "No strategies imported yet." if not strategies else f"{len(strategies)} imported strateg(ies).",
    }




@router.get("/{strategy_id}")
def get_strategy(strategy_id: str, session: Session = Depends(get_session)):
    row = StrategyRegistryService(session).get(strategy_id)
    if not row:
        return {"status": "error", "message": "not found"}
    return {"status": "ok", "strategy": row}


@router.get("/{strategy_id}/scorecard")
def get_scorecard(strategy_id: str, session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    sc = StrategyScorecardService(session, cfg).latest(strategy_id)
    return {"status": "ok", "scorecard": sc}


@router.get("/{strategy_id}/memories")
def get_memories(strategy_id: str, session: Session = Depends(get_session)):
    links = session.exec(
        select(StrategyMemoryLink).where(StrategyMemoryLink.strategy_id == strategy_id)
    ).all()
    return {
        "status": "ok",
        "memories": [
            {
                "memory_id": l.memory_id,
                "memory_type": l.memory_type,
                "memory_status": l.memory_status,
                "can_influence_ranking": l.can_influence_ranking,
                "visible_to_ai": l.visible_to_ai,
            }
            for l in links
        ],
    }


@router.get("/{strategy_id}/lifecycle")
def get_lifecycle(strategy_id: str, session: Session = Depends(get_session)):
    rows = session.exec(
        select(StrategyLifecycleEvent)
        .where(StrategyLifecycleEvent.strategy_id == strategy_id)
        .order_by(StrategyLifecycleEvent.created_at.desc())
        .limit(50)
    ).all()
    return {
        "status": "ok",
        "events": [
            {
                "from_stage": r.from_stage,
                "to_stage": r.to_stage,
                "reason_code": r.reason_code,
                "reason_text": r.reason_text,
                "decided_by": r.decided_by,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{strategy_id}/validation-results")
def get_validation_results(strategy_id: str, session: Session = Depends(get_session)):
    rows = session.exec(
        select(StrategyValidationResult)
        .where(StrategyValidationResult.strategy_id == strategy_id)
        .order_by(StrategyValidationResult.created_at.desc())
        .limit(20)
    ).all()
    return {"status": "ok", "results": [{"gate_name": r.gate_name, "passed": r.passed, "target_stage": r.target_stage} for r in rows]}


@router.get("/{strategy_id}/eligibility-window")
def get_eligibility(strategy_id: str, session: Session = Depends(get_session)):
    row = session.exec(
        select(StrategyEligibilityWindow)
        .where(StrategyEligibilityWindow.strategy_id == strategy_id)
        .order_by(StrategyEligibilityWindow.created_at.desc())
    ).first()
    if not row:
        return {"status": "ok", "window": None}
    return {
        "status": "ok",
        "window": {
            "eligibility_start_at_utc": row.eligibility_start_at_utc.isoformat() + "Z",
            "earliest_promote_at_utc": row.earliest_promote_at_utc.isoformat() + "Z",
            "latest_decision_at_utc": row.latest_decision_at_utc.isoformat() + "Z",
            "eligibility_health": row.eligibility_health,
            "hard_block_reason": row.hard_block_reason,
            "decision": row.decision,
        },
    }


@router.post("/registry/sync-from-lab")
def sync_from_lab(session: Session = Depends(get_session)):
    out = StrategyRegistryService(session).sync_from_lab()
    session.commit()
    return out


@router.post("/validate")
def validate_all(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    out = StrategyValidationGate(session).validate_all()
    session.commit()
    return out


@router.post("/promote-candidates")
def promote_candidates(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    orders_before = len(session.exec(select(OrderRecord)).all())
    out = StrategyValidationGate(session).promote_candidates()
    session.commit()
    orders_after = len(session.exec(select(OrderRecord)).all())
    out["orders_unchanged"] = orders_before == orders_after
    return out


@router.post("/retire-failed")
def retire_failed(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    out = StrategyValidationGate(session).retire_failed()
    session.commit()
    return out


@router.post("/rebalance")
def rebalance(body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    cfg = ConfigManager(session).get_current()
    out = StrategyConflictService(session, cfg).evaluate()
    session.commit()
    return out


@router.post("/memories/validate")
def validate_memories(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    svc = StrategyMemoryValidationService(session, cfg)
    out = svc.validate_all_pending()
    out["synced"] = svc.sync_link_status_to_lessons()
    session.commit()
    return out


@router.post("/pause/{strategy_id}")
def pause_strategy(strategy_id: str, body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    out = StrategyValidationGate(session).pause(strategy_id, body.get("reason", "operator_pause"))
    session.commit()
    return out


@router.post("/resume/{strategy_id}")
def resume_strategy(strategy_id: str, body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    out = StrategyValidationGate(session).resume(strategy_id)
    session.commit()
    return out


@router.post("/experiment-eligibility/scan")
def experiment_eligibility_scan(session: Session = Depends(get_session)):
    from app.services.aggressive_paper_learning_service import AggressivePaperLearningService

    return AggressivePaperLearningService(session).scan_experiment_eligibility()


@router.post("/{strategy_id}/mark-paper-experiment")
def mark_paper_experiment(strategy_id: str, body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    out = StrategyRegistryService(session).mark_paper_experiment(
        strategy_id, body.get("reason", "operator_mark_experiment")
    )
    session.commit()
    return out


@router.post("/{strategy_id}/pause-experiment")
def pause_experiment(strategy_id: str, body: dict = Body(default={}), session: Session = Depends(get_session)):
    _block_ai_actor(body)
    out = StrategyRegistryService(session).pause_experiment(
        strategy_id, body.get("reason", "experiment_daily_cap")
    )
    session.commit()
    return out


@router.post("/import")
def strategies_import(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.strategy_import_service import StrategyImportService

    _block_ai_actor(body)
    svc = StrategyImportService(session)
    if body.get("manifest"):
        out = svc.import_manifest(body["manifest"], body.get("python_source"))
    elif body.get("path"):
        out = svc.import_file(body["path"])
    else:
        out = {"status": "error", "message": "manifest or path required"}
    session.commit()
    return out


