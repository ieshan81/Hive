"""Controlled Research OS graph runner.

Default implementation is deterministic and local. LangGraph can be added as an
adapter later without changing API semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import AIAgentRun, ResearchJob
from app.schemas.research_os import AgentOutput


AGENT_NODES = [
    "ResearchDirector",
    "StrategyDiscovery",
    "Backtest",
    "WalkForwardValidation",
    "Risk",
    "PortfolioFit",
    "ExecutionPolicy",
    "Memory",
    "Audit",
    "HumanApprovalQueue",
    "BudgetCost",
    "CodeProposal",
    "DeploymentReadiness",
]


FORBIDDEN_AGENT_CAPABILITIES = {
    "submit_orders": False,
    "cancel_orders": False,
    "change_live_flags": False,
    "approve_promotion": False,
    "merge_code": False,
    "deploy_code": False,
}


class AgentGraphService:
    def __init__(self, session: Session):
        self.session = session

    def status(self) -> dict[str, Any]:
        latest = self.session.exec(select(AIAgentRun).order_by(AIAgentRun.id.desc()).limit(1)).first()
        return {
            "status": "ok",
            "orchestrator": "local_deterministic_graph",
            "langgraph_required": False,
            "nodes": AGENT_NODES,
            "forbidden_capabilities": FORBIDDEN_AGENT_CAPABILITIES,
            "latest_run": None
            if not latest
            else {
                "graph_run_id": latest.graph_run_id,
                "agent_name": latest.agent_name,
                "node_name": latest.node_name,
                "status": latest.status,
                "completed_at": latest.completed_at.isoformat() + "Z" if latest.completed_at else None,
            },
        }

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        rows = self.session.exec(select(AIAgentRun).order_by(AIAgentRun.id.desc()).limit(limit)).all()
        return {
            "status": "ok",
            "runs": [
                {
                    "graph_run_id": r.graph_run_id,
                    "agent_name": r.agent_name,
                    "node_name": r.node_name,
                    "status": r.status,
                    "output": r.output_json,
                    "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() + "Z" if r.completed_at else None,
                }
                for r in rows
            ],
        }

    def run_dry(self, payload: dict[str, Any] | None = None, *, actor: str = "operator") -> dict[str, Any]:
        graph_run_id = f"graph_{uuid.uuid4().hex[:12]}"
        job = ResearchJob(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            job_type="agent_loop_dry_run",
            status="running",
            requested_by=actor,
            input_json=payload or {},
            progress_pct=5,
            started_at=datetime.utcnow(),
        )
        self.session.add(job)
        self.session.flush()
        outputs = []
        for node in AGENT_NODES:
            output = AgentOutput(
                graph_run_id=graph_run_id,
                agent_name=node,
                node_name=node,
                status="complete",
                output={
                    "mode": "dry_run",
                    "orders_submitted": 0,
                    "live_flags_changed": False,
                    "requires_human_approval": node in ("HumanApprovalQueue", "DeploymentReadiness"),
                },
                tool_calls=[],
            )
            row = AIAgentRun(
                graph_run_id=output.graph_run_id,
                agent_name=output.agent_name,
                node_name=output.node_name,
                status=output.status,
                input_json=payload or {},
                output_json=output.output,
                tool_calls_json=output.tool_calls,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            self.session.add(row)
            outputs.append(output.model_dump())
        job.status = "complete"
        job.progress_pct = 100
        job.output_json = {
            "graph_run_id": graph_run_id,
            "nodes_completed": len(outputs),
            "orders_submitted": 0,
            "live_flags_changed": False,
        }
        job.completed_at = datetime.utcnow()
        self.session.add(job)
        return {
            "status": "ok",
            "graph_run_id": graph_run_id,
            "nodes_completed": len(outputs),
            "orders_submitted": 0,
            "live_flags_changed": False,
            "capabilities": FORBIDDEN_AGENT_CAPABILITIES,
            "outputs": outputs,
        }

    def run_paper_research(self, payload: dict[str, Any] | None = None, *, actor: str = "operator") -> dict[str, Any]:
        out = self.run_dry({**(payload or {}), "paper_research": True}, actor=actor)
        out["paper_research_note"] = "Research loop completed. Paper execution must be requested through caged services."
        return out

