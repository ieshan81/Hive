"""Consolidate Alpha Factory evidence into useful Hive memories.

Raw activity is not a lesson. This service writes counted, consolidated lessons
for alpha evidence, failures, churn, data quality, broker truth, and autonomous
promotion/quarantine outcomes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AlphaScorecard, LessonNode


MEMORY_TYPE_BY_VERDICT = {
    "paper_candidate": "validated_alpha_candidate",
    "paper_active": "validated_alpha_candidate",
    "paper_quarantined": "autonomous_quarantine_lesson",
    "rejected": "rejected_alpha_candidate",
    "unproven": "alpha_candidate_unproven",
}


class MemoryEvidenceConsolidatorV2:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def consolidate_scorecards(self, *, limit: int = 100) -> dict[str, Any]:
        rows = list(
            self.session.exec(select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc()).limit(limit)).all()
        )
        written = 0
        for sc in rows:
            if self._from_scorecard(sc):
                written += 1
        return {
            "status": "ok",
            "scorecards_seen": len(rows),
            "memory_written_count": written,
            "raw_events_hidden": True,
        }

    def summary(self) -> dict[str, Any]:
        types = set(MEMORY_TYPE_BY_VERDICT.values()) | {
            "alpha_evidence",
            "strategy_failure",
            "churn_pattern",
            "cost_spread_drag",
            "data_quality_issue",
            "paper_outcome_lesson",
            "autonomous_research_lesson",
            "autonomous_promotion_lesson",
        }
        rows = list(
            self.session.exec(
                select(LessonNode).where(LessonNode.memory_type.in_(list(types)), LessonNode.status == "active")
            ).all()
        )
        meaningful = [r for r in rows if r.is_consolidated or r.memory_level in ("consolidated_lesson", "core_ai_lesson")]
        return {
            "status": "ok",
            "meaningful_memory_count": len(meaningful),
            "alpha_memory_count": len(rows),
            "can_influence_ranking_count": sum(1 for r in rows if r.can_influence_ranking),
            "raw_hidden_by_default": True,
            "latest": self._lesson_public(max(rows, key=lambda r: r.updated_at, default=None)),
        }

    def _from_scorecard(self, sc: AlphaScorecard) -> bool:
        mtype = MEMORY_TYPE_BY_VERDICT.get(sc.verdict, "alpha_evidence")
        pattern_key = f"alpha_v2|{sc.normalized_symbol}|{sc.strategy_id}|{sc.verdict}"
        title = self._title(sc)
        summary = sc.promotion_reason or f"{sc.symbol} {sc.strategy_family} verdict: {sc.verdict}."
        evidence = {
            "scorecard_id": sc.id,
            "symbol": sc.symbol,
            "strategy_id": sc.strategy_id,
            "strategy_family": sc.strategy_family,
            "related_backtest_run_id": sc.last_backtest_run_id,
            "related_walk_forward_run_id": sc.last_walk_forward_run_id,
            "evidence_ids": sc.evidence_ids_json or [],
            "sample_size": sc.sample_size,
            "expectancy": sc.expectancy,
            "profit_factor": sc.profit_factor,
            "edge_after_cost_bps": sc.edge_after_cost_bps,
            "blocker_reasons": sc.blocker_reasons_json or [],
        }
        existing = self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pattern_key)).first()
        if existing:
            existing.occurrence_count += 1
            existing.summary = summary
            existing.detailed_lesson = self._detail(sc)
            existing.evidence_json = evidence
            existing.last_seen_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            existing.confidence = self._confidence(sc)
            existing.importance_score = self._importance(sc)
            self.session.add(existing)
            return False
        row = LessonNode(
            category="research_memory",
            memory_type=mtype,
            title=title,
            summary=summary,
            detailed_lesson=self._detail(sc),
            severity="MEDIUM" if sc.verdict in ("paper_candidate", "paper_active") else "LOW",
            confidence=self._confidence(sc),
            source="alpha_factory",
            symbol=sc.symbol,
            strategy_name=sc.strategy_id,
            related_entity_type="alpha_scorecard",
            related_entity_id=str(sc.id),
            evidence_json=evidence,
            proposed_action="paper_candidate_allowed" if sc.verdict in ("paper_candidate", "paper_active") else "do_not_trade",
            action_status="pending" if sc.verdict in ("paper_candidate", "paper_active") else "none",
            visible_in_graph=True,
            visible_to_ai=True,
            can_influence_ranking=sc.verdict in ("paper_candidate", "paper_active", "paper_quarantined"),
            human_review_status="pending",
            system_validation_status="validated" if sc.verdict in ("paper_candidate", "paper_active") else "passed",
            pattern_key=pattern_key,
            tags=["alpha_factory", sc.verdict, sc.strategy_family],
            is_consolidated=True,
            memory_level="consolidated_lesson",
            memory_scope="strategy",
            importance_score=self._importance(sc),
            strength=self._confidence(sc),
        )
        self.session.add(row)
        return True

    @staticmethod
    def _title(sc: AlphaScorecard) -> str:
        if sc.verdict in ("paper_candidate", "paper_active"):
            return f"Alpha candidate: {sc.symbol} {sc.strategy_family}"
        if sc.verdict == "paper_quarantined":
            return f"Quarantined alpha: {sc.symbol}"
        if sc.verdict == "rejected":
            return f"Rejected alpha: {sc.symbol} {sc.strategy_family}"
        return f"Unproven alpha: {sc.symbol} {sc.strategy_family}"

    @staticmethod
    def _detail(sc: AlphaScorecard) -> str:
        blockers = ", ".join(sc.blocker_reasons_json or []) or "none"
        return (
            f"Alpha scorecard {sc.id} for {sc.symbol}/{sc.strategy_id}: verdict={sc.verdict}, "
            f"sample={sc.sample_size}, expectancy={sc.expectancy}, PF={sc.profit_factor}, "
            f"edge_after_cost_bps={sc.edge_after_cost_bps}, blockers={blockers}."
        )

    @staticmethod
    def _confidence(sc: AlphaScorecard) -> float:
        sample = min(1.0, max(0.0, sc.sample_size / 50.0))
        pf = min(1.0, max(0.0, float(sc.profit_factor or 0.0) / 2.0))
        return round(max(0.35, min(0.95, 0.35 + sample * 0.35 + pf * 0.25)), 4)

    @staticmethod
    def _importance(sc: AlphaScorecard) -> float:
        if sc.verdict in ("paper_candidate", "paper_active", "paper_quarantined"):
            return 0.85
        if sc.verdict == "rejected":
            return 0.65
        return 0.45

    @staticmethod
    def _lesson_public(row: LessonNode | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": row.id,
            "memory_type": row.memory_type,
            "title": row.title,
            "summary": row.summary,
            "symbol": row.symbol,
            "strategy_id": row.strategy_name,
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        }
