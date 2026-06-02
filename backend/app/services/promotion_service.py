"""Promotion stage system — human-controlled, not AI-writable."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PromotionStatus, TradeRecord
from app.services.engine_config import cfg_get, current_promotion_stage


class PromotionService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config

    def _row(self) -> PromotionStatus:
        row = self.session.get(PromotionStatus, 1)
        if not row:
            stage = current_promotion_stage(self.config)
            row = PromotionStatus(id=1, current_stage=stage, paper_started_at=datetime.utcnow(), metrics_json={})
            self.session.add(row)
            self.session.flush()
        return row

    def status(self) -> dict[str, Any]:
        row = self._row()
        stage = current_promotion_stage(self.config)
        closed = self.session.exec(
            select(TradeRecord).where(TradeRecord.status == "closed")
        ).all()
        # Single authoritative criteria source (shared with PromotionReadinessService + diagnostics).
        from app.services.promotion_criteria import authoritative_promotion_criteria

        authoritative = authoritative_promotion_criteria(self.config, session=self.session)
        criteria = authoritative["promotion_to_pre_live_criteria"]  # the gate that controls live/pre-live
        return {
            "current_stage": stage,
            "db_stage": row.current_stage,
            "paper_started_at": row.paper_started_at.isoformat() + "Z" if row.paper_started_at else None,
            "closed_trade_count": len(closed),
            "criteria": criteria,
            "criteria_source": authoritative["criteria_source"],
            "controls_live_pre_live_promotion": authoritative["controls_live_pre_live_promotion"],
            "authoritative_criteria": authoritative,
            "human_approval_required": bool(cfg_get(self.config, "promotion.human_approval_required", True)),
            "live_orders_enabled": bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
            "paper_orders_enabled": bool(cfg_get(self.config, "execution.paper_orders_enabled", False)),
            "metrics": row.metrics_json or {},
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        }

    def request_promotion(self, target_stage: str, *, operator_note: str = "") -> dict[str, Any]:
        """Record promotion request — does not auto-apply (human endpoint only)."""
        current = current_promotion_stage(self.config)
        return {
            "status": "pending_human_review",
            "current_stage": current,
            "requested_stage": target_stage.upper(),
            "operator_note": operator_note,
            "message": "Promotion requires human approval and locked config change",
        }
