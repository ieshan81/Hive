"""Post-reset epoch marker — hide pre-reset rows from active APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, SettingsActionAudit


RESET_EPOCH_ACTION = "reset_epoch"
NUKE_EPOCH_ACTION = RESET_EPOCH_ACTION


def record_reset_epoch(session: Session, operator: str, *, deleted: dict[str, Any]) -> dict[str, Any]:
    at = datetime.utcnow()
    epoch_id = f"reset-{at.strftime('%Y%m%dT%H%M%S')}"
    row = SettingsActionAudit(
        action=RESET_EPOCH_ACTION,
        actor=operator,
        broker_mode="paper",
        paper_broker=True,
        live_trading_locked=True,
        live_orders_enabled=False,
        details_json={
            "reset_epoch_id": epoch_id,
            "nuke_epoch_id": epoch_id,
            "nuke_completed_at": at.isoformat() + "Z",
            "reset_completed_at": at.isoformat() + "Z",
            "deleted": deleted,
        },
    )
    session.add(row)
    session.flush()
    return {
        "reset_epoch_id": epoch_id,
        "nuke_epoch_id": epoch_id,
        "nuke_completed_at": at.isoformat() + "Z",
        "reset_completed_at": at.isoformat() + "Z",
    }


record_nuke_epoch = record_reset_epoch


def get_latest_reset_epoch(session: Session) -> Optional[dict[str, Any]]:
    rows = list(
        session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == RESET_EPOCH_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
        ).all()
    )
    if not rows:
        return None
    d = dict(rows[0].details_json or {})
    eid = d.get("reset_epoch_id") or d.get("nuke_epoch_id")
    completed = d.get("reset_completed_at") or d.get("nuke_completed_at")
    return {
        "reset_epoch_id": eid,
        "nuke_epoch_id": eid,
        "nuke_completed_at": completed,
        "reset_completed_at": completed,
        "recorded_at": rows[0].created_at.isoformat() + "Z" if rows[0].created_at else None,
    }


get_latest_nuke_epoch = get_latest_reset_epoch


def current_reset_epoch_id(session: Session) -> Optional[str]:
    epoch = get_latest_reset_epoch(session)
    return epoch.get("reset_epoch_id") if epoch else None


def nuke_status_export(session: Session) -> dict[str, Any]:
    epoch = get_latest_reset_epoch(session)
    post_nuke_lessons = len(
        filter_lessons_post_nuke(session, list(session.exec(select(LessonNode)).all()))
    )
    return {
        "status": "ok",
        "latest_reset": epoch,
        "latest_nuke": epoch,
        "post_nuke_lesson_count": post_nuke_lessons,
        "active_memory_cutoff": epoch.get("nuke_completed_at") if epoch else None,
    }


def record_created_after(row: Any, cutoff_iso: Optional[str]) -> bool:
    if not cutoff_iso:
        return True
    created = getattr(row, "created_at", None)
    if not created:
        return False
    try:
        cutoff = datetime.fromisoformat(str(cutoff_iso).replace("Z", ""))
        return created >= cutoff
    except ValueError:
        return True


def filter_lessons_post_nuke(session: Session, lessons: list[LessonNode]) -> list[LessonNode]:
    epoch = get_latest_reset_epoch(session)
    if not epoch:
        return lessons
    epoch_id = epoch.get("reset_epoch_id")
    cutoff = epoch.get("nuke_completed_at")
    out: list[LessonNode] = []
    for lesson in lessons:
        le = getattr(lesson, "reset_epoch_id", None)
        if le:
            if le == epoch_id:
                out.append(lesson)
        elif record_created_after(lesson, cutoff):
            out.append(lesson)
    return out


def filter_rows_post_nuke(session: Session, rows: list[Any]) -> list[Any]:
    epoch = get_latest_reset_epoch(session)
    if not epoch:
        return rows
    epoch_id = epoch.get("reset_epoch_id")
    cutoff = epoch.get("nuke_completed_at")
    out: list[Any] = []
    for row in rows:
        re = getattr(row, "reset_epoch_id", None)
        if re:
            if re == epoch_id:
                out.append(row)
        elif record_created_after(row, cutoff):
            out.append(row)
    return out
