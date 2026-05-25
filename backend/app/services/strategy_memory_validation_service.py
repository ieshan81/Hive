"""Validate strategy-linked memories — pending cannot influence ranking."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import LessonNode, StrategyMemoryLink, StrategyRegistry
from app.services.memory_categories import RESEARCH_MEMORY_TYPES


class StrategyMemoryValidationService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.rcfg = config.get("research") or {}

    def validate_all_pending(self) -> dict[str, Any]:
        links = list(
            self.session.exec(
                select(StrategyMemoryLink).where(StrategyMemoryLink.memory_status == "pending")
            ).all()
        )
        validated = rejected = 0
        for link in links:
            lesson = self.session.get(LessonNode, link.memory_id)
            if not lesson:
                continue
            ok, rule, evidence = self._evaluate(link.strategy_id, lesson)
            if ok:
                link.memory_status = "validated"
                link.can_influence_ranking = lesson.memory_type not in (
                    "rejected_strategy_memory",
                    "do_not_promote_recommendation",
                    "sample_size_warning",
                )
                link.validator_rule = rule
                link.validation_evidence_json = evidence
                link.validated_at = datetime.utcnow()
                lesson.system_validation_status = "validated"
                lesson.system_validated_at = link.validated_at
                lesson.system_validator_rule = rule
                lesson.can_influence_ranking = link.can_influence_ranking
                validated += 1
            else:
                link.memory_status = "rejected"
                link.can_influence_ranking = False
                link.validator_rule = rule
                link.validation_evidence_json = evidence
                lesson.system_validation_status = "rejected"
                lesson.system_validated_at = datetime.utcnow()
                lesson.system_validator_rule = rule
                lesson.can_influence_ranking = False
                rejected += 1
            self.session.add(link)
            self.session.add(lesson)
        self._refresh_registry_counts()
        return {"status": "ok", "validated": validated, "rejected": rejected, "scanned": len(links)}

    def link_research_memories(self, strategy_id: str) -> int:
        lessons = list(
            self.session.exec(
                select(LessonNode)
                .where(
                    LessonNode.strategy_name == strategy_id,
                    LessonNode.memory_type.in_(list(RESEARCH_MEMORY_TYPES)),
                )
            ).all()
        )
        created = 0
        for lesson in lessons:
            exists = self.session.exec(
                select(StrategyMemoryLink).where(
                    StrategyMemoryLink.strategy_id == strategy_id,
                    StrategyMemoryLink.memory_id == lesson.id,
                )
            ).first()
            if exists:
                continue
            self.session.add(
                StrategyMemoryLink(
                    strategy_id=strategy_id,
                    memory_id=lesson.id,
                    memory_type=lesson.memory_type or "unknown",
                    memory_status="pending",
                    visible_to_ai=True,
                    can_influence_ranking=False,
                )
            )
            lesson.can_influence_ranking = False
            self.session.add(lesson)
            created += 1
        self._refresh_registry_counts(strategy_id)
        return created

    def _evaluate(self, strategy_id: str, lesson: LessonNode) -> tuple[bool, str, dict]:
        mtype = lesson.memory_type or ""
        evidence = lesson.evidence_json or {}
        low_n = int(self.rcfg.get("low_sample_trade_threshold", 10))

        if mtype == "backtest_failure_pattern":
            runs = evidence.get("metrics") or evidence
            severe = (runs.get("max_drawdown") or 0) >= 0.5 if isinstance(runs, dict) else False
            return True, "failure_pattern", {"severe": severe}

        if mtype == "spread_kills_edge_pattern":
            return True, "cost_drag", {"record": True}

        if mtype == "rejected_strategy_memory":
            return True, "record_only", {"ranking": False}

        if mtype == "do_not_promote_recommendation":
            linked = evidence.get("promote_allowed") is False or evidence.get("evaluation")
            return bool(linked), "do_not_promote", evidence

        if mtype == "sample_size_warning":
            n = evidence.get("num_trades") or evidence.get("sample_size") or 0
            return int(n) < low_n, "sample_size", {"trades": n}

        if mtype == "walk_forward_success":
            total = evidence.get("windows_count", 0)
            return int(total) >= 2, "walk_forward", evidence

        if mtype == "walk_forward_failure":
            return True, "walk_forward_fail", evidence

        if mtype == "parameter_sweep_no_variation":
            return True, "sweep_no_variation", evidence

        if mtype == "repeated_losing_parameter_family":
            return True, "losing_family", evidence

        if mtype in RESEARCH_MEMORY_TYPES:
            return True, "generic_research", {"type": mtype}
        return False, "unknown_type", {}

    def _refresh_registry_counts(self, strategy_id: str | None = None) -> None:
        q = select(StrategyRegistry)
        if strategy_id:
            q = q.where(StrategyRegistry.strategy_id == strategy_id)
        for reg in self.session.exec(q).all():
            links = list(
                self.session.exec(
                    select(StrategyMemoryLink).where(StrategyMemoryLink.strategy_id == reg.strategy_id)
                ).all()
            )
            reg.memory_count = len(links)
            reg.validated_memory_count = sum(1 for l in links if l.memory_status == "validated")
            reg.pending_memory_count = sum(1 for l in links if l.memory_status == "pending")
            self.session.add(reg)
