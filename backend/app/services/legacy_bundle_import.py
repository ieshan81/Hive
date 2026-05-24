"""Import legacy AI bundle concepts as archived reference — never active trading rules."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.services.lesson_memory_service import LessonMemoryService
from app.services.memory_categories import CATEGORY_LEGACY


LEGACY_CONCEPTS = [
    {
        "memory_type": "stale_exit_detection",
        "title": "Stale exit decision detection",
        "summary": "Monitor exit decisions that remain open beyond expected hold horizon.",
    },
    {
        "memory_type": "capital_trap_detection",
        "title": "Capital trap detection",
        "summary": "Detect when capital is locked in low-liquidity positions with poor exit options.",
    },
    {
        "memory_type": "price_divergence_guard",
        "title": "Price divergence guard",
        "summary": "Flag when broker price diverges from signal reference beyond tolerance.",
    },
    {
        "memory_type": "liquidity_recovery_exit",
        "title": "Liquidity recovery exit",
        "summary": "Consider exit when spread normalizes after liquidity stress.",
    },
    {
        "memory_type": "exit_worker_heartbeat",
        "title": "Exit worker heartbeat monitor",
        "summary": "Ensure position monitor / exit worker runs each cycle.",
    },
    {
        "memory_type": "repeated_warning_pattern",
        "title": "Repeated warning pattern aggregation",
        "summary": "Aggregate repeated risk warnings into a single actionable pattern.",
    },
]


class LegacyBundleImport:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.lessons = LessonMemoryService(session, config)

    def import_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        imported = 0
        skipped = 0
        notes = payload.get("notes") or payload.get("ai_strategy_notes") or []
        patterns = payload.get("patterns") or []
        skills = payload.get("proposed_skills") or payload.get("skills") or []

        for concept in LEGACY_CONCEPTS:
            row = self.lessons.upsert_lesson(
                memory_type=concept["memory_type"],
                title=concept["title"],
                summary=concept["summary"],
                detailed_lesson=concept["summary"] + " (imported legacy reference — review before activation)",
                category=CATEGORY_LEGACY,
                severity="LOW",
                confidence=0.4,
                source="legacy_bot",
                visible_in_graph=False,
                visible_to_ai=False,
                can_influence_ranking=False,
                evidence={"import": "legacy_ai_bundle", "concept": concept["memory_type"]},
            )
            self.lessons.archive(row.id, reason="legacy import", hide_from_ai=True, hide_from_graph=True)
            imported += 1

        for note in notes[:40]:
            text = note if isinstance(note, str) else note.get("note") or note.get("text") or ""
            if not text:
                skipped += 1
                continue
            row = self.lessons.upsert_lesson(
                memory_type="operator_note",
                title=text[:80],
                summary=text[:300],
                detailed_lesson=text,
                category=CATEGORY_LEGACY,
                source="legacy_bot",
                visible_in_graph=False,
                visible_to_ai=False,
                can_influence_ranking=False,
                evidence={"legacy_note": True},
            )
            self.lessons.archive(row.id, reason="legacy note")
            imported += 1

        for p in patterns[:19]:
            title = p if isinstance(p, str) else p.get("title") or p.get("pattern") or "pattern"
            row = self.lessons.upsert_lesson(
                memory_type="repeated_warning_pattern",
                title=str(title)[:80],
                summary=str(p)[:300] if not isinstance(p, str) else p,
                detailed_lesson="Legacy pattern reference",
                category=CATEGORY_LEGACY,
                source="legacy_bot",
                visible_in_graph=False,
                visible_to_ai=False,
                evidence={"legacy_pattern": p},
            )
            self.lessons.archive(row.id, reason="legacy pattern")
            imported += 1

        return {
            "status": "ok",
            "imported": imported,
            "skipped": skipped,
            "message": "Legacy memories imported as archived reference only. Human review required to activate.",
        }
