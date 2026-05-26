"""AI Manager — human-readable learning summaries (not fake review cards)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode
from app.services.confidence_engine import ConfidenceEngine
from app.services.config_manager import ConfigManager
from app.services.push_pull_engine_service import PushPullEngineService


class AIManagerService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.confidence = ConfidenceEngine(session, self.config)

    def status(self) -> dict[str, Any]:
        conf = self.confidence.summary()
        lessons = self.lessons(limit=5)
        return {
            "status": "ok",
            "headline": "What the bot learned from paper push-pull trading",
            "confidence_overall": conf.get("overall"),
            "confidence_label": conf.get("overall_label"),
            "can_unlock_live": False,
            "recent_lessons_count": lessons.get("count", 0),
            "questions_answered": [
                "What did I do?",
                "Why did I do it?",
                "Did it work?",
                "What did I learn?",
                "What will I do differently next time?",
            ],
        }

    def memories(self, limit: int = 40) -> dict[str, Any]:
        rows = list(
            self.session.exec(select(LessonNode).order_by(LessonNode.created_at.desc()).limit(limit)).all()
        )
        return {
            "status": "ok",
            "memories": [
                {
                    "id": r.id,
                    "title": r.title,
                    "human_summary": _human_summary(r),
                    "memory_type": r.memory_type,
                    "category": r.category,
                    "symbol": r.symbol,
                    "strategy_name": r.strategy_name,
                    "severity": r.severity,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                }
                for r in rows
            ],
            "count": len(rows),
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
