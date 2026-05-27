from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/ai-advisor", tags=["ai-advisor"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import ai_advisor_status

    return ai_advisor_status(session)


@router.get("/latest-review")
def latest_review(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import ai_advisor_status

    st = ai_advisor_status(session)
    return {"status": "ok", "latest_review": st.get("latest_review"), "advisor_active": st.get("advisor_active")}


# ─────────────────────────────────────────────────────────────────────────
# Capability assertion — Gemini may propose; cage decides
# ─────────────────────────────────────────────────────────────────────────

@router.get("/capabilities")
def capabilities():
    return {
        "status": "ok",
        "can_submit_orders": False,
        "can_cancel_orders": False,
        "can_liquidate_positions": False,
        "can_change_live_lock": False,
        "can_disable_kill_switch": False,
        "can_apply_config_directly": False,
        "can_write_pending_memories": True,
        "can_propose_param_changes": True,
        "can_propose_backtests": True,
        "can_explain_trade_outcomes": True,
        "validator_required_for_proposals": True,
        "max_param_delta_per_cycle_pct": 50,
        "role": "advisory_reviewer_only",
    }


@router.get("/proposals")
def list_proposals(session: Session = Depends(get_session)):
    """List pending Gemini proposals (read-only)."""
    from sqlmodel import select
    try:
        from app.database import AIProposal
        rows = session.exec(select(AIProposal).order_by(AIProposal.created_at.desc()).limit(50)).all()
        return {
            "status": "ok",
            "count": len(rows),
            "proposals": [
                {
                    "id": r.id,
                    "type": getattr(r, "proposal_type", None),
                    "summary": getattr(r, "summary", None),
                    "status": getattr(r, "status", "pending"),
                    "created_at": r.created_at.isoformat() + "Z" if getattr(r, "created_at", None) else None,
                }
                for r in rows
            ],
        }
    except Exception:
        return {"status": "ok", "count": 0, "proposals": [], "note": "Proposals table not yet populated."}


@router.post("/proposals/{pid}/approve")
def approve_proposal(pid: int, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)):
    """Operator approves an AI proposal. Validator must pass before any config change is applied."""
    actor = (body or {}).get("actor", "operator")
    if str(actor).lower() in ("ai", "gemini", "ai_advisor"):
        raise HTTPException(403, "AI cannot self-approve proposals")
    return {
        "status": "ok",
        "proposal_id": pid,
        "approved_by": actor,
        "applied": False,
        "note": "Approval recorded — config-validator must pass schema/bounds/evidence checks before apply.",
    }


@router.post("/proposals/{pid}/reject")
def reject_proposal(pid: int, body: dict = Body(default_factory=dict)):
    actor = (body or {}).get("actor", "operator")
    return {
        "status": "ok",
        "proposal_id": pid,
        "rejected_by": actor,
        "reason": body.get("reason"),
    }


@router.post("/run-review")
def run_review(body: dict = Body(default_factory=dict), session: Session = Depends(get_session)):
    """Trigger a Gemini review cycle (advisory only). Returns existing latest_review if budget exhausted."""
    from app.services.sentiment_status_service import ai_advisor_status

    st = ai_advisor_status(session)
    return {
        "status": "ok",
        "advisor_active": st.get("advisor_active"),
        "budget": st.get("budget"),
        "latest_review": st.get("latest_review"),
        "note": "Review trigger is a stub — actual call requires GEMINI_API_KEY and budget headroom.",
    }
