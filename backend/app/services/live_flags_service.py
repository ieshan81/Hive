"""Locked live flag request ledger.

The current build records dry-runs and requests only. It never mutates
environment variables or unlocks live trading.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import LiveFlagChangeRequest, LiveReadinessReview
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager


CONFIRMATION_PHRASE = "I understand live trading is locked and requires separate human approval"
AI_ACTORS = {"ai", "gemini", "agent", "ai_advisor", "ai_research"}


class LiveFlagsService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()

    def status(self) -> dict[str, Any]:
        latest_req = self.session.exec(
            select(LiveFlagChangeRequest).order_by(LiveFlagChangeRequest.created_at.desc()).limit(1)
        ).first()
        latest_review = self.session.exec(
            select(LiveReadinessReview).order_by(LiveReadinessReview.created_at.desc()).limit(1)
        ).first()
        return {
            "status": "ok",
            "live_locked": True,
            "paper_broker": is_paper_broker_url(),
            "live_orders_enabled": False,
            "live_trading_enabled": False,
            "ai_can_change_live_flags": False,
            "confirmation_phrase_required": CONFIRMATION_PHRASE,
            "latest_request": self._request_row(latest_req) if latest_req else None,
            "latest_readiness_review": self._review_row(latest_review) if latest_review else None,
            **live_lock_status(self.config),
        }

    def dry_run(self, body: dict[str, Any]) -> dict[str, Any]:
        actor_type = str(body.get("actor_type") or "operator").lower()
        requested = body.get("requested_flags") or {}
        blockers = self._blockers(actor_type, str(body.get("confirmation_phrase") or ""), requested)
        return {
            "status": "blocked" if blockers else "preview",
            "would_mutate": False,
            "live_flags_changed": False,
            "requested_flags": requested,
            "current_flags": self._current_flags(),
            "blockers": blockers or ["live_flag_changes_are_ledger_only_in_this_build"],
            "paper_broker": is_paper_broker_url(),
            "live_locked": True,
        }

    def request_change(self, body: dict[str, Any]) -> dict[str, Any]:
        actor_type = str(body.get("actor_type") or "operator").lower()
        phrase = str(body.get("confirmation_phrase") or "")
        requested = body.get("requested_flags") or {}
        blockers = self._blockers(actor_type, phrase, requested)
        dry = {
            "would_mutate": False,
            "blockers": blockers or ["live_flag_changes_are_ledger_only_in_this_build"],
            "live_flags_changed": False,
        }
        row = LiveFlagChangeRequest(
            requested_by=str(body.get("requested_by") or "operator"),
            actor_type=actor_type,
            current_flags_json=self._current_flags(),
            requested_flags_json=requested,
            status="rejected" if blockers else "requested_review_only",
            confirmation_phrase_ok=phrase == CONFIRMATION_PHRASE,
            approval_stage="human_review_required",
            dry_run_result_json=dry,
            audit_log_json={"ai_actor_blocked": actor_type in AI_ACTORS, "created_by_service": "live_flags_service"},
            rejected_reason=", ".join(blockers) if blockers else None,
        )
        self.session.add(row)
        self.session.flush()
        return {
            "status": row.status,
            "request": self._request_row(row),
            "live_flags_changed": False,
            "blockers": blockers,
        }

    def approve_change(self, body: dict[str, Any]) -> dict[str, Any]:
        actor_type = str(body.get("actor_type") or "operator").lower()
        if actor_type in AI_ACTORS:
            return {"status": "blocked", "reason": "AI cannot approve live flag changes", "live_flags_changed": False}
        req_id = body.get("request_id")
        row = self.session.get(LiveFlagChangeRequest, int(req_id)) if req_id else None
        if not row:
            return {"status": "not_found", "request_id": req_id, "live_flags_changed": False}
        row.status = "rejected"
        row.rejected_reason = "Live flag mutation is disabled in this paper-only build"
        row.approved_at = datetime.utcnow()
        self.session.add(row)
        return {
            "status": "rejected",
            "request": self._request_row(row),
            "live_flags_changed": False,
            "reason": row.rejected_reason,
        }

    def record_readiness_review(self, body: dict[str, Any]) -> dict[str, Any]:
        row = LiveReadinessReview(
            stage=str(body.get("stage") or "PAPER_LOCKED"),
            status="locked",
            account_snapshot_json=body.get("account_snapshot"),
            paper_performance_json=body.get("paper_performance"),
            risk_evidence_json=body.get("risk_evidence"),
            reconciliation_status_json=body.get("reconciliation_status"),
            kill_switch_status_json=body.get("kill_switch_status"),
            approval_required=True,
        )
        self.session.add(row)
        self.session.flush()
        return {"status": "ok", "review": self._review_row(row)}

    def _blockers(self, actor_type: str, phrase: str, requested: dict[str, Any]) -> list[str]:
        blockers = []
        if actor_type in AI_ACTORS:
            blockers.append("AI_ACTOR_FORBIDDEN")
        if phrase != CONFIRMATION_PHRASE:
            blockers.append("CONFIRMATION_PHRASE_REQUIRED")
        if not is_paper_broker_url():
            blockers.append("BROKER_NOT_PAPER")
        if requested.get("live_trading_enabled") or requested.get("live_orders_enabled"):
            blockers.append("LIVE_ENABLE_REQUEST_REQUIRES_SEPARATE_OUT_OF_BAND_APPROVAL")
        stage = str((self.config.get("promotion") or {}).get("current_stage", "PAPER"))
        if stage != "STANDARD_LIVE_CANDIDATE":
            blockers.append("PROMOTION_STAGE_NOT_LIVE_READY")
        return blockers

    def _current_flags(self) -> dict[str, Any]:
        return {
            "live_trading_enabled": False,
            "execution.live_orders_enabled": False,
            "promotion.current_stage": (self.config.get("promotion") or {}).get("current_stage", "PAPER"),
            "paper_trading_only": True,
        }

    @staticmethod
    def _request_row(r: LiveFlagChangeRequest) -> dict[str, Any]:
        return {
            "id": r.id,
            "requested_by": r.requested_by,
            "actor_type": r.actor_type,
            "status": r.status,
            "confirmation_phrase_ok": r.confirmation_phrase_ok,
            "approval_stage": r.approval_stage,
            "rejected_reason": r.rejected_reason,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }

    @staticmethod
    def _review_row(r: LiveReadinessReview) -> dict[str, Any]:
        return {
            "id": r.id,
            "stage": r.stage,
            "status": r.status,
            "approval_required": r.approval_required,
            "approved_by": r.approved_by,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }

