"""Research OS API.

GET routes are read-only DB/cache projections. POST routes are operator actions
and may create jobs/ledger rows, but they never submit broker orders.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from app.database import (
    AIAgentRun,
    CodeProposal,
    LessonNode,
    ResearchBacktestRun,
    StrategyChangeProposal,
    get_session,
)
from app.services.agent_graph_service import AgentGraphService
from app.services.code_proposal_service import CodeProposalService
from app.services.live_flags_service import LiveFlagsService
from app.services.operator_auth import require_operator_token
from app.services.research_os_service import ResearchOSReadService, ResearchOSService

router = APIRouter(prefix="/api/research", tags=["research-os"])


def _actor(body: dict) -> str:
    return str((body or {}).get("actor") or (body or {}).get("requested_by") or "operator")


def _block_ai_dangerous(body: dict) -> None:
    if _actor(body).lower() in ("ai", "gemini", "agent", "ai_advisor", "ai_research"):
        raise HTTPException(403, "AI actor cannot invoke this operator action")


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """READ ONLY: Research OS dashboard projection."""
    return ResearchOSReadService(session).status()


@router.get("/jobs")
def jobs(session: Session = Depends(get_session)):
    """READ ONLY: persisted research jobs."""
    return ResearchOSService(session).list_jobs()


@router.get("/jobs/{job_id}")
def job(job_id: str, session: Session = Depends(get_session)):
    """READ ONLY: persisted research job detail."""
    return ResearchOSService(session).get_job(job_id)


@router.get("/strategies")
def strategies(session: Session = Depends(get_session)):
    """READ ONLY: strategy specs plus reused existing definitions."""
    return ResearchOSService(session).list_strategy_specs()


@router.get("/strategies/{strategy_id}")
def strategy(strategy_id: str, session: Session = Depends(get_session)):
    """READ ONLY: strategy spec detail."""
    return ResearchOSService(session).get_strategy_spec(strategy_id)


@router.get("/backtests")
def backtests(limit: int = 50, session: Session = Depends(get_session)):
    """READ ONLY: latest persisted backtest runs."""
    rows = session.exec(select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(limit)).all()
    return {
        "status": "ok",
        "backtests": [
            {
                "run_id": r.run_id,
                "strategy_id": r.strategy_id,
                "symbols": r.symbols,
                "status": r.status,
                "num_trades": r.num_trades,
                "metrics": r.metrics_json,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/backtests/{run_id}")
def backtest(run_id: str, session: Session = Depends(get_session)):
    """READ ONLY: backtest detail."""
    row = session.exec(select(ResearchBacktestRun).where(ResearchBacktestRun.run_id == run_id)).first()
    if not row:
        return {"status": "not_found", "run_id": run_id}
    return {
        "status": "ok",
        "backtest": {
            "run_id": row.run_id,
            "strategy_id": row.strategy_id,
            "symbols": row.symbols,
            "status": row.status,
            "num_trades": row.num_trades,
            "metrics": row.metrics_json,
            "warnings": row.warnings,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        },
    }


@router.get("/promotions")
def promotions(limit: int = 50, session: Session = Depends(get_session)):
    """READ ONLY: promotion/config change proposals."""
    rows = session.exec(select(StrategyChangeProposal).order_by(StrategyChangeProposal.created_at.desc()).limit(limit)).all()
    return {
        "status": "ok",
        "promotions": [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "proposal_type": r.proposal_type,
                "status": r.status,
                "requires_operator_approval": r.requires_operator_approval,
                "proposed_by": r.proposed_by,
            }
            for r in rows
        ],
    }


@router.get("/memory")
def memory(limit: int = 50, session: Session = Depends(get_session)):
    """READ ONLY: evidence-backed lesson memory."""
    rows = session.exec(select(LessonNode).order_by(LessonNode.created_at.desc()).limit(limit)).all()
    return {
        "status": "ok",
        "memory": [
            {
                "id": r.id,
                "memory_type": r.memory_type,
                "symbol": r.symbol,
                "strategy_id": r.strategy_id,
                "title": r.title,
                "summary": r.summary,
                "status": r.status,
                "can_influence_ranking": r.can_influence_ranking,
            }
            for r in rows
        ],
    }


@router.get("/agent-runs")
def agent_runs(session: Session = Depends(get_session)):
    """READ ONLY: agent graph run ledger."""
    return AgentGraphService(session).list_runs()


@router.get("/code-proposals")
def code_proposals(session: Session = Depends(get_session)):
    """READ ONLY: code proposal drafts."""
    return CodeProposalService(session).list()


@router.get("/live-readiness")
def live_readiness(session: Session = Depends(get_session)):
    """READ ONLY: live remains locked."""
    return LiveFlagsService(session).status()


@router.post("/strategy-specs/create")
def create_strategy_spec(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: validate and persist a StrategySpec. No orders."""
    _block_ai_dangerous(body)
    out = ResearchOSService(session).create_strategy_spec(body, actor=_actor(body))
    session.commit()
    return out


@router.post("/backtests/run")
def run_backtest(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: run research backtest using existing lab service. No orders."""
    _block_ai_dangerous(body)
    out = ResearchOSService(session).run_backtest(body, requested_by=_actor(body))
    session.commit()
    return out


@router.post("/optimization/run")
def run_optimization(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: create deterministic optimization ledger. No orders."""
    _block_ai_dangerous(body)
    out = ResearchOSService(session).run_optimization(body, requested_by=_actor(body))
    session.commit()
    return out


@router.post("/validation/run")
def run_validation(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: validation currently delegates to risk audit scaffold."""
    _block_ai_dangerous(body)
    out = ResearchOSService(session).run_risk_audit(body, requested_by=_actor(body))
    session.commit()
    return out


@router.post("/risk-audit/run")
def run_risk_audit(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: deterministic risk audit. No orders."""
    _block_ai_dangerous(body)
    out = ResearchOSService(session).run_risk_audit(body, requested_by=_actor(body))
    session.commit()
    return out


@router.post("/promotion/propose")
def promotion_propose(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: create human-review promotion proposal. No auto-promotion."""
    _block_ai_dangerous(body)
    out = ResearchOSService(session).propose_promotion(body, actor=_actor(body))
    session.commit()
    return out


@router.post("/promotion/approve")
def promotion_approve(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: approval acknowledgement only; live stays locked."""
    _block_ai_dangerous(body)
    return {"status": "blocked", "reason": "Promotion apply requires existing deterministic promotion gate", "applied": False}


@router.post("/agent-loop/run-dry")
def agent_loop_run_dry(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: controlled dry-run graph. No orders or live changes."""
    out = AgentGraphService(session).run_dry(body, actor=_actor(body))
    session.commit()
    return out


@router.post("/agent-loop/run-paper-research")
def agent_loop_run_paper_research(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: controlled research graph. Execution still requires cage path."""
    out = AgentGraphService(session).run_paper_research(body, actor=_actor(body))
    session.commit()
    return out


@router.post("/code-proposals/create")
def code_proposal_create(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: store draft code proposal only. No file writes."""
    out = CodeProposalService(session).create(body, actor=_actor(body))
    session.commit()
    return out


@router.post("/code-proposals/approve-draft")
def code_proposal_approve_draft(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: mark draft for human review only."""
    _block_ai_dangerous(body)
    out = CodeProposalService(session).approve_draft(str(body.get("proposal_id")), actor=_actor(body))
    session.commit()
    return out

