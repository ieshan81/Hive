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
            if self._from_session_scorecard(sc):
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
            "validated_session_candidate",
            "rejected_session_setup",
            "session_near_miss",
            "session_sample_insufficient",
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

    @staticmethod
    def _stable_pattern_key(sc: AlphaScorecard) -> str:
        timeframe = sc.timeframe or "5Min"
        return f"alpha_scorecard|{sc.strategy_id}|{sc.symbol}|{timeframe}"

    def _archive_conflicting_memories(self, sc: AlphaScorecard, *, canonical_pattern_key: str) -> list[int]:
        """Archive prior verdict-specific or duplicate active memories for this scorecard."""
        superseded: list[int] = []
        now = datetime.utcnow()

        by_entity = list(
            self.session.exec(
                select(LessonNode).where(
                    LessonNode.related_entity_type == "alpha_scorecard",
                    LessonNode.related_entity_id == str(sc.id),
                    LessonNode.status == "active",
                )
            ).all()
        )
        legacy_prefix = f"alpha_v2|{sc.normalized_symbol}|{sc.strategy_id}|"
        legacy_rows = list(
            self.session.exec(
                select(LessonNode).where(
                    LessonNode.pattern_key.like(f"{legacy_prefix}%"),  # type: ignore[attr-defined]
                    LessonNode.status == "active",
                )
            ).all()
        )

        seen_ids: set[int] = set()
        for row in by_entity + legacy_rows:
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            if row.pattern_key == canonical_pattern_key:
                continue
            row.status = "archived"
            row.archive_reason = "verdict_superseded"
            row.visible_to_ai = False
            row.can_influence_ranking = False
            row.updated_at = now
            self.session.add(row)
            superseded.append(row.id)
        return superseded

    def _from_scorecard(self, sc: AlphaScorecard) -> bool:
        mtype = MEMORY_TYPE_BY_VERDICT.get(sc.verdict, "alpha_evidence")
        pattern_key = self._stable_pattern_key(sc)
        title = self._title(sc)
        summary = sc.promotion_reason or f"{sc.symbol} {sc.strategy_family} verdict: {sc.verdict}."
        superseded_ids = self._archive_conflicting_memories(sc, canonical_pattern_key=pattern_key)
        evidence = {
            "scorecard_id": sc.id,
            "symbol": sc.symbol,
            "strategy_id": sc.strategy_id,
            "strategy_family": sc.strategy_family,
            "verdict": sc.verdict,
            "related_backtest_run_id": sc.last_backtest_run_id,
            "related_walk_forward_run_id": sc.last_walk_forward_run_id,
            "evidence_ids": sc.evidence_ids_json or [],
            "sample_size": sc.sample_size,
            "expectancy": sc.expectancy,
            "profit_factor": sc.profit_factor,
            "edge_after_cost_bps": sc.edge_after_cost_bps,
            "blocker_reasons": sc.blocker_reasons_json or [],
            "best_session": sc.best_session,
            "session_sample_size": sc.session_sample_size,
            "session_expectancy": sc.session_expectancy,
            "session_profit_factor": sc.session_profit_factor,
            "session_edge_after_cost_bps": sc.session_edge_after_cost_bps,
            "low_liquidity_session_warning": sc.low_liquidity_session_warning,
        }
        if superseded_ids:
            evidence["superseded_memory_ids"] = superseded_ids

        can_rank = sc.verdict in ("paper_candidate", "paper_active", "paper_quarantined")
        severity = "MEDIUM" if sc.verdict in ("paper_candidate", "paper_active") else "LOW"
        proposed = "paper_candidate_allowed" if sc.verdict in ("paper_candidate", "paper_active") else "do_not_trade"
        action_status = "pending" if sc.verdict in ("paper_candidate", "paper_active") else "none"
        validation = "validated" if sc.verdict in ("paper_candidate", "paper_active") else "passed"

        existing = self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pattern_key)).first()
        if not existing:
            existing = self.session.exec(
                select(LessonNode).where(
                    LessonNode.related_entity_type == "alpha_scorecard",
                    LessonNode.related_entity_id == str(sc.id),
                    LessonNode.status == "active",
                )
            ).first()

        if existing:
            existing.pattern_key = pattern_key
            existing.memory_type = mtype
            existing.title = title
            existing.summary = summary
            existing.detailed_lesson = self._detail(sc)
            existing.evidence_json = evidence
            existing.severity = severity
            existing.confidence = self._confidence(sc)
            existing.importance_score = self._importance(sc)
            existing.proposed_action = proposed
            existing.action_status = action_status
            existing.visible_in_graph = True
            existing.visible_to_ai = can_rank or sc.verdict in ("rejected", "paper_quarantined", "unproven")
            existing.can_influence_ranking = can_rank
            existing.human_review_status = "pending"
            existing.system_validation_status = validation
            existing.symbol = sc.symbol
            existing.strategy_name = sc.strategy_id
            existing.related_entity_type = "alpha_scorecard"
            existing.related_entity_id = str(sc.id)
            existing.tags = ["alpha_factory", sc.verdict, sc.strategy_family]
            existing.is_consolidated = True
            existing.memory_level = "consolidated_lesson"
            existing.occurrence_count += 1
            existing.last_seen_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            self.session.add(existing)
            return False

        row = LessonNode(
            category="research_memory",
            memory_type=mtype,
            title=title,
            summary=summary,
            detailed_lesson=self._detail(sc),
            severity=severity,
            confidence=self._confidence(sc),
            source="alpha_factory",
            symbol=sc.symbol,
            strategy_name=sc.strategy_id,
            related_entity_type="alpha_scorecard",
            related_entity_id=str(sc.id),
            evidence_json=evidence,
            proposed_action=proposed,
            action_status=action_status,
            visible_in_graph=True,
            visible_to_ai=can_rank or sc.verdict in ("rejected", "paper_quarantined", "unproven"),
            can_influence_ranking=can_rank,
            human_review_status="pending",
            system_validation_status=validation,
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

    def _from_session_scorecard(self, sc: AlphaScorecard) -> bool:
        if not sc.best_session:
            return False
        session_metrics = (sc.scorecard_json or {}).get("session_metrics") or {}
        reason = session_metrics.get("session_blocker")
        if not reason:
            if sc.verdict in ("paper_candidate", "paper_active"):
                reason = "validated_session_candidate"
            elif sc.verdict == "rejected":
                reason = "rejected_session_setup"
            else:
                reason = "session_near_miss"
        mtype = {
            "validated_session_candidate": "validated_session_candidate",
            "session_sample_insufficient": "session_sample_insufficient",
            "negative_expectancy": "rejected_session_setup",
            "costs_too_high": "rejected_session_setup",
        }.get(str(reason), "session_near_miss")
        pattern_key = f"alpha_session|{sc.strategy_id}|{sc.symbol}|{sc.best_session}|{reason}"
        title = f"Session evidence: {sc.symbol} {sc.best_session}"
        summary = (
            f"{sc.symbol} {sc.strategy_family} session={sc.best_session}, sample={sc.session_sample_size}, "
            f"edge_after_cost_bps={sc.session_edge_after_cost_bps}, verdict={sc.verdict}."
        )
        evidence = {
            "scorecard_id": sc.id,
            "symbol": sc.symbol,
            "strategy_id": sc.strategy_id,
            "strategy_family": sc.strategy_family,
            "session": sc.best_session,
            "reason": reason,
            "session_sample_size": sc.session_sample_size,
            "session_win_rate": sc.session_win_rate,
            "session_expectancy": sc.session_expectancy,
            "session_profit_factor": sc.session_profit_factor,
            "session_edge_after_cost_bps": sc.session_edge_after_cost_bps,
            "session_next_action": session_metrics.get("session_next_action"),
            "low_liquidity_session_warning": sc.low_liquidity_session_warning,
        }
        can_rank = mtype == "validated_session_candidate" and sc.verdict in ("paper_candidate", "paper_active")
        existing = self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pattern_key)).first()
        if existing:
            existing.memory_type = mtype
            existing.title = title
            existing.summary = summary
            existing.detailed_lesson = summary
            existing.evidence_json = evidence
            existing.visible_in_graph = True
            existing.visible_to_ai = True
            existing.can_influence_ranking = can_rank
            existing.symbol = sc.symbol
            existing.strategy_name = sc.strategy_id
            existing.tags = ["alpha_factory", "session", str(sc.best_session), str(reason)]
            existing.is_consolidated = True
            existing.memory_level = "consolidated_lesson"
            existing.occurrence_count += 1
            existing.last_seen_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            self.session.add(existing)
            return False
        self.session.add(
            LessonNode(
                category="research_memory",
                memory_type=mtype,
                title=title,
                summary=summary,
                detailed_lesson=summary,
                severity="LOW",
                confidence=self._confidence(sc),
                source="alpha_factory",
                symbol=sc.symbol,
                strategy_name=sc.strategy_id,
                related_entity_type="alpha_session_scorecard",
                related_entity_id=str(sc.id),
                evidence_json=evidence,
                proposed_action="paper_candidate_allowed" if can_rank else "research_more",
                action_status="none",
                visible_in_graph=True,
                visible_to_ai=True,
                can_influence_ranking=can_rank,
                human_review_status="pending",
                system_validation_status="passed",
                pattern_key=pattern_key,
                tags=["alpha_factory", "session", str(sc.best_session), str(reason)],
                is_consolidated=True,
                memory_level="consolidated_lesson",
                memory_scope="strategy",
                importance_score=0.8 if can_rank else 0.6,
                strength=self._confidence(sc),
            )
        )
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
            f"edge_after_cost_bps={sc.edge_after_cost_bps}, best_session={sc.best_session}, "
            f"session_edge_after_cost_bps={sc.session_edge_after_cost_bps}, blockers={blockers}."
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
