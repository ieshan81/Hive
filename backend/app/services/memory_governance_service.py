"""Memory governance: typed taxonomy + evidence gating + archive/reset.

Central safety rule: **no memory may directly trade or mutate risk/live settings.** Memory is
advisory (ranking only) and may influence trading scoring ONLY when it is evidence-linked
(closed trade / validated strategy / backtest). Hypotheses can never influence trading without a
linked backtest.

This service is read/write DB cleanup + classification only — it never submits an order, never
enables live, never deletes evidence-linked memory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode

# 7-class taxonomy (self_correction_brain_audit.md).
RAW_EVENT = "raw_event"
CLOSED_TRADE = "closed_trade"
BACKTEST = "backtest"
RISK = "risk"
REGIME = "regime"
HYPOTHESIS = "hypothesis"
VALIDATED = "validated_strategy"

# Evidence keys that tie a learning memory to real, non-AI proof.
EVIDENCE_KEYS = ("trade_id", "order_id", "outcome_id", "scorecard_id", "backtest_id",
                 "backtest_run_id", "verifier_id", "diagnostic_bundle_id", "related_backtest_run_id")

# Only these classes may influence trading scoring — and only when evidence-linked.
TRADING_INFLUENCE_CLASSES = frozenset({CLOSED_TRADE, VALIDATED, BACKTEST})


class MemoryGovernanceService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    @staticmethod
    def classify(lesson: LessonNode) -> str:
        mt = (lesson.memory_type or "").lower()
        ret = (lesson.related_entity_type or "").lower()
        if "hypothesis" in mt:
            return HYPOTHESIS
        if "backtest" in mt or ret in ("backtest", "research_backtest_run"):
            return BACKTEST
        if "validated" in mt:
            return VALIDATED
        if "outcome" in mt or "closed" in mt or ret in ("trade", "order", "outcome"):
            return CLOSED_TRADE
        if any(k in mt for k in ("cost", "spread", "drag", "churn", "stale", "rejected", "risk")):
            return RISK
        if any(k in mt for k in ("regime", "session", "volatility", "correlation", "liquidity")):
            return REGIME
        return RAW_EVENT

    @classmethod
    def is_evidence_linked(cls, lesson: LessonNode) -> bool:
        if lesson.related_entity_type and lesson.related_entity_id:
            return True
        ev = lesson.evidence_json or {}
        if isinstance(ev, dict):
            if any(ev.get(k) for k in EVIDENCE_KEYS):
                return True
            if isinstance(ev.get("evidence_ids"), list) and ev["evidence_ids"]:
                return True
        return False

    @classmethod
    def has_backtest_link(cls, lesson: LessonNode) -> bool:
        ev = lesson.evidence_json or {}
        if isinstance(ev, dict) and any(ev.get(k) for k in ("backtest_id", "backtest_run_id", "related_backtest_run_id")):
            return True
        return (lesson.related_entity_type or "") in ("backtest", "research_backtest_run", "alpha_scorecard")

    @classmethod
    def can_influence_trading(cls, lesson: LessonNode) -> bool:
        """The single gate: a memory may influence trading scoring ONLY if it is an evidence-linked
        trading class. A hypothesis NEVER influences trading without a linked backtest. Raw/regime/
        risk memories never directly drive a trade (advisory confidence only, not order triggers)."""
        klass = cls.classify(lesson)
        if klass == HYPOTHESIS:
            return False  # hypotheses cannot trade — must be backtested first
        if klass not in TRADING_INFLUENCE_CLASSES:
            return False
        return cls.is_evidence_linked(lesson)

    def archive_noisy_active_memory(self, *, dry_run: bool = False, operator: str = "memory_reset") -> dict[str, Any]:
        """Archive ACTIVE lessons that are not evidence-linked (noise), preserving every
        evidence-linked lesson. Never hard-deletes. Returns an export summary."""
        active = list(self.session.exec(select(LessonNode).where(LessonNode.status == "active")).all())
        export = {"total_active": len(active), "by_type": {}, "evidence_linked": 0, "noisy": 0}
        to_archive: list[LessonNode] = []
        for lz in active:
            export["by_type"][lz.memory_type] = export["by_type"].get(lz.memory_type, 0) + 1
            if self.is_evidence_linked(lz):
                export["evidence_linked"] += 1
            else:
                export["noisy"] += 1
                to_archive.append(lz)
        if not dry_run:
            now = datetime.utcnow()
            for lz in to_archive:
                lz.status = "archived"
                lz.visible_to_ai = False
                lz.can_influence_ranking = False
                if hasattr(lz, "archive_reason"):
                    lz.archive_reason = "noisy_unlinked_memory_reset"
                lz.updated_at = now
                self.session.add(lz)
            self.session.flush()
        return {
            "status": "ok",
            "dry_run": dry_run,
            "archived": 0 if dry_run else len(to_archive),
            "would_archive": len(to_archive) if dry_run else 0,
            "evidence_linked_preserved": export["evidence_linked"],
            "export_summary": export,
            "orders_created": 0,
        }
