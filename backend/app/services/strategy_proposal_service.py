"""Controlled strategy improvement proposals — never unlock live or locked keys."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import StrategyChangeProposal
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get

LOCKED_KEYS = frozenset(
    {
        "promotion.current_stage",
        "execution.live_orders_enabled",
        "live_trading_enabled",
        "kill.manual_master_active",
    }
)


class StrategyProposalService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def list_proposals(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        q = select(StrategyChangeProposal).order_by(StrategyChangeProposal.created_at.desc()).limit(limit)
        rows = list(self.session.exec(q).all())
        if status:
            rows = [r for r in rows if r.status == status]
        return [self._serialize(r) for r in rows]

    def create(
        self,
        *,
        proposal_type: str,
        strategy_id: str,
        reason: str,
        patch_json: Optional[dict] = None,
        memory_evidence_ids: Optional[list] = None,
        backtest_run_id: Optional[str] = None,
        risk_note: str = "",
        proposed_by: str = "system",
    ) -> dict[str, Any]:
        for k in (patch_json or {}):
            if k in LOCKED_KEYS or "live" in k.lower():
                return {"status": "error", "message": f"Cannot propose change to locked key: {k}"}
        row = StrategyChangeProposal(
            proposal_type=proposal_type,
            strategy_id=strategy_id,
            patch_json=patch_json or {},
            reason=reason[:500],
            memory_evidence_ids=memory_evidence_ids or [],
            backtest_run_id=backtest_run_id,
            risk_note=risk_note[:300],
            status="proposed",
            requires_operator_approval=True,
            expected_risk=risk_note[:200] or "Paper-only experiment",
            proposed_by=proposed_by,
        )
        self.session.add(row)
        self.session.flush()
        return {"status": "ok", "proposal": self._serialize(row)}

    def approve(self, proposal_id: int, operator: str = "operator") -> dict[str, Any]:
        row = self.session.get(StrategyChangeProposal, proposal_id)
        if not row:
            return {"status": "error", "message": "Proposal not found"}
        if row.status != "proposed":
            return {"status": "error", "message": f"Proposal status is {row.status}"}
        patch = row.patch_json or {}
        for k in patch:
            if k in LOCKED_KEYS:
                return {"status": "error", "message": f"Refusing locked key: {k}"}
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        if proposal_type_applies_to_strategy_params(row.proposal_type):
            strat_key = row.strategy_id.replace("-", "_")
            merged = dict(cur)
            merged.setdefault("strategies", {})
            merged["strategies"][strat_key] = {**(cur.get("strategies", {}).get(strat_key) or {}), **patch}
            cfg_mgr._activate(merged, operator, f"proposal_approve_{proposal_id}")
        row.status = "accepted"
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return {"status": "ok", "proposal": self._serialize(row)}

    def reject(self, proposal_id: int, operator: str = "operator") -> dict[str, Any]:
        row = self.session.get(StrategyChangeProposal, proposal_id)
        if not row:
            return {"status": "error", "message": "Proposal not found"}
        row.status = "rejected"
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return {"status": "ok", "proposal": self._serialize(row)}

    def _serialize(self, r: StrategyChangeProposal) -> dict:
        return {
            "id": r.id,
            "proposal_type": r.proposal_type,
            "strategy_id": r.strategy_id,
            "proposed_change": r.patch_json,
            "reason": r.reason,
            "memory_evidence_ids": r.memory_evidence_ids,
            "backtest_run_id": r.backtest_run_id,
            "expected_risk": r.expected_risk,
            "approval_required": r.requires_operator_approval,
            "status": r.status,
            "proposed_by": r.proposed_by,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }


def proposal_type_applies_to_strategy_params(proposal_type: str) -> bool:
    return proposal_type in ("parameter_change", "ranking_change", "symbol_universe")
