"""Create Hive lesson memories from research results — no fake metrics."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, ResearchBacktestRun, StrategyCandidate
from app.services.lesson_memory_service import LessonMemoryService
from app.services.memory_categories import CATEGORY_BACKTEST, CATEGORY_RESEARCH, CATEGORY_WALK_FORWARD


class ResearchMemoryService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.lessons = LessonMemoryService(session, config)

    def from_backtest_run(self, run_id: str) -> Optional[LessonNode]:
        row = self.session.exec(
            select(ResearchBacktestRun).where(ResearchBacktestRun.run_id == run_id)
        ).first()
        if not row or row.status not in ("ok", "empty"):
            return None
        metrics = row.metrics_json or {}
        mtype = "backtest_success_pattern" if row.status == "ok" and row.num_trades >= 10 else "backtest_failure_pattern"
        if row.num_trades < int((self.config.get("research") or {}).get("low_sample_trade_threshold", 10)):
            mtype = "backtest_failure_pattern"
            title = f"Insufficient sample: {row.strategy_id}"
            summary = f"Only {row.num_trades} trades — not enough for reliable inference."
        elif (metrics.get("expectancy") or 0) <= 0:
            mtype = "cost_drag_pattern" if (metrics.get("profit_factor") or 0) > 1 else "backtest_failure_pattern"
            title = f"After-cost underperformance: {row.strategy_id}"
            summary = f"Expectancy {metrics.get('expectancy')} with {row.num_trades} trades on {row.symbols}."
        else:
            title = f"Backtest edge found: {row.strategy_id}"
            summary = (
                f"Expectancy {metrics.get('expectancy'):.4f}, PF {metrics.get('profit_factor')}, "
                f"{row.num_trades} trades."
            )

        evidence = {
            "strategy_id": row.strategy_id,
            "parameter_set_id": row.parameter_set_id,
            "run_id": row.run_id,
            "symbols": row.symbols,
            "date_start": row.date_start,
            "date_end": row.date_end,
            "metrics": metrics,
            "sample_size": row.num_trades,
            "confidence": row.confidence_label,
            "estimated_spread": row.estimated_spread,
            "recommended_action": "walk_forward_validation" if mtype == "backtest_success_pattern" else "revise_parameters",
        }
        return self.lessons.upsert_lesson(
            memory_type=mtype,
            title=title,
            summary=summary,
            detailed_lesson=summary + " Cost model uses tiered spread assumptions on OHLCV bars.",
            category=CATEGORY_BACKTEST,
            severity="MEDIUM" if row.num_trades >= 10 else "LOW",
            confidence=0.75 if row.num_trades >= 20 else 0.5,
            source="research_lab",
            strategy_name=row.strategy_id,
            symbol=row.symbols[0] if row.symbols else None,
            related_entity_type="research_backtest_run",
            related_entity_id=row.run_id,
            evidence=evidence,
            aggregate=True,
            pattern_key=f"bt|{row.strategy_id}|{row.parameter_set_id}",
        )

    def from_walk_forward(self, run_id: str, wf_summary: dict) -> Optional[LessonNode]:
        if wf_summary.get("status") == "error":
            return self.lessons.upsert_lesson(
                memory_type="walk_forward_failure",
                title="Walk-forward unavailable",
                summary=wf_summary.get("message", "Insufficient data"),
                detailed_lesson=wf_summary.get("message", ""),
                category=CATEGORY_WALK_FORWARD,
                severity="LOW",
                source="research_lab",
                evidence={"run_id": run_id, **wf_summary},
            )
        oos = wf_summary.get("out_of_sample_positive", 0)
        total = wf_summary.get("windows_count", 0)
        mtype = "walk_forward_success" if oos >= total / 2 and total >= 2 else "walk_forward_failure"
        return self.lessons.upsert_lesson(
            memory_type=mtype,
            title=f"Walk-forward {wf_summary.get('strategy_id', 'strategy')}",
            summary=f"{oos}/{total} OOS windows positive.",
            detailed_lesson=f"Walk-forward run {run_id}: {oos} of {total} test windows showed positive expectancy.",
            category=CATEGORY_WALK_FORWARD,
            source="research_lab",
            strategy_name=wf_summary.get("strategy_id"),
            evidence={"run_id": run_id, **wf_summary},
            related_entity_type="walk_forward",
            related_entity_id=run_id,
        )

    def from_rejection(self, strategy_id: str, reason: str, evidence: dict) -> LessonNode:
        return self.lessons.upsert_lesson(
            memory_type="rejected_strategy_memory",
            title=f"Rejected: {strategy_id}",
            summary=reason[:200],
            detailed_lesson=reason,
            category=CATEGORY_RESEARCH,
            severity="MEDIUM",
            source="research_lab",
            strategy_name=strategy_id,
            evidence=evidence,
            action_status="rejected",
            visible_to_ai=True,
            can_influence_ranking=False,
        )

    def from_promotion_candidate(self, candidate: StrategyCandidate) -> LessonNode:
        return self.lessons.upsert_lesson(
            memory_type="promoted_strategy_candidate",
            title=f"Paper candidate: {candidate.strategy_id}",
            summary="Requires human approval before paper_enabled.",
            detailed_lesson="Strategy passed research gates; awaiting operator approval.",
            category=CATEGORY_RESEARCH,
            severity="MEDIUM",
            source="research_lab",
            strategy_name=candidate.strategy_id,
            evidence=candidate.evidence_json or {},
            action_status="pending_human_review",
            can_influence_ranking=False,
        )

    def list_research_memories(self, limit: int = 50) -> list[dict]:
        from app.services.memory_categories import RESEARCH_MEMORY_TYPES

        rows = self.session.exec(
            select(LessonNode)
            .where(LessonNode.memory_type.in_(list(RESEARCH_MEMORY_TYPES)))
            .order_by(LessonNode.created_at.desc())
            .limit(limit)
        ).all()
        return [self.lessons._lesson_detail(r) for r in rows]
