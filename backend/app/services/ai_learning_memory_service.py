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
    OUTCOME_SOURCE_MEMORY_TYPES,
    RESEARCH_MEMORY_TYPES,
    TRAINING_MEMORY_TYPES,
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
        created += self._from_outcome_memories()
        self.session.flush()
        return {"status": "ok", "created": created, "total_ai": len(self.list_ai_learning(100))}

    def learning_directives(self, limit: int = 8) -> dict[str, list[str]]:
        """AI Fund Manager payload: learned / avoid / test next."""
        learned: list[str] = []
        avoid: list[str] = []
        test_next: list[str] = []
        rows = self.list_ai_learning(limit * 3)
        for row in rows:
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")[:200]
            line = f"{title}: {summary}" if summary else title
            mt = row.get("memory_type") or ""
            if mt in ("stale_position_memory",) or "reject" in title.lower() or "block" in title.lower():
                avoid.append(line)
            elif mt in TRAINING_MEMORY_TYPES or "test" in title.lower() or "experiment" in title.lower():
                test_next.append(line)
            else:
                learned.append(line)
        from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop
        from app.services.fast_training_exit_only_service import FastTrainingExitOnlyService
        from app.services.open_position_review_service import OpenPositionReviewService

        ft = FastCryptoTrainingLoop(self.session, self.config).status()
        exit_only = FastTrainingExitOnlyService(self.session, self.config).status()
        reviews = OpenPositionReviewService(self.session, self.config).review_all()
        concerns = [
            f"{r.get('display_symbol')}: {r.get('action')} ({r.get('reason')}) hold={r.get('true_hold_minutes')}m"
            for r in reviews.get("reviews", [])
        ]
        return {
            "what_i_learned": learned[:limit],
            "what_i_will_avoid": avoid[:limit],
            "what_i_will_test_next": test_next[:limit],
            "what_changed_because_of_memory": learned[:3],
            "current_training_posture": {
                "mode_enabled": ft.get("mode_enabled"),
                "fast_training_loop_enabled": ft.get("fast_training_loop_enabled"),
                "exit_only_enabled": exit_only.get("exit_only_enabled"),
                "can_submit_orders": ft.get("can_submit_orders"),
                "blockers": ft.get("blockers", []),
            },
            "current_open_position_concern": concerns[:limit],
        }

    def _from_outcome_memories(self) -> int:
        n = 0
        for src in self.session.exec(
            select(LessonNode).where(
                LessonNode.status == "active",
                LessonNode.memory_type.in_(list(OUTCOME_SOURCE_MEMORY_TYPES)),
            ).limit(40)
        ).all():
            pk = f"core_ai|outcome|{src.memory_type}|{src.id}"
            if self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pk)).first():
                continue
            title = f"Core lesson: {src.title[:60]}"
            avoid = src.memory_type in (
                "stale_position_memory",
                "training_blocked_memory",
                "fast_training_blocked_memory",
                "meme_spike_block_memory",
            )
            row = self.lessons.upsert_lesson(
                memory_type="core_ai_lesson",
                title=title,
                summary=src.summary[:500],
                detailed_lesson=src.detailed_lesson[:900] if src.detailed_lesson else src.summary[:900],
                strategy_name=src.strategy_name,
                symbol=src.symbol,
                source="ai_learning_outcome",
                pattern_key=pk,
                category=CATEGORY_AI_LEARNING,
                can_influence_ranking=False,
                visible_to_ai=True,
                visible_in_graph=True,
            )
            row.memory_level = MEMORY_LEVEL_CORE
            row.importance_score = 0.88 if avoid else 0.72
            row.source_memory_ids_json = [src.id]
            row.evidence_json = {"source_memory_id": src.id, "source_memory_type": src.memory_type}
            row.system_validation_status = "validated"
            row.system_validator_rule = "outcome_to_core_ai_lesson"
            self.session.add(row)
            self._link_core_to_source(row, src)
            n += 1
        return n

    def _link_core_to_source(self, core: LessonNode, source: LessonNode) -> None:
        from app.database import MemoryEdge

        self.session.add(
            MemoryEdge(
                source_id=f"lesson-{source.id}",
                target_id=f"lesson-{core.id}",
                relation="converted_into_core_lesson",
                weight=0.85,
                evidence_count=source.occurrence_count,
                lesson_id=core.id,
            )
        )

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
