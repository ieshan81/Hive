"""Generate core AI learning memories from research, training, and rejections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import LessonNode, StrategyMemoryLink, StrategyRegistry, StrategyRejection
from app.services.lesson_memory_service import LessonMemoryService
from app.services.memory_categories import (
    CATEGORY_AI_LEARNING,
    MEMORY_LEVEL_CORE,
    MEMORY_LEVEL_CONSOLIDATED,
    RESEARCH_MEMORY_TYPES,
)


CORE_LESSON_TEMPLATES = [
    (
        "crypto_push_pull_momentum",
        "rejected",
        "Crypto push-pull momentum rejected",
        "Repeated research shows negative expectancy and cost sensitivity. Do not promote until fresh data improves evidence.",
    ),
    (
        None,
        "cost",
        "Cost and spread kill weak crypto edge",
        "When round-trip cost exceeds expected edge, strategies fail in paper even with positive raw signals.",
    ),
    (
        None,
        "promotion",
        "Promotion requires evidence not AI opinion",
        "Deterministic validation gate owns lifecycle. AI memories are advisory only.",
    ),
    (
        None,
        "meme_discipline",
        "Meme push-pull needs fast exit discipline",
        "Quick push-pull positions must not become passive bags. Time-stop and spread exits are mandatory.",
    ),
]


class AILearningMemoryService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.lessons = LessonMemoryService(session, config)

    def list_ai_learning(self, limit: int = 40) -> list[dict]:
        rows = self.session.exec(
            select(LessonNode)
            .where(
                LessonNode.memory_level.in_(("core_ai_lesson", "consolidated_lesson")),
                LessonNode.category == CATEGORY_AI_LEARNING,
                LessonNode.status == "active",
            )
            .order_by(LessonNode.importance_score.desc())
            .limit(limit)
        ).all()
        return [self.lessons._lesson_detail(r) for r in rows]

    def generate(self, *, force: bool = False) -> dict[str, Any]:
        created = 0
        for strategy_id, stage_hint, title, lesson in CORE_LESSON_TEMPLATES:
            if strategy_id:
                reg = self.session.exec(
                    select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
                ).first()
                if not reg and not force:
                    continue
            pk = f"core_ai|{strategy_id or stage_hint}|{title[:30]}"
            exists = self.session.exec(
                select(LessonNode).where(LessonNode.pattern_key == pk, LessonNode.status == "active")
            ).first()
            if exists and not force:
                continue
            row = self.lessons.upsert_lesson(
                memory_type="core_ai_lesson",
                title=title,
                summary=lesson,
                detailed_lesson=lesson,
                strategy_name=strategy_id,
                source="ai_learning_generator",
                pattern_key=pk,
                category=CATEGORY_AI_LEARNING,
                can_influence_ranking=False,
                visible_to_ai=True,
            )
            row.memory_level = MEMORY_LEVEL_CORE
            row.importance_score = 0.85
            row.strength = 0.9
            row.system_validation_status = "validated"
            row.system_validator_rule = "ai_learning_from_research_gate"
            row.last_confirmed_at = datetime.utcnow()
            self.session.add(row)
            created += 1

        created += self._from_rejected_strategies()
        created += self._from_consolidated()
        created += self._from_research_links()
        self.session.flush()
        return {"status": "ok", "created": created, "total_ai": len(self.list_ai_learning(100))}

    def _from_rejected_strategies(self) -> int:
        n = 0
        for reg in self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.current_stage == "rejected")
        ).all():
            rej = self.session.exec(
                select(StrategyRejection).where(StrategyRejection.strategy_id == reg.strategy_id)
            ).first()
            rationale = rej.rationale if rej else "Research gate rejected"
            pk = f"core_ai|rejected|{reg.strategy_id}"
            if self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pk)).first():
                continue
            row = self.lessons.upsert_lesson(
                memory_type="ai_learning_lesson",
                title=f"{reg.name[:40]} rejected",
                summary=rationale[:400],
                detailed_lesson=rationale[:800],
                strategy_name=reg.strategy_id,
                source="ai_learning_rejection",
                pattern_key=pk,
                category=CATEGORY_AI_LEARNING,
            )
            row.memory_level = MEMORY_LEVEL_CORE
            row.importance_score = 0.75
            self.session.add(row)
            n += 1
        return n

    def _from_consolidated(self) -> int:
        n = 0
        for c in self.session.exec(
            select(LessonNode).where(
                LessonNode.memory_type == "consolidated_learning",
                LessonNode.status == "active",
            ).limit(20)
        ).all():
            pk = f"core_ai|from_consolidated|{c.id}"
            if self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pk)).first():
                continue
            row = self.lessons.upsert_lesson(
                memory_type="core_ai_lesson",
                title=f"Core: {c.title[:50]}",
                summary=c.summary[:400],
                detailed_lesson=c.detailed_lesson[:800],
                strategy_name=c.strategy_name,
                symbol=c.symbol,
                source="ai_learning_consolidated",
                pattern_key=pk,
                category=CATEGORY_AI_LEARNING,
            )
            row.memory_level = MEMORY_LEVEL_CORE
            row.source_memory_ids_json = c.source_memory_ids_json or [c.id]
            row.importance_score = max(c.importance_score, 0.7)
            self.session.add(row)
            n += 1
        return n

    def _from_research_links(self) -> int:
        n = 0
        links = list(
            self.session.exec(
                select(StrategyMemoryLink).where(StrategyMemoryLink.memory_status == "validated").limit(30)
            ).all()
        )
        by_strategy: dict[str, int] = {}
        for link in links:
            if link.memory_type not in RESEARCH_MEMORY_TYPES:
                continue
            by_strategy[link.strategy_id] = by_strategy.get(link.strategy_id, 0) + 1
        for sid, count in by_strategy.items():
            if count < 5:
                continue
            pk = f"core_ai|research_pattern|{sid}"
            if self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pk)).first():
                continue
            row = self.lessons.upsert_lesson(
                memory_type="ai_learning_lesson",
                title=f"Research pattern: {sid}",
                summary=f"{count} validated research memories indicate repeated backtest behavior for {sid}.",
                detailed_lesson="Use consolidated evidence before promotion. AI does not override gate.",
                strategy_name=sid,
                source="ai_learning_research_links",
                pattern_key=pk,
                category=CATEGORY_AI_LEARNING,
            )
            row.memory_level = MEMORY_LEVEL_CONSOLIDATED
            row.importance_score = 0.65
            self.session.add(row)
            n += 1
        return n
