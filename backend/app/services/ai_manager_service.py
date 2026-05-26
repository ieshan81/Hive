"""AI Manager — human-readable learning summaries (not fake review cards)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode
from app.services.confidence_engine import ConfidenceEngine
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import filter_lessons_post_nuke, get_latest_nuke_epoch, nuke_status_export
from app.services.push_pull_engine_service import PushPullEngineService


class AIManagerService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.confidence = ConfidenceEngine(session, self.config)

    def status(self) -> dict[str, Any]:
        conf = self.confidence.summary()
        lessons = self.lessons(limit=5)
        from app.services.memory_policy_service import MemoryPolicyService

        memory = MemoryPolicyService(self.session).status()
        nuke = get_latest_nuke_epoch(self.session)
        count = memory.get("counts", {}).get("meaningful_memory_count", 0)
        if nuke and count == 0:
            headline = "Fresh brain. No validated memories yet. Paper learning available."
        else:
            headline = "What the bot learned from paper push-pull trading"
        return {
            "status": "ok",
            "headline": headline,
            "fresh_brain": bool(nuke and count == 0),
            "nuke_status": nuke_status_export(self.session),
            "memory_policy": memory,
            "memory_categories": memory.get("counts"),
            "confidence_overall": conf.get("overall"),
            "confidence_label": conf.get("overall_label"),
            "can_unlock_live": False,
            "recent_lessons_count": count,
            "questions_answered": [
                "What did I do?",
                "Why did I do it?",
                "Did it work?",
                "What did I learn?",
                "What will I do differently next time?",
            ],
        }

    def memories(self, limit: int = 40) -> dict[str, Any]:
        from app.services.memory_policy_service import MemoryPolicyService

        policy = MemoryPolicyService(self.session)
        rows = policy.hive_mind_memories(limit)
        nuke = get_latest_nuke_epoch(self.session)
        return {
            "status": "ok",
            "fresh_brain": bool(nuke and len(rows) == 0),
            "nuke_epoch": nuke,
            "memories": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "human_summary": r.get("summary") or r.get("title"),
                    "memory_type": r.get("memory_type"),
                    "symbol": r.get("symbol"),
                    "strategy_name": r.get("strategy"),
                    "occurrence_count": r.get("occurrence_count", 1),
                    "last_seen_at": r.get("last_seen_at"),
                }
                for r in rows
            ],
            "count": len(rows),
            "meaningful_memory_count": policy.status().get("counts", {}).get("meaningful_memory_count"),
        }

    def lessons(self, limit: int = 30) -> dict[str, Any]:
        return PushPullEngineService(self.session, self.config).lessons(limit)

    def strategy_confidence(self) -> dict[str, Any]:
        return self.confidence.by_strategy()


def _human_summary(row: LessonNode) -> str:
    text = (row.summary or row.detailed_lesson or row.title or "").strip()
    code = (row.memory_type or "").lower()
    sym = row.symbol or ""
    if "reject" in code or "broker" in text.lower():
        if "USDC" in (sym + text).upper():
            return (
                f"{sym}: rejected because the paper account has no USDC. "
                "Avoid USDC pairs unless USDC balance exists."
            )
        if "USDT" in (sym + text).upper():
            return (
                f"{sym}: rejected because the paper account has no USDT. "
                "Avoid USDT pairs unless USDT balance exists."
            )
        return f"{sym}: broker blocked this push — {text[:120]}"
    if "daily_trade" in text.lower() or "max experiment" in text.lower():
        return "Legacy daily trade cap memory — not active under opportunity-based allocator."
    if "spread" in text.lower():
        return f"Push failed after spread cost on {sym}. Require stronger edge before entry."
    if text:
        return text[:240]
    return row.title or "Lesson recorded from paper trading."
