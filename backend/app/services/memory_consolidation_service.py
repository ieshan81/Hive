"""Consolidate raw memories into stronger lessons — archive duplicates, keep evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, MemoryEdge, SystemValidationAudit
from app.services.lesson_memory_service import LessonMemoryService
from app.services.memory_categories import (
    CATEGORY_AI_LEARNING,
    CATEGORY_RESEARCH,
    MEMORY_LEVEL_CONSOLIDATED,
    MEMORY_LEVEL_RAW,
    OUTCOME_SOURCE_MEMORY_TYPES,
    RESEARCH_MEMORY_TYPES,
)
from app.services.memory_policy import ensure_memory_policy_row, load_memory_policy


PROTECTED_MEMORY_TYPES = frozenset(
    {
        "reconciliation_bug",
        "broker_behavior",
        "paper_trade_filled",
        "risk_lesson",
        "open_position_monitor",
    }
)


class MemoryConsolidationService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.policy = ensure_memory_policy_row(session, config)
        self.lessons = LessonMemoryService(session, config)

    def status(self) -> dict[str, Any]:
        raw = self._raw_active()
        consolidated = list(
            self.session.exec(
                select(LessonNode).where(
                    LessonNode.memory_level.in_(("consolidated_lesson", "core_ai_lesson")),
                    LessonNode.status == "active",
                )
            ).all()
        )
        archived = len(
            list(
                self.session.exec(
                    select(LessonNode).where(
                        LessonNode.status == "archived",
                        LessonNode.archive_reason == "consolidated_duplicate",
                    )
                ).all()
            )
        )
        total = len(raw) + len(consolidated)
        ratio = round(len(consolidated) / max(total, 1), 3)
        return {
            "status": "ok",
            "total_raw_memories": len(raw),
            "consolidated_memories": len(consolidated),
            "archived_raw_memories": archived,
            "compression_ratio": ratio,
            "policy": self.policy,
            "should_consolidate": self._should_run(),
        }

    def _raw_active(self) -> list[LessonNode]:
        return list(
            self.session.exec(
                select(LessonNode).where(
                    LessonNode.status == "active",
                    LessonNode.memory_level == MEMORY_LEVEL_RAW,
                    LessonNode.is_consolidated == False,  # noqa: E712
                )
            ).all()
        )

    def _should_run(self) -> bool:
        raw = self._raw_active()
        if len(raw) >= int(self.policy.get("consolidation_threshold_total_raw_memories", 100)):
            return True
        by_strategy: dict[str, int] = defaultdict(int)
        for r in raw:
            by_strategy[r.strategy_name or "unknown"] += 1
        thresh = int(self.policy.get("consolidation_threshold_per_strategy", 25))
        return any(c >= thresh for c in by_strategy.values())

    def run(self, *, force: bool = False) -> dict[str, Any]:
        if not force and not self._should_run():
            return {"status": "skipped", "message": "Consolidation thresholds not met", **self.status()}
        raw = self._raw_active()
        groups = self._group_raw(raw)
        created = archived = 0
        for key, rows in groups.items():
            if len(rows) < int(self.policy.get("consolidation_threshold_same_type", 3)):
                continue
            if any(r.memory_type in PROTECTED_MEMORY_TYPES for r in rows):
                continue
            lesson = self._consolidate_group(key, rows)
            if lesson:
                created += 1
                if self.policy.get("archive_raw_after_consolidation", True):
                    archived += self._archive_sources(rows, lesson.id)
        self.session.add(
            SystemValidationAudit(
                actor="gate",
                action="memory_consolidation_run",
                decision="completed",
                reasoning=f"created={created} archived={archived}",
            )
        )
        ai_created = 0
        try:
            from app.services.ai_learning_memory_service import AILearningMemoryService

            ai_created = AILearningMemoryService(self.session, self.config).generate(force=force).get("created", 0)
        except Exception:
            pass
        self.session.flush()
        return {
            "status": "ok",
            "consolidated_created": created,
            "raw_archived": archived,
            "core_ai_promoted": ai_created,
            **self.status(),
        }

    def _group_raw(self, rows: list[LessonNode]) -> dict[str, list[LessonNode]]:
        groups: dict[str, list[LessonNode]] = defaultdict(list)
        for r in rows:
            key = "|".join(
                [
                    r.strategy_name or "",
                    r.symbol or "",
                    r.memory_type or "",
                    (r.pattern_key or "")[:40],
                ]
            )
            groups[key].append(r)
        return {k: v for k, v in groups.items() if len(v) >= 2}

    def _consolidate_group(self, key: str, rows: list[LessonNode]) -> Optional[LessonNode]:
        strategy = rows[0].strategy_name
        symbol = rows[0].symbol
        mtype = rows[0].memory_type
        summaries = [r.summary for r in rows[:8]]
        evidence_count = sum(r.occurrence_count for r in rows)
        title = f"Consolidated: {strategy or symbol or mtype}"[:80]
        summary = (
            f"Repeated pattern ({len(rows)} memories, {evidence_count} occurrences): "
            + (summaries[0][:200] if summaries else mtype)
        )
        existing = self.session.exec(
            select(LessonNode).where(
                LessonNode.pattern_key == f"consolidated|{key}",
                LessonNode.status == "active",
            )
        ).first()
        if existing:
            existing.occurrence_count += len(rows)
            existing.evidence_json = {
                "source_memory_ids": [r.id for r in rows],
                "evidence_count": evidence_count,
            }
            existing.last_confirmed_at = datetime.utcnow()
            existing.strength = min(1.0, existing.strength + 0.1)
            self.session.add(existing)
            return existing

        row = self.lessons.upsert_lesson(
            memory_type="consolidated_learning",
            title=title,
            summary=summary,
            detailed_lesson=summary,
            strategy_name=strategy,
            symbol=symbol,
            source="memory_consolidation",
            pattern_key=f"consolidated|{key}",
            can_influence_ranking=True,
            visible_to_ai=True,
            category=CATEGORY_AI_LEARNING,
        )
        if row:
            row.memory_level = MEMORY_LEVEL_CONSOLIDATED
            row.source_memory_ids_json = [r.id for r in rows]
            row.importance_score = min(1.0, 0.4 + len(rows) * 0.05)
            row.strength = min(1.0, 0.5 + evidence_count * 0.02)
            row.evidence_json = {"source_memory_ids": [r.id for r in rows], "group_key": key}
            row.system_validation_status = "validated"
            row.system_validator_rule = "consolidation_evidence_threshold"
            self.session.add(row)
            self._link_consolidated_edges(row, rows)
        return row

    def _link_consolidated_edges(self, consolidated: LessonNode, sources: list[LessonNode]) -> None:
        cid = f"lesson-{consolidated.id}"
        for src in sources[:15]:
            sid = f"lesson-{src.id}"
            self.session.add(
                MemoryEdge(
                    source_id=sid,
                    target_id=cid,
                    relation="converted_into_core_lesson",
                    weight=0.8,
                    evidence_count=src.occurrence_count,
                    lesson_id=consolidated.id,
                )
            )

    def _archive_sources(self, rows: list[LessonNode], consolidated_id: int) -> int:
        n = 0
        retention_days = int(self.policy.get("raw_memory_retention_days", 30))
        until = datetime.utcnow() + timedelta(days=retention_days)
        for r in rows:
            if r.memory_type in PROTECTED_MEMORY_TYPES:
                continue
            r.status = "archived"
            r.visible_in_graph = False
            r.archive_reason = "consolidated_duplicate"
            r.is_consolidated = True
            r.consolidated_into_memory_id = consolidated_id
            r.retention_until = until
            r.evidence_json = {
                **(r.evidence_json or {}),
                "archived_as_duplicate_of": consolidated_id,
                "evidence_preserved": True,
            }
            n += 1
            self.session.add(r)
        return n

    def archive_raw_duplicates(self) -> dict[str, Any]:
        raw = self._raw_active()
        archived = 0
        seen: dict[str, int] = {}
        for r in sorted(raw, key=lambda x: x.last_seen_at, reverse=True):
            pk = r.pattern_key or f"{r.memory_type}|{r.strategy_name}|{r.symbol}"
            if pk in seen:
                r.status = "archived"
                r.visible_in_graph = False
                r.archive_reason = "duplicate_raw"
                r.consolidated_into_memory_id = seen[pk]
                self.session.add(r)
                archived += 1
            else:
                seen[pk] = r.id or 0
        return {"status": "ok", "archived": archived}

    def list_consolidated(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(
            select(LessonNode)
            .where(LessonNode.memory_level.in_(("consolidated_lesson", "core_ai_lesson")))
            .order_by(LessonNode.last_seen_at.desc())
            .limit(limit)
        ).all()
        return [self.lessons._lesson_detail(r) for r in rows]
