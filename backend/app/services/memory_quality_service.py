"""
5-Tier Memory System — Quality Scoring & Promotion Engine (DOMAIN 7).

Tiers (maps to existing LessonNode.memory_level):
  raw_event         → "raw_experience"    : Any logged event; expires after 7d; never ascends directly
  candidate_memory  → "pattern_memory"    : AI creates from ≥1 raw event
  validated_memory  → "consolidated_lesson": DSR-passing backtest OR ≥5 live confirmations p<0.05
  consolidated_memory → "core_ai_lesson"  : Survives 30d without contradiction; merged with similar
  archived_memory   → status="archived"   : Older than 180d OR replaced by newer consolidated

Quality Scoring Formula:
  quality = 0.30 * recurrence(min(occ/10, 1))
          + 0.25 * precision(p_value_inverse)
          + 0.20 * recency(exp(-days_since_last_use/30))
          + 0.15 * coverage(unique_symbols/10 capped)
          + 0.10 * falsifiability(0 or 1)

  promotion_floor = 0.60

Anti-Spam Rules (NEVER becomes a memory):
  - Per-tick/per-bar events without a trade outcome
  - "No order because cooldown" — log only, not memory
  - Repeated identical rejections within cooldown_window
  - Raw broker JSON / raw bar dumps
  - AI hourly chatter; writes ONLY after closed trade or backtest
  - AI lesson on single trade → tagged "speculative", blocked from ascending past candidate
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode


# ──────────────────────────────────────────────────────────────
# Tier constants
# ──────────────────────────────────────────────────────────────

TIER_LEVELS = {
    "raw_event": "raw_experience",
    "candidate": "pattern_memory",
    "validated": "consolidated_lesson",
    "consolidated": "core_ai_lesson",
}

TIER_FROM_DB = {v: k for k, v in TIER_LEVELS.items()}

PROMOTION_FLOOR = 0.60

RAW_EVENT_EXPIRY_DAYS = 7
CONSOLIDATED_SURVIVAL_DAYS = 30
ARCHIVED_AFTER_DAYS = 180

# Minimum occurrences / symbols for promotion
CANDIDATE_MIN_OCCURRENCES = 3
CANDIDATE_MIN_SYMBOLS = 2
CANDIDATE_WINDOW_DAYS = 30

VALIDATED_MIN_BACKTEST_DSR = 0.95
VALIDATED_MIN_LIVE_CONFIRMATIONS = 5

# Anti-spam: never promote if only 1 occurrence
SPECULATIVE_TAG = "speculative"


# ──────────────────────────────────────────────────────────────
# Quality scoring
# ──────────────────────────────────────────────────────────────

def compute_memory_quality(
    lesson: LessonNode,
    *,
    unique_symbols: int = 1,
    p_value: Optional[float] = None,
    has_falsifiable_evidence: bool = False,
) -> float:
    """
    quality = 0.30 * recurrence
            + 0.25 * precision
            + 0.20 * recency
            + 0.15 * coverage
            + 0.10 * falsifiability

    All components are 0–1. Returns 0–1.
    """
    # Recurrence — occurrence_count, capped at 10
    occ = max(1, lesson.occurrence_count or 1)
    recurrence = min(occ / 10.0, 1.0)

    # Precision — p-value inverse (lower p = higher confidence)
    if p_value is not None and 0 < p_value <= 1.0:
        precision = 1.0 - p_value
    else:
        # Fall back to lesson.confidence
        precision = float(lesson.confidence or 0.5)

    # Recency — exponential decay based on last_seen_at
    last_used = lesson.last_seen_at or lesson.updated_at or lesson.created_at
    days_since = (datetime.utcnow() - last_used).total_seconds() / 86_400
    recency = math.exp(-days_since / 30.0)

    # Coverage — unique symbols seen (capped at 10)
    coverage = min(unique_symbols / 10.0, 1.0)

    # Falsifiability — binary: does the lesson have a falsifiable evidence ref?
    falsifiability = 1.0 if has_falsifiable_evidence else 0.0

    quality = (
        0.30 * recurrence
        + 0.25 * precision
        + 0.20 * recency
        + 0.15 * coverage
        + 0.10 * falsifiability
    )
    return round(min(1.0, max(0.0, quality)), 4)


def memory_tier(lesson: LessonNode) -> str:
    """Map DB memory_level → canonical tier name."""
    if (lesson.status or "active") == "archived":
        return "archived"
    return TIER_FROM_DB.get(lesson.memory_level or "raw_experience", "raw_event")


# ──────────────────────────────────────────────────────────────
# Anti-spam filter
# ──────────────────────────────────────────────────────────────

ANTI_SPAM_KEYWORDS = (
    "cooldown",
    "no order",
    "rate limit",
    "tick ",
    "raw broker",
    "raw bar",
    "i noticed",   # AI chatter
    "i observe",
    "bar dump",
)

ANTI_SPAM_TYPES = {
    "tick_event",
    "cooldown_skip",
    "rate_limit_log",
    "bar_dump",
    "ai_hourly_chatter",
    "repeated_rejection",
}


def is_anti_spam(
    memory_type: str,
    summary: str,
    *,
    has_trade_outcome: bool = False,
    has_backtest_ref: bool = False,
) -> tuple[bool, str]:
    """
    Returns (is_spam, reason). Anti-spam memories must NEVER be stored.
    - Per-tick/per-bar events without a trade outcome
    - Cooldown skips (log-only)
    - Repeated identical rejections within cooldown_window
    - Raw broker JSON / raw bar dumps
    - AI hourly chatter without a closed trade or backtest ref
    """
    if memory_type in ANTI_SPAM_TYPES:
        return True, f"memory_type={memory_type} is anti-spam"

    summary_lower = (summary or "").lower()
    for kw in ANTI_SPAM_KEYWORDS:
        if kw in summary_lower:
            if not (has_trade_outcome or has_backtest_ref):
                return True, f"anti_spam_keyword='{kw}' without trade/backtest"

    return False, ""


# ──────────────────────────────────────────────────────────────
# Promotion logic
# ──────────────────────────────────────────────────────────────

def can_promote_to_candidate(lesson: LessonNode, *, unique_symbols: int = 1) -> tuple[bool, str]:
    """
    raw_event → candidate_memory requires:
      ≥ 3 independent recurrences across ≥ 2 symbols within 30 days.
    Single-trade AI lessons stay tagged "speculative" and cannot promote.
    """
    current_tier = memory_tier(lesson)
    if current_tier != "raw_event":
        return False, f"already_at_tier={current_tier}"

    tags = list(lesson.tags or [])
    if SPECULATIVE_TAG in tags:
        return False, "speculative_tag_blocks_promotion"

    if (lesson.occurrence_count or 1) < CANDIDATE_MIN_OCCURRENCES:
        return False, f"need_{CANDIDATE_MIN_OCCURRENCES}_occurrences_have_{lesson.occurrence_count or 1}"

    if unique_symbols < CANDIDATE_MIN_SYMBOLS:
        return False, f"need_{CANDIDATE_MIN_SYMBOLS}_symbols_have_{unique_symbols}"

    return True, "ok"


def can_promote_to_validated(
    lesson: LessonNode,
    *,
    dsr_p_value: Optional[float] = None,
    live_confirmations: int = 0,
) -> tuple[bool, str]:
    """
    candidate → validated requires:
      DSR-passing backtest (DSR_p > 0.95) OR ≥ 5 live confirmations p < 0.05
    """
    current_tier = memory_tier(lesson)
    if current_tier != "candidate":
        return False, f"not_at_candidate_tier={current_tier}"

    if dsr_p_value is not None and dsr_p_value >= VALIDATED_MIN_BACKTEST_DSR:
        return True, f"dsr_p={dsr_p_value:.3f}"

    if live_confirmations >= VALIDATED_MIN_LIVE_CONFIRMATIONS:
        return True, f"live_confirmations={live_confirmations}"

    return False, (
        f"need_dsr>={VALIDATED_MIN_BACKTEST_DSR}_or_{VALIDATED_MIN_LIVE_CONFIRMATIONS}_live; "
        f"dsr={dsr_p_value}_live={live_confirmations}"
    )


def can_promote_to_consolidated(lesson: LessonNode) -> tuple[bool, str]:
    """
    validated → consolidated requires:
      Survives 30 days without contradicting evidence; merged with similar memories.
    """
    current_tier = memory_tier(lesson)
    if current_tier != "validated":
        return False, f"not_at_validated_tier={current_tier}"

    validated_at = lesson.system_validated_at or lesson.created_at
    days_survived = (datetime.utcnow() - validated_at).total_seconds() / 86_400
    if days_survived < CONSOLIDATED_SURVIVAL_DAYS:
        return False, f"need_{CONSOLIDATED_SURVIVAL_DAYS}d_survived_have_{days_survived:.1f}d"

    return True, f"survived_{days_survived:.1f}d"


def should_archive(lesson: LessonNode) -> tuple[bool, str]:
    """
    Archive when:
      - Older than 180 days AND at consolidated or lower tier
      - OR replaced by a newer consolidated memory (is_consolidated=True with a replacement)
    Archived memories are read-only, used for AI context only.
    """
    age_days = (datetime.utcnow() - lesson.created_at).total_seconds() / 86_400

    if lesson.consolidated_into_memory_id is not None:
        return True, f"replaced_by_memory_{lesson.consolidated_into_memory_id}"

    if age_days > ARCHIVED_AFTER_DAYS:
        return True, f"age_{age_days:.0f}d_exceeds_{ARCHIVED_AFTER_DAYS}d"

    return False, ""


def should_expire_raw(lesson: LessonNode) -> bool:
    """Raw events expire after 7 days (never ascend directly)."""
    if memory_tier(lesson) != "raw_event":
        return False
    age_days = (datetime.utcnow() - lesson.created_at).total_seconds() / 86_400
    return age_days > RAW_EVENT_EXPIRY_DAYS


# ──────────────────────────────────────────────────────────────
# Batch promotion runner
# ──────────────────────────────────────────────────────────────

class MemoryQualityService:
    """
    Run promotion checks and quality score updates across all LessonNode records.
    Called by the training loop or a scheduled job.
    """

    def __init__(self, session: Session):
        self.session = session

    def run_promotion_pass(self) -> dict[str, Any]:
        """
        Single-pass: evaluate each active memory for promotion/archival.
        Returns summary of changes made.
        """
        lessons = self.session.exec(
            select(LessonNode).where(LessonNode.status == "active")
        ).all()

        promoted = 0
        archived = 0
        expired = 0
        errors = 0

        for lesson in lessons:
            try:
                changed = self._process_lesson(lesson)
                if changed == "promoted":
                    promoted += 1
                elif changed == "archived":
                    archived += 1
                elif changed == "expired":
                    expired += 1
            except Exception:
                errors += 1

        if promoted + archived + expired > 0:
            self.session.flush()

        return {
            "processed": len(lessons),
            "promoted": promoted,
            "archived": archived,
            "expired": expired,
            "errors": errors,
        }

    def _process_lesson(self, lesson: LessonNode) -> str:
        tier = memory_tier(lesson)

        # Check expiry for raw events
        if should_expire_raw(lesson):
            lesson.status = "archived"
            lesson.archive_reason = "raw_event_ttl_expired"
            lesson.updated_at = datetime.utcnow()
            self.session.add(lesson)
            return "expired"

        # Check general archive condition
        do_archive, reason = should_archive(lesson)
        if do_archive:
            lesson.status = "archived"
            lesson.archive_reason = reason
            lesson.updated_at = datetime.utcnow()
            self.session.add(lesson)
            return "archived"

        # Try promotion
        if tier == "raw_event":
            # Unique symbols from evidence_json
            evidence = lesson.evidence_json or {}
            unique_symbols = len(set(
                (evidence.get("symbols") or [lesson.symbol]) if lesson.symbol else ["*"]
            ))
            ok, reason = can_promote_to_candidate(lesson, unique_symbols=unique_symbols)
            if ok:
                lesson.memory_level = TIER_LEVELS["candidate"]
                lesson.can_influence_ranking = True
                lesson.updated_at = datetime.utcnow()
                self.session.add(lesson)
                return "promoted"

        elif tier == "candidate":
            evidence = lesson.evidence_json or {}
            dsr_p = evidence.get("dsr_p_value")
            live_conf = int(evidence.get("live_confirmations", 0) or 0)
            ok, reason = can_promote_to_validated(lesson, dsr_p_value=dsr_p, live_confirmations=live_conf)
            if ok:
                lesson.memory_level = TIER_LEVELS["validated"]
                lesson.system_validated_at = datetime.utcnow()
                lesson.system_validation_status = "validated"
                lesson.updated_at = datetime.utcnow()
                self.session.add(lesson)
                return "promoted"

        elif tier == "validated":
            ok, reason = can_promote_to_consolidated(lesson)
            if ok:
                lesson.memory_level = TIER_LEVELS["consolidated"]
                lesson.is_consolidated = True
                lesson.updated_at = datetime.utcnow()
                self.session.add(lesson)
                return "promoted"

        return "unchanged"

    def update_quality_scores(self) -> int:
        """Recompute importance_score for all active memories."""
        lessons = self.session.exec(
            select(LessonNode).where(LessonNode.status == "active")
        ).all()
        updated = 0
        for lesson in lessons:
            evidence = lesson.evidence_json or {}
            unique_syms = len(set(evidence.get("symbols") or ([lesson.symbol] if lesson.symbol else ["*"])))
            dsr_p = evidence.get("dsr_p_value")
            falsifiable = bool(evidence.get("trade_ids") or evidence.get("backtest_run_id"))
            q = compute_memory_quality(lesson, unique_symbols=unique_syms, p_value=dsr_p, has_falsifiable_evidence=falsifiable)
            if abs(q - float(lesson.importance_score or 0.0)) > 0.001:
                lesson.importance_score = q
                lesson.updated_at = datetime.utcnow()
                self.session.add(lesson)
                updated += 1
        if updated:
            self.session.flush()
        return updated

    def tag_speculative(self, lesson_id: int) -> bool:
        """Tag a lesson as speculative (single-trade AI lesson, blocked from promotion)."""
        lesson = self.session.get(LessonNode, lesson_id)
        if not lesson:
            return False
        tags = list(lesson.tags or [])
        if SPECULATIVE_TAG not in tags:
            tags.append(SPECULATIVE_TAG)
            lesson.tags = tags
            lesson.can_influence_ranking = False
            lesson.updated_at = datetime.utcnow()
            self.session.add(lesson)
            self.session.flush()
        return True

    def status_summary(self) -> dict[str, Any]:
        """Count memories by tier."""
        lessons = self.session.exec(select(LessonNode)).all()
        by_tier: dict[str, int] = {
            "raw_event": 0, "candidate": 0, "validated": 0,
            "consolidated": 0, "archived": 0, "other": 0,
        }
        for l in lessons:
            t = memory_tier(l)
            if t in by_tier:
                by_tier[t] += 1
            else:
                by_tier["other"] += 1
        return {
            "total": len(lessons),
            "by_tier": by_tier,
            "promotion_floor": PROMOTION_FLOOR,
        }
