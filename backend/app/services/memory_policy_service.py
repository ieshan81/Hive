"""Strict memory policy — episodic/semantic/consolidated, no spam."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode
from app.services.nuke_epoch_service import get_latest_reset_epoch
from app.trading_cage.memory_schema import MEMORY_TYPES, RANKING_INFLUENCE_TYPES, memory_record

CONSOLIDATION_WINDOW_HOURS = 24
SPAM_THRESHOLD = 3

# Events that should never become standalone memories
RAW_ONLY_EVENTS = frozenset(
    {
        "tick_completed",
        "scan_completed",
        "no_order_tick",
        "scheduler_tick",
        "quote_refreshed",
        "strategy_eligibility_checked",
    }
)

# Repeated blockers merge instead of spam
MERGE_BLOCKERS = frozenset(
    {
        "SYMBOL_COOLDOWN_ACTIVE",
        "DUPLICATE_OPEN_ORDER",
        "open_position_blocks_duplicate_entry",
        "NEGATIVE_EDGE_AFTER_COST",
        "STALE_QUOTE",
        "ALLOCATOR_MAX_POSITIONS",
    }
)


class MemoryPolicyService:
    def __init__(self, session: Session):
        self.session = session
        self.epoch = get_latest_reset_epoch(session)

    def status(self) -> dict[str, Any]:
        rows = list(self.session.exec(select(LessonNode)).all())
        epoch_id = (self.epoch or {}).get("reset_epoch_id")
        in_epoch = [r for r in rows if self._epoch_match(r, epoch_id)]

        validated = [r for r in in_epoch if (r.memory_type or "") not in ("raw_event", "pending")]
        pending = [r for r in in_epoch if r.memory_type == "pending" or r.status == "pending"]
        archived = [r for r in in_epoch if r.status == "archived"]
        consolidated = [r for r in in_epoch if r.memory_type == "consolidated_memory" or (r.occurrence_count or 0) > 1]

        latest_useful = None
        for r in sorted(in_epoch, key=lambda x: x.updated_at or x.created_at, reverse=True):
            if r.memory_type not in ("raw_event", "pending") and r.title:
                latest_useful = {"title": r.title, "summary": r.summary, "symbol": r.symbol}
                break

        return {
            "status": "ok",
            "reset_epoch_id": epoch_id,
            "counts": {
                "raw_event_count": len([r for r in in_epoch if r.memory_type == "raw_event"]),
                "candidate_count": len(pending),
                "validated_count": len(validated),
                "consolidated_count": len(consolidated),
                "archived_count": len(archived),
                "total_lesson_nodes": len(in_epoch),
                "meaningful_memory_count": len(validated) + len(consolidated),
            },
            "latest_useful_lesson": latest_useful,
            "what_bot_learned": latest_useful.get("summary") if latest_useful else "Fresh brain — no validated lessons yet.",
            "what_bot_will_avoid": self._avoidance_summary(in_epoch),
            "what_bot_will_test_next": "Continue paper push-pull with cost-validated entries only.",
            "hive_mind_visible_count": len(validated) + len(consolidated),
        }

    def propose_memory(
        self,
        *,
        event_type: str,
        lesson: str,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        evidence_refs: Optional[list] = None,
        memory_type: str = "risk_memory",
        severity: str = "info",
        source: str = "system",
        gemini_authored: bool = False,
        block_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Returns action: stored | merged | rejected | raw_log_only."""
        if event_type in RAW_ONLY_EVENTS:
            return {"action": "raw_log_only", "reason": "raw_event_not_memory"}

        if not evidence_refs and not block_reason:
            return {"action": "rejected", "reason": "missing_evidence_refs"}

        if memory_type not in MEMORY_TYPES:
            memory_type = "risk_memory"

        status = "pending" if gemini_authored else "validated"
        can_rank = memory_type in RANKING_INFLUENCE_TYPES and status == "validated"

        merge_key = self._merge_key(block_reason or memory_type, symbol, strategy)
        if block_reason in MERGE_BLOCKERS or (block_reason and "duplicate" in block_reason.lower()):
            existing = self._find_merge_candidate(merge_key, symbol)
            if existing:
                existing.occurrence_count = (existing.occurrence_count or 1) + 1
                existing.last_seen_at = datetime.utcnow()
                existing.summary = self._consolidated_summary(existing, lesson, block_reason)
                existing.memory_type = "consolidated_memory"
                self.session.add(existing)
                return {
                    "action": "merged",
                    "memory_id": existing.id,
                    "occurrence_count": existing.occurrence_count,
                }

        rec = memory_record(
            memory_type=memory_type,
            lesson=lesson,
            reset_epoch_id=(self.epoch or {}).get("reset_epoch_id"),
            symbol=symbol,
            strategy=strategy,
            evidence={"refs": evidence_refs or [], "block_reason": block_reason, "source": source},
            can_influence_ranking=can_rank,
        )
        row = LessonNode(
            memory_type=memory_type if status == "validated" else "pending",
            title=lesson[:120],
            summary=lesson[:500],
            detailed_lesson=str(rec),
            symbol=symbol,
            strategy_name=strategy,
            severity=severity.upper() if severity else "MEDIUM",
            status=status if status in ("active", "archived", "pending") else "active",
            occurrence_count=1,
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
            importance_score=0.7 if status == "validated" else 0.4,
            pattern_key=merge_key,
            reset_epoch_id=(self.epoch or {}).get("reset_epoch_id"),
            memory_level="pattern_memory" if status == "validated" else "raw_experience",
            can_influence_ranking=can_rank,
            visible_in_graph=status == "validated",
        )
        self.session.add(row)
        return {"action": "stored", "memory_id": row.id, "status": status}

    def hive_mind_memories(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = list(
            self.session.exec(
                select(LessonNode)
                .where(LessonNode.status.in_(("validated", "active")))
                .order_by(LessonNode.updated_at.desc())
                .limit(limit * 3)
            ).all()
        )
        epoch_id = (self.epoch or {}).get("reset_epoch_id")
        rows = [r for r in rows if self._epoch_match(r, epoch_id)]
        out = []
        for r in rows:
            if r.memory_type in ("raw_event", "pending"):
                continue
            if (r.importance_score or 0) < 0.5 and r.memory_type != "consolidated_memory":
                continue
            out.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "summary": r.summary,
                    "symbol": r.symbol,
                    "strategy": r.strategy_name,
                    "memory_type": r.memory_type,
                    "occurrence_count": r.occurrence_count or 1,
                    "importance_score": r.importance_score,
                    "last_seen_at": r.last_seen_at.isoformat() + "Z" if r.last_seen_at else None,
                }
            )
            if len(out) >= limit:
                break
        return out

    def _epoch_match(self, row: LessonNode, epoch_id: Optional[str]) -> bool:
        if not epoch_id:
            return True
        if getattr(row, "reset_epoch_id", None) == epoch_id:
            return True
        if row.created_at and epoch_id.replace("reset-", "") in (row.created_at.isoformat()[:10].replace("-", "")):
            return True
        return False

    def _merge_key(self, reason: str, symbol: Optional[str], strategy: Optional[str]) -> str:
        raw = f"{reason}|{symbol or ''}|{strategy or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _find_merge_candidate(self, merge_key: str, symbol: Optional[str]) -> Optional[LessonNode]:
        since = datetime.utcnow() - timedelta(hours=CONSOLIDATION_WINDOW_HOURS)
        rows = list(
            self.session.exec(
                select(LessonNode).where(
                    LessonNode.pattern_key == merge_key,
                    LessonNode.created_at >= since,
                )
            ).all()
        )
        return rows[0] if rows else None

    def _consolidated_summary(self, row: LessonNode, lesson: str, block_reason: Optional[str]) -> str:
        n = row.occurrence_count or 1
        sym = row.symbol or "symbol"
        reason = block_reason or row.title or "block"
        return f"{sym}: {reason} occurred {n} times in {CONSOLIDATION_WINDOW_HOURS}h — {lesson[:80]}"

    def _avoidance_summary(self, rows: list[LessonNode]) -> str:
        blockers: dict[str, int] = {}
        for r in rows:
            if r.memory_type == "consolidated_memory" and r.title:
                blockers[r.title[:60]] = r.occurrence_count or 1
        if not blockers:
            return "No repeated patterns recorded yet."
        top = max(blockers, key=blockers.get)
        return f"Avoid repeating: {top}"
