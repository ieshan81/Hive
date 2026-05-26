"""Post-nuke epoch marker — hide pre-nuke memories from active graph/APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, SettingsActionAudit


NUKE_EPOCH_ACTION = "nuke_epoch"


def record_nuke_epoch(session: Session, operator: str, *, deleted: dict[str, Any]) -> dict[str, Any]:
    """Persist nuke timestamp; must not be deleted by subsequent nukes."""
    at = datetime.utcnow()
    epoch_id = f"nuke-{at.strftime('%Y%m%dT%H%M%S')}"
    row = SettingsActionAudit(
        action=NUKE_EPOCH_ACTION,
        actor=operator,
        broker_mode="paper",
        paper_broker=True,
        live_trading_locked=True,
        live_orders_enabled=False,
        details_json={
            "nuke_epoch_id": epoch_id,
            "nuke_completed_at": at.isoformat() + "Z",
            "deleted": deleted,
        },
    )
    session.add(row)
    session.flush()
    return {
        "nuke_epoch_id": epoch_id,
        "nuke_completed_at": at.isoformat() + "Z",
    }


def get_latest_nuke_epoch(session: Session) -> Optional[dict[str, Any]]:
    rows = list(
        session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == NUKE_EPOCH_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
        ).all()
    )
    if not rows:
        return None
    d = dict(rows[0].details_json or {})
    return {
        "nuke_epoch_id": d.get("nuke_epoch_id"),
        "nuke_completed_at": d.get("nuke_completed_at"),
        "recorded_at": rows[0].created_at.isoformat() + "Z" if rows[0].created_at else None,
    }


def nuke_status_export(session: Session) -> dict[str, Any]:
    epoch = get_latest_nuke_epoch(session)
    post_nuke_lessons = 0
    if epoch and epoch.get("nuke_completed_at"):
        post_nuke_lessons = _count_lessons_after(session, epoch["nuke_completed_at"])
    return {
        "status": "ok",
        "latest_nuke": epoch,
        "post_nuke_lesson_count": post_nuke_lessons,
        "active_memory_cutoff": epoch.get("nuke_completed_at") if epoch else None,
    }


def record_created_after(row: Any, nuke_at_iso: Optional[str]) -> bool:
    if not nuke_at_iso:
        return True
    created = getattr(row, "created_at", None)
    if not created:
        return True
    try:
        cutoff = datetime.fromisoformat(str(nuke_at_iso).replace("Z", ""))
        return created >= cutoff
    except ValueError:
        return True


def lesson_created_after(lesson: LessonNode, nuke_at_iso: Optional[str]) -> bool:
    return record_created_after(lesson, nuke_at_iso)


def filter_lessons_post_nuke(session: Session, lessons: list[LessonNode]) -> list[LessonNode]:
    epoch = get_latest_nuke_epoch(session)
    if not epoch:
        return lessons
    cutoff = epoch.get("nuke_completed_at")
    return [l for l in lessons if lesson_created_after(l, cutoff)]


def filter_rows_post_nuke(session: Session, rows: list[Any]) -> list[Any]:
    epoch = get_latest_nuke_epoch(session)
    if not epoch:
        return rows
    cutoff = epoch.get("nuke_completed_at")
    return [r for r in rows if record_created_after(r, cutoff)]


def _count_lessons_after(session: Session, nuke_at_iso: str) -> int:
    return len(filter_lessons_post_nuke(session, list(session.exec(select(LessonNode)).all())))
