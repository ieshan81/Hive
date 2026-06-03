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
    CATEGORY_SYMBOL_PATTERN,
    CATEGORY_SYSTEM,
    MEMORY_LEVEL_CONSOLIDATED,
    MEMORY_LEVEL_PATTERN,
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
        active = list(self.session.exec(select(LessonNode).where(LessonNode.status == "active")).all())
        consolidated = [r for r in active if r.memory_level in ("consolidated_lesson", "core_ai_lesson")]
        patterns = [
            r
            for r in active
            if r.memory_level == MEMORY_LEVEL_PATTERN
            or r.category == CATEGORY_SYMBOL_PATTERN
            or "pattern" in (r.memory_type or "")
        ]
        system_issues = [r for r in active if r.category == CATEGORY_SYSTEM]
        nudges = [r for r in active if "nudge" in (r.memory_type or "") or r.category == "nudge"]
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
        # Candidate raw memories = those already clustering into a group of >=2
        # (eligible to consolidate once the run thresholds are met).
        candidate_count = sum(len(v) for v in self._group_raw(raw).values())
        total = len(raw) + len(consolidated)
        ratio = round(len(consolidated) / max(total, 1), 3)
        should = self._should_run()

        last_consolidation_at: Optional[str] = None
        try:
            last_run = self.session.exec(
                select(SystemValidationAudit)
                .where(SystemValidationAudit.action == "memory_consolidation_run")
                .order_by(SystemValidationAudit.created_at.desc())
            ).first()
            if last_run and getattr(last_run, "created_at", None):
                last_consolidation_at = last_run.created_at.isoformat() + "Z"
        except Exception:
            last_consolidation_at = None

        return {
            "status": "ok",
            "total_raw_memories": len(raw),
            "consolidated_memories": len(consolidated),
            "archived_raw_memories": archived,
            "compression_ratio": ratio,
            "policy": self.policy,
            "should_consolidate": should,
            # --- Hive Mind diagnostics (TASK 7) ---
            "raw_memory_count": len(raw),
            "candidate_memory_count": candidate_count,
            "consolidated_memory_count": len(consolidated),
            "nudge_count": len(nudges),
            "pattern_count": len(patterns),
            "system_issue_count": len(system_issues),
            "last_consolidation_at": last_consolidation_at,
            "why_consolidation_skipped": None if should else self._why_skipped(raw),
            # learned_memory_count is the operator-facing name for consolidated lessons.
            "learned_memory_count": len(consolidated),
            "latest_visible_memory_titles": self._latest_visible_titles(
                consolidated, patterns, system_issues, nudges
            ),
        }

    @staticmethod
    def _latest_visible_titles(*groups: list) -> list[str]:
        seen: set = set()
        merged: list = []
        for g in groups:
            for r in g or []:
                rid = getattr(r, "id", None)
                if rid in seen:
                    continue
                seen.add(rid)
                merged.append(r)
        merged.sort(
            key=lambda r: getattr(r, "last_seen_at", None) or getattr(r, "first_seen_at", None) or datetime.min,
            reverse=True,
        )
        return [str(getattr(r, "title", "") or "") for r in merged[:8]]

    # Sane ceilings so a stale persisted MemoryPolicyConfig row (e.g. 100/25/10) cannot
    # starve consolidation — the bot must still form visible learned memories on modest
    # volume. Effective threshold = min(persisted, ceiling).
    _THRESHOLD_CEILINGS = {
        "consolidation_threshold_total_raw_memories": 12,
        "consolidation_threshold_per_strategy": 6,
        "consolidation_threshold_same_type": 3,
    }

    def _eff(self, key: str) -> int:
        ceiling = self._THRESHOLD_CEILINGS.get(key)
        raw = int(self.policy.get(key, ceiling or 0) or 0)
        return min(raw, ceiling) if ceiling else raw

    def _why_skipped(self, raw: list[LessonNode]) -> str:
        total_t = self._eff("consolidation_threshold_total_raw_memories")
        per_t = self._eff("consolidation_threshold_per_strategy")
        by_strategy: dict[str, int] = defaultdict(int)
        for r in raw:
            by_strategy[r.strategy_name or "unknown"] += 1
        max_strat = max(by_strategy.values(), default=0)
        return (
            f"raw {len(raw)}/{total_t} total and max {max_strat}/{per_t} per-strategy "
            "below consolidation thresholds"
        )

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
        if len(raw) >= self._eff("consolidation_threshold_total_raw_memories"):
            return True
        by_strategy: dict[str, int] = defaultdict(int)
        for r in raw:
            by_strategy[r.strategy_name or "unknown"] += 1
        thresh = self._eff("consolidation_threshold_per_strategy")
        return any(c >= thresh for c in by_strategy.values())

    def run(self, *, force: bool = False) -> dict[str, Any]:
        if not force and not self._should_run():
            return {"status": "skipped", "message": "Consolidation thresholds not met", **self.status()}
        raw = self._raw_active()
        groups = self._group_raw(raw)
        created = archived = 0
        same_type_min = self._eff("consolidation_threshold_same_type")
        for key, rows in groups.items():
            if len(rows) < same_type_min:
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
            from app.services.evidence_memory_service import EvidenceMemoryService

            ai_created = EvidenceMemoryService(self.session, self.config).generate(force=force).get("created", 0)
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
