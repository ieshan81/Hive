"""Create Hive lesson memories from research results — no fake metrics."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, ResearchBacktestRun, StrategyCandidate
from app.services.lesson_memory_service import LessonMemoryService
from app.services.memory_categories import (
    CATEGORY_BACKTEST,
    CATEGORY_RESEARCH,
    CATEGORY_WALK_FORWARD,
    RESEARCH_MEMORY_TYPES,
)
from app.services.research_performance import evaluate_metrics


class ResearchMemoryService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.lessons = LessonMemoryService(session, config)
        self.rcfg = config.get("research") or {}

    def create_typed(
        self,
        memory_type: str,
        *,
        title: str,
        summary: str,
        strategy_id: Optional[str] = None,
        evidence: Optional[dict] = None,
        action_status: Optional[str] = None,
        pattern_key: Optional[str] = None,
        aggregate: bool = False,
    ) -> LessonNode:
        cat = CATEGORY_BACKTEST
        if memory_type.startswith("walk_forward"):
            cat = CATEGORY_WALK_FORWARD
        elif memory_type in (
            "rejected_strategy_memory",
            "promoted_strategy_candidate",
            "do_not_promote_recommendation",
            "parameter_sweep_no_variation",
            "sample_size_warning",
            "repeated_losing_parameter_family",
            "strategy_discovery_verdict",
        ):
            cat = CATEGORY_RESEARCH
        return self.lessons.upsert_lesson(
            memory_type=memory_type,
            title=title,
            summary=summary,
            detailed_lesson=summary,
            category=cat,
            severity="MEDIUM",
            confidence=0.6,
            source="research_lab",
            strategy_name=strategy_id,
            evidence=evidence or {},
            action_status=action_status,
            visible_to_ai=True,
            can_influence_ranking=memory_type not in ("rejected_strategy_memory", "do_not_promote_recommendation"),
            aggregate=aggregate,
            pattern_key=pattern_key or f"{memory_type}|{strategy_id}|{title[:40]}",
        )

    def from_backtest_run(self, run_id: str) -> int:
        """Create one or more research memories from a backtest run. Returns count created."""
        row = self.session.exec(
            select(ResearchBacktestRun).where(ResearchBacktestRun.run_id == run_id)
        ).first()
        if not row:
            return 0

        created = 0
        metrics = row.metrics_json or {}
        eval_res = evaluate_metrics(metrics, self.config)

        if row.status == "empty" or row.num_trades == 0:
            self.create_typed(
                "backtest_failure_pattern",
                title=f"No trades: {row.strategy_id}",
                summary=((row.warnings or ["No trades triggered"])[0])[:200],
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id, "status": row.status},
                pattern_key=f"empty|{run_id}",
            )
            return 1

        if row.status not in ("ok", "empty"):
            return 0

        low_sample = row.num_trades < int(self.rcfg.get("low_sample_trade_threshold", 10))
        exp = metrics.get("expectancy")
        pf = metrics.get("profit_factor")
        mdd = (metrics.get("max_drawdown") or 0) * 100

        if low_sample:
            self.create_typed(
                "sample_size_warning",
                title=f"Insufficient sample: {row.strategy_id}",
                summary=f"Only {row.num_trades} trades — not enough for reliable inference.",
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id, "num_trades": row.num_trades},
                pattern_key=f"sample|{run_id}",
            )
            created += 1

        if exp is not None and float(exp) < 0:
            self.create_typed(
                "backtest_failure_pattern",
                title=f"Negative expectancy: {row.strategy_id}",
                summary=f"Expectancy {float(exp):.5f} after costs ({row.num_trades} trades).",
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id, "metrics": metrics},
                pattern_key=f"neg_exp|{run_id}",
            )
            created += 1

        if pf is not None and float(pf) < 1.0:
            self.create_typed(
                "spread_kills_edge_pattern",
                title=f"Poor profit factor: {row.strategy_id}",
                summary=f"Profit factor {float(pf):.3f} — edge lost after spread/fees/slippage.",
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id, "metrics": metrics},
                pattern_key=f"pf_low|{run_id}",
            )
            created += 1

        if mdd and float(mdd) >= 50:
            self.create_typed(
                "backtest_failure_pattern",
                title=f"High max drawdown: {row.strategy_id}",
                summary=f"Max drawdown ~{float(mdd):.1f}% after costs.",
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id, "metrics": metrics},
                pattern_key=f"mdd|{run_id}",
            )
            created += 1

        if eval_res["reject"]:
            reason = eval_res.get("rejection_reason") or "weak performance"
            self.create_typed(
                "rejected_strategy_memory",
                title=f"{row.strategy_id} rejected: {reason}",
                summary=(
                    f"{row.strategy_id} parameter set {row.parameter_set_id}: "
                    f"expectancy {exp}, PF {pf}, {row.num_trades} trades."
                ),
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id, "evaluation": eval_res, "metrics": metrics},
                action_status="rejected",
                pattern_key=f"reject|{run_id}",
            )
            created += 1
            if not eval_res["promote_allowed"]:
                self.create_typed(
                    "do_not_promote_recommendation",
                    title=f"Do not promote {row.strategy_id}",
                    summary=reason,
                    strategy_id=row.strategy_id,
                    evidence={"run_id": run_id, "promote_allowed": False},
                    pattern_key=f"dnm|{run_id}",
                )
                created += 1
        elif row.status == "ok" and not low_sample:
            self.create_typed(
                "backtest_success_pattern",
                title=f"Backtest edge found: {row.strategy_id}",
                summary=(
                    f"Expectancy {float(exp or 0):.4f}, PF {pf}, {row.num_trades} trades on {row.symbols}."
                ),
                strategy_id=row.strategy_id,
                evidence={
                    "run_id": run_id,
                    "metrics": metrics,
                    "recommended_action": "walk_forward_validation",
                },
                pattern_key=f"ok|{run_id}",
            )
            created += 1

        if created == 0:
            self.create_typed(
                "backtest_failure_pattern",
                title=f"Backtest note: {row.strategy_id}",
                summary=f"Run {row.status} with {row.num_trades} trades.",
                strategy_id=row.strategy_id,
                evidence={"run_id": run_id},
                pattern_key=f"bt|{run_id}",
            )
            created = 1
        return created

    def from_walk_forward(self, run_id: str, wf_summary: dict) -> Optional[LessonNode]:
        if wf_summary.get("status") == "error":
            msg = wf_summary.get("message", "Insufficient data")
            if "insufficient" in msg.lower() or "not enough" in msg.lower():
                return self.create_typed(
                    "insufficient_walk_forward_data",
                    title="Walk-forward insufficient data",
                    summary=msg,
                    strategy_id=wf_summary.get("strategy_id"),
                    evidence={"run_id": run_id, **wf_summary},
                )
            return self.create_typed(
                "walk_forward_failure",
                title="Walk-forward unavailable",
                summary=msg,
                strategy_id=wf_summary.get("strategy_id"),
                evidence={"run_id": run_id, **wf_summary},
            )
        oos = wf_summary.get("out_of_sample_positive", 0)
        total = wf_summary.get("windows_count", 0)
        if total < 2:
            return self.create_typed(
                "insufficient_walk_forward_data",
                title=f"Walk-forward insufficient windows: {wf_summary.get('strategy_id', 'strategy')}",
                summary=f"Only {total} windows — need more historical bars.",
                strategy_id=wf_summary.get("strategy_id"),
                evidence={"run_id": run_id, **wf_summary},
            )
        mtype = "walk_forward_success" if oos >= total / 2 else "walk_forward_failure"
        return self.create_typed(
            mtype,
            title=f"Walk-forward {wf_summary.get('strategy_id', 'strategy')}",
            summary=f"{oos}/{total} OOS windows positive.",
            strategy_id=wf_summary.get("strategy_id"),
            evidence={"run_id": run_id, **wf_summary},
        )

    def from_rejection(self, strategy_id: str, reason: str, evidence: dict) -> LessonNode:
        return self.create_typed(
            "rejected_strategy_memory",
            title=f"Rejected: {strategy_id}",
            summary=reason[:200],
            strategy_id=strategy_id,
            evidence=evidence,
            action_status="rejected",
        )

    def from_promotion_candidate(self, candidate: StrategyCandidate) -> LessonNode:
        return self.create_typed(
            "promoted_strategy_candidate",
            title=f"Paper candidate: {candidate.strategy_id}",
            summary="Requires human approval before paper_enabled.",
            strategy_id=candidate.strategy_id,
            evidence=candidate.evidence_json or {},
            action_status="pending_human_review",
        )

    def list_research_memories(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(
            select(LessonNode)
            .where(LessonNode.memory_type.in_(list(RESEARCH_MEMORY_TYPES)))
            .order_by(LessonNode.created_at.desc())
            .limit(limit)
        ).all()
        return [self.lessons._lesson_detail(r) for r in rows]
