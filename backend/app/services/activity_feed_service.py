"""Plain-English activity feed for operator visibility."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    ActivityLog,
    ExecutionLog,
    LessonNode,
    PaperExperimentDecision,
    SettingsActionAudit,
)
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import filter_lessons_post_nuke, get_latest_reset_epoch, record_created_after


def activity_feed(session: Session, limit: int = 80) -> dict[str, Any]:
    epoch = get_latest_reset_epoch(session)
    events: list[dict[str, Any]] = []

    for row in session.exec(
        select(SettingsActionAudit)
        .where(SettingsActionAudit.action.in_(("reset_epoch", "nuke_everything", "start_fresh_paper_learning")))
        .order_by(SettingsActionAudit.created_at.desc())
        .limit(10)
    ).all():
        events.append(
            {
                "at": _ts(row.created_at),
                "kind": "reset",
                "message": f"Reset event: {row.action}",
                "detail": dict(row.details_json or {}),
            }
        )

    for row in session.exec(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
    ).all():
        if epoch and not record_created_after(row, epoch.get("nuke_completed_at")):
            continue
        events.append(
            {
                "at": _ts(row.created_at),
                "kind": row.event_type,
                "message": row.message,
                "detail": row.details,
            }
        )

    for row in session.exec(
        select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(limit)
    ).all():
        if epoch and not record_created_after(row, epoch.get("nuke_completed_at")):
            continue
        sym = row.symbol or ""
        from app.services.order_display import enrich_execution_row

        enriched = enrich_execution_row(
            {
                "symbol": sym,
                "side": row.side,
                "status": row.status,
                "reject_reason": row.reject_reason,
                "broker_order_id": row.broker_order_id,
                "gates_failed_json": row.gates_failed_json,
                "limit_price": row.limit_price,
                "requested_qty": row.requested_qty,
            }
        )
        events.append(
            {
                "at": _ts(row.created_at),
                "kind": "candle_cycle" if row.cycle_run_id else "execution",
                "message": enriched.get("user_message", f"{sym} {row.status}")[:200],
                "detail": {
                    "status": row.status,
                    "symbol": sym,
                    "cycle_run_id": row.cycle_run_id,
                    "blocked_before_broker": enriched.get("blocked_before_broker"),
                    "submitted_to_broker": enriched.get("submitted_to_broker"),
                    "alpaca_message": enriched.get("alpaca_message"),
                    "broker_rejection": enriched.get("broker_rejection"),
                    "status_label": enriched.get("status_label"),
                },
            }
        )

    for row in session.exec(
        select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(limit)
    ).all():
        if epoch and not record_created_after(row, epoch.get("nuke_completed_at")):
            continue
        action = "Entry approved" if row.decision == "approved" else "Entry skipped"
        events.append(
            {
                "at": _ts(row.created_at),
                "kind": "decision",
                "message": f"{row.symbol} — {action}: {row.reason_code or row.reason_text or '—'}",
                "detail": {"decision": row.decision, "reason_code": row.reason_code},
            }
        )

    lessons = filter_lessons_post_nuke(
        session, list(session.exec(select(LessonNode).order_by(LessonNode.created_at.desc()).limit(30)).all())
    )
    for row in lessons:
        events.append(
            {
                "at": _ts(row.created_at),
                "kind": "lesson",
                "message": f"Lesson saved — {row.title[:80]}",
                "detail": {"memory_type": row.memory_type, "symbol": row.symbol},
            }
        )

    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    return {
        "status": "ok",
        "reset_epoch": epoch,
        "events": events[:limit],
        "count": len(events[:limit]),
    }


def _ts(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.strftime("%H:%M") + " " + dt.strftime("%Y-%m-%d")
