"""AI/operator code proposal ledger.

Proposals are draft artifacts only. This service never writes repo files,
merges branches, deploys, or changes live/runtime flags.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import CodeProposal
from app.schemas.research_os import CodeProposal as CodeProposalSchema


class CodeProposalService:
    def __init__(self, session: Session):
        self.session = session

    def list(self, limit: int = 50) -> dict[str, Any]:
        rows = self.session.exec(select(CodeProposal).order_by(CodeProposal.created_at.desc()).limit(limit)).all()
        return {"status": "ok", "proposals": [self._row(r) for r in rows]}

    def create(self, body: dict[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        proposal = CodeProposalSchema.model_validate(body)
        row = CodeProposal(
            proposal_id=f"code_{uuid.uuid4().hex[:12]}",
            title=proposal.title,
            description=proposal.description,
            proposed_by_agent=proposal.proposed_by_agent or actor,
            affected_files_json=proposal.affected_files,
            diff_text=proposal.diff_text,
            tests_required_json=proposal.tests_required,
            risk_assessment_json={
                **proposal.risk_assessment,
                "auto_apply_allowed": False,
                "auto_merge_allowed": False,
                "deploy_allowed": False,
                "live_flag_changes_allowed": False,
            },
            status="draft",
        )
        self.session.add(row)
        self.session.flush()
        return {"status": "ok", "proposal": self._row(row), "applied": False, "merged": False, "deployed": False}

    def approve_draft(self, proposal_id: str, *, actor: str = "operator") -> dict[str, Any]:
        if str(actor).lower() in ("ai", "gemini", "agent", "ai_advisor"):
            return {"status": "blocked", "reason": "AI cannot approve code proposals"}
        row = self.session.exec(select(CodeProposal).where(CodeProposal.proposal_id == proposal_id)).first()
        if not row:
            return {"status": "not_found", "proposal_id": proposal_id}
        row.status = "pending_review"
        row.reviewed_at = datetime.utcnow()
        self.session.add(row)
        return {
            "status": "ok",
            "proposal": self._row(row),
            "applied": False,
            "merged": False,
            "deployed": False,
            "note": "Draft approved for human review only. No code was applied.",
        }

    @staticmethod
    def _row(r: CodeProposal) -> dict[str, Any]:
        return {
            "proposal_id": r.proposal_id,
            "title": r.title,
            "description": r.description,
            "proposed_by_agent": r.proposed_by_agent,
            "affected_files": r.affected_files_json,
            "tests_required": r.tests_required_json,
            "risk_assessment": r.risk_assessment_json,
            "status": r.status,
            "branch_name": r.branch_name,
            "pr_url": r.pr_url,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            "reviewed_at": r.reviewed_at.isoformat() + "Z" if r.reviewed_at else None,
        }

