"""Execution log queries scoped to scheduler ticks vs historical portfolio cycles."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, SettingsActionAudit
from app.services.diagnostic_export import serialize_execution_log


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.isoformat() + ("Z" if dt.tzinfo is None else "")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except ValueError:
        return None


def scheduler_windows(session: Session) -> dict[str, Any]:
    """Scheduler enable time and latest tick boundary for log scoping."""
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    enabled_row = session.exec(
        select(SettingsActionAudit)
        .where(SettingsActionAudit.action == "scheduler_enable")
        .order_by(SettingsActionAudit.created_at.desc())
    ).first()
    scheduler_enabled_at = _iso(enabled_row.created_at) if enabled_row and enabled_row.created_at else None

    sched = AutonomousPaperScheduler(session).status()
    last_tick_at = sched.get("last_tick_at")
    return {
        "scheduler_enabled": bool(sched.get("scheduler_enabled")),
        "scheduler_enabled_at": scheduler_enabled_at,
        "last_tick_at": last_tick_at,
        "scheduler_tick_id": last_tick_at,  # tick boundary id (ISO timestamp)
        "ticks_today": int(sched.get("ticks_today", 0)),
    }


def _annotate_log(
    row: dict[str, Any],
    *,
    scheduler_enabled_at: str | None,
    last_tick_at: str | None,
) -> dict[str, Any]:
    from app.services.order_display import enrich_execution_row

    created = row.get("created_at")
    source_window = "historical"
    historical = True
    if scheduler_enabled_at and created and created >= scheduler_enabled_at:
        source_window = "since_scheduler_enable"
        historical = False
    if last_tick_at and created and created >= last_tick_at:
        source_window = "since_last_tick"
        historical = False

    enriched = enrich_execution_row(
        {
            "event_id": row.get("event_id"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "status": row.get("status"),
            "reject_reason": row.get("reject_reason"),
            "limit_price": row.get("limit_price"),
            "tif": row.get("tif"),
            "requested_qty": row.get("requested_qty"),
            "requested_notional": row.get("requested_notional"),
            "filled_qty": row.get("filled_qty"),
            "filled_avg_price": row.get("filled_avg_price"),
            "broker_order_id": row.get("broker_order_id"),
            "client_order_id": row.get("broker_client_order_id"),
            "submitted_at": row.get("submitted_at") or created,
        }
    )
    status = str(row.get("status") or "")
    broker_status = "rejected" if "reject" in status.lower() or enriched.get("is_rejected") else status
    outcome = str(enriched.get("status_label") or status or "—")
    reason = enriched.get("reject_reason_plain") or row.get("reject_reason") or ""

    return {
        **row,
        **enriched,
        "timestamp": created,
        "cycle_run_id": row.get("cycle_run_id"),
        "scheduler_tick_id": last_tick_at if source_window == "since_last_tick" else None,
        "source_window": source_window,
        "historical": historical,
        "outcome": outcome,
        "broker_status": broker_status,
        "reason": reason,
    }


def list_execution_logs(
    session: Session,
    *,
    scope: str = "latest_tick",
    cycle_run_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """
    scope:
      - latest_tick: logs since last scheduler tick only (empty if no tick yet)
      - since_scheduler_enable: logs since scheduler was enabled
      - historical: logs before scheduler enable (or all if never enabled)
      - cycle: filter by portfolio cycle_run_id (legacy)
      - recent: last N logs regardless of scope (for debugging)
    """
    windows = scheduler_windows(session)
    scheduler_enabled_at = windows.get("scheduler_enabled_at")
    last_tick_at = windows.get("last_tick_at")

    rows = list(
        session.exec(select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(500)).all()
    )

    scope_norm = (scope or "latest_tick").lower().replace("-", "_")
    filtered: list[ExecutionLog] = []

    if scope_norm == "cycle" and cycle_run_id:
        cid = cycle_run_id if cycle_run_id != "latest" else None
        if cid:
            filtered = [r for r in rows if r.cycle_run_id == cid]
        else:
            from app.services.query_service import resolve_cycle_run_id

            cid = resolve_cycle_run_id(session, "latest")
            filtered = [r for r in rows if cid and r.cycle_run_id == cid]
    elif scope_norm == "latest_tick":
        tick_dt = _parse_iso(last_tick_at)
        if not tick_dt:
            filtered = []
        else:
            filtered = [r for r in rows if r.created_at and r.created_at >= tick_dt]
    elif scope_norm == "since_scheduler_enable":
        en_dt = _parse_iso(scheduler_enabled_at)
        if not en_dt:
            filtered = rows[:limit]
        else:
            filtered = [r for r in rows if r.created_at and r.created_at >= en_dt]
    elif scope_norm == "historical":
        en_dt = _parse_iso(scheduler_enabled_at)
        if en_dt:
            filtered = [r for r in rows if r.created_at and r.created_at < en_dt]
        else:
            filtered = list(rows)
    elif scope_norm in ("recent", "current_session"):
        en_dt = _parse_iso(scheduler_enabled_at)
        if en_dt:
            filtered = [r for r in rows if r.created_at and r.created_at >= en_dt]
        else:
            filtered = list(rows)
    elif scope_norm == "all":
        # All recent logs across every cycle, regardless of scheduler enable/tick window.
        filtered = list(rows)
    else:
        filtered = []

    serialized = [serialize_execution_log(r) for r in filtered[:limit]]
    annotated = [
        _annotate_log(
            s,
            scheduler_enabled_at=scheduler_enabled_at,
            last_tick_at=last_tick_at,
        )
        for s in serialized
        if s.get("status") not in ("pending",)
    ]

    if scope_norm == "latest_tick":
        annotated = [a for a in annotated if a.get("source_window") == "since_last_tick"]

    if scope_norm == "historical":
        annotated = [a for a in annotated if a.get("historical")]

    return {
        "status": "ok",
        "scope": scope_norm,
        "count": len(annotated),
        "scheduler_windows": windows,
        "execution_logs": annotated,
        "empty_reason": (
            "no_scheduler_tick_yet"
            if scope_norm == "latest_tick" and not last_tick_at
            else (
                "no_executions_in_window"
                if scope_norm == "latest_tick" and last_tick_at and not annotated
                else None
            )
        ),
    }
