"""Paper-autopilot run journal, daily diagnostics, and export bundle.

Every scheduler tick appends a compact journal row (``SettingsActionAudit`` with
``action=JOURNAL_ACTION``). Daily diagnostics aggregate those rows; the export
bundle packages journal + diagnostics + current safety status into a single
JSON/zip artifact. An optional daily rotation persists a compact per-day
snapshot and prunes to the newest N (default 14).

Everything here is read/append-only paper telemetry — it places no orders,
changes no config, exposes no secrets, and never raises into a live tick (all
write paths are wrapped so journaling can never break trading-loop safety).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, SettingsActionAudit

JOURNAL_ACTION = "autonomous_paper_journal"
DAILY_BUNDLE_ACTION = "autonomous_paper_daily_bundle"
DEFAULT_DAILY_RETENTION = 14
DEFAULT_JOURNAL_RETENTION_DAYS = 14


# ─────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _day_key(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.utcnow()).strftime("%Y-%m-%d")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _summarize_tick(tick_result: dict) -> dict[str, Any]:
    """Reduce a scheduler ``tick()`` result to a compact, queryable record."""
    tr = tick_result or {}
    cycle = tr.get("cycle_result") or {}
    tick_status = tr.get("tick") or {}
    ts_summary = cycle.get("tick_summary") or {}

    orders_created = 0
    for src in (cycle, tr):
        if isinstance(src, dict) and src.get("orders_created") is not None:
            orders_created = _int(src.get("orders_created"))
            break

    return {
        "ts": _now_iso(),
        "status": tr.get("status"),
        "reason": tr.get("reason") or cycle.get("reason"),
        "action": cycle.get("action"),
        "orders_created": orders_created,
        "rejected_this_tick": _int(tr.get("rejected_this_tick")),
        "paused": bool(tick_status.get("paused")),
        "paused_reason": tick_status.get("paused_reason"),
        "ticks_today": tick_status.get("ticks_today"),
        "plain_summary": ts_summary.get("plain_summary") or cycle.get("message"),
    }


# ─────────────────────────────────────────────────────────────────────────
# Per-tick journal (append-only)
# ─────────────────────────────────────────────────────────────────────────

def record_tick(
    session: Session,
    *,
    operator: str,
    supervised: bool,
    tick_result: dict,
    commit: bool = False,
) -> dict[str, Any]:
    """Append one compact journal row for a scheduler tick. Never raises."""
    try:
        entry = _summarize_tick(tick_result)
        entry["operator"] = operator
        entry["supervised"] = bool(supervised)
        entry["day_key"] = _day_key()
        session.add(
            SettingsActionAudit(
                action=JOURNAL_ACTION,
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json=entry,
            )
        )
        if commit:
            session.commit()
        return entry
    except Exception:
        # Journaling is best-effort telemetry; a failure must never abort a tick.
        try:
            session.rollback()
        except Exception:
            pass
        return {}


def recent_journal(session: Session, *, limit: int = 200, day: Optional[str] = None) -> list[dict[str, Any]]:
    """Return recent journal entries (newest first). Optionally filter by day_key."""
    fetch = max(limit, 2000) if day else limit
    rows = list(
        session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == JOURNAL_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
            .limit(fetch)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        entry = dict(r.details_json or {})
        if not entry.get("ts") and r.created_at:
            entry["ts"] = r.created_at.isoformat() + "Z"
        if not entry.get("day_key") and r.created_at:
            entry["day_key"] = _day_key(r.created_at)
        if day and entry.get("day_key") != day:
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def prune_journal(session: Session, *, keep_days: int = DEFAULT_JOURNAL_RETENTION_DAYS, commit: bool = False) -> int:
    """Delete journal rows older than ``keep_days``. Returns rows deleted."""
    cutoff = datetime.utcnow() - timedelta(days=max(1, keep_days))
    rows = list(
        session.exec(
            select(SettingsActionAudit).where(SettingsActionAudit.action == JOURNAL_ACTION)
        ).all()
    )
    deleted = 0
    for r in rows:
        if (r.created_at or datetime.utcnow()) < cutoff:
            session.delete(r)
            deleted += 1
    if commit:
        session.commit()
    return deleted


# ─────────────────────────────────────────────────────────────────────────
# Daily diagnostics (aggregation)
# ─────────────────────────────────────────────────────────────────────────

def _empty_day(day_key: str) -> dict[str, Any]:
    return {
        "day_key": day_key,
        "ticks": 0,
        "supervised_ticks": 0,
        "orders_created": 0,
        "rejected": 0,
        "pauses": 0,
        "status_counts": {},
        "pause_reasons": {},
    }


def daily_diagnostics(session: Session, config: Optional[dict] = None, *, days: int = DEFAULT_DAILY_RETENTION) -> dict[str, Any]:
    """Aggregate the run journal into per-day counters over the trailing window."""
    days = max(1, int(days or DEFAULT_DAILY_RETENTION))
    cutoff_day = _day_key(datetime.utcnow() - timedelta(days=days - 1))
    entries = recent_journal(session, limit=10000)

    by_day: dict[str, dict[str, Any]] = {}
    totals = {"ticks": 0, "orders_created": 0, "rejected": 0, "pauses": 0}
    for e in entries:
        dk = e.get("day_key") or (e.get("ts") or "")[:10]
        if not dk or dk < cutoff_day:
            continue
        agg = by_day.setdefault(dk, _empty_day(dk))
        agg["ticks"] += 1
        totals["ticks"] += 1
        if e.get("supervised"):
            agg["supervised_ticks"] += 1
        oc = _int(e.get("orders_created"))
        rj = _int(e.get("rejected_this_tick"))
        agg["orders_created"] += oc
        agg["rejected"] += rj
        totals["orders_created"] += oc
        totals["rejected"] += rj
        status = e.get("status")
        if status:
            agg["status_counts"][status] = agg["status_counts"].get(status, 0) + 1
        if e.get("paused"):
            agg["pauses"] += 1
            totals["pauses"] += 1
            pr = e.get("paused_reason") or "unknown"
            agg["pause_reasons"][pr] = agg["pause_reasons"].get(pr, 0) + 1

    days_list = [by_day[k] for k in sorted(by_day.keys(), reverse=True)]
    return {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "window_days": days,
        "totals": totals,
        "days": days_list,
        "live_locked": True,
    }


# ─────────────────────────────────────────────────────────────────────────
# Export bundle
# ─────────────────────────────────────────────────────────────────────────

def _recent_execution_logs(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = list(
        session.exec(
            select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(limit)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "symbol": r.symbol,
                "side": r.side,
                "signal_type": r.signal_type,
                "status": r.status,
                "requested_qty": r.requested_qty,
                "filled_qty": r.filled_qty,
                "filled_avg_price": r.filled_avg_price,
                "reject_reason": r.reject_reason,
                "broker_order_id": r.broker_order_id,
                "submitted_at": r.submitted_at.isoformat() + "Z" if r.submitted_at else None,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
        )
    return out


def _scheduler_status(session: Session, config: Optional[dict]) -> dict[str, Any]:
    try:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        return AutonomousPaperScheduler(session, config).status()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": f"{type(exc).__name__}: {exc}"}


def _exit_monitor_status(session: Session, config: Optional[dict]) -> dict[str, Any]:
    try:
        from app.services.exit_monitor_service import exit_monitor_status

        return exit_monitor_status(session, config)
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": f"{type(exc).__name__}: {exc}"}


def _ai_boundaries_section() -> dict[str, Any]:
    from app.services.ai_boundaries import (
        AI_CAPABILITIES,
        AI_CONFIG_FORBIDDEN_PREFIXES,
        AI_CONFIG_PAPER_SAFE_ALLOWLIST,
    )

    return {
        "capabilities": AI_CAPABILITIES,
        "forbidden_config_prefixes": list(AI_CONFIG_FORBIDDEN_PREFIXES),
        "paper_safe_allowlist": list(AI_CONFIG_PAPER_SAFE_ALLOWLIST),
    }


_README = (
    "# Paper Autopilot Bundle\n\n"
    "Operator export of the caged paper-trading autopilot. Everything here is "
    "PAPER telemetry — no live orders, no secrets.\n\n"
    "Contents:\n"
    "- `scheduler_status.json` — current scheduler state, interval, and ABSOLUTE caps.\n"
    "- `exit_monitor_status.json` — per-position exit plans / missing-exit-plan flags.\n"
    "- `daily_diagnostics.json` — per-day tick/order/rejection/pause aggregates.\n"
    "- `run_journal.json` — compact per-tick journal (newest first).\n"
    "- `recent_execution_logs.json` — recent paper execution-log rows.\n"
    "- `ai_boundaries.json` — the AI advisory capability matrix + config allowlist.\n"
)


def paper_autopilot_bundle(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Assemble the one-click Paper Autopilot bundle as a dict of named files."""
    if config is None:
        try:
            from app.services.config_manager import ConfigManager

            config = ConfigManager(session).get_current()
        except Exception:
            config = {}

    return {
        "paper_autopilot/README.md": _README,
        "paper_autopilot/meta.json": {
            "generated_at": _now_iso(),
            "kind": "paper_autopilot_bundle",
            "live_locked": True,
            "broker_mode": "paper",
        },
        "paper_autopilot/scheduler_status.json": _scheduler_status(session, config),
        "paper_autopilot/exit_monitor_status.json": _exit_monitor_status(session, config),
        "paper_autopilot/daily_diagnostics.json": daily_diagnostics(session, config),
        "paper_autopilot/run_journal.json": recent_journal(session, limit=500),
        "paper_autopilot/recent_execution_logs.json": _recent_execution_logs(session),
        "paper_autopilot/ai_boundaries.json": _ai_boundaries_section(),
    }


def paper_autopilot_bundle_zip(session: Session, config: Optional[dict] = None) -> bytes:
    from app.services.diagnostic_export import bundle_dict_as_zip_bytes

    return bundle_dict_as_zip_bytes(paper_autopilot_bundle(session, config))


def paper_autopilot_bundle_filename() -> str:
    return f"paper_autopilot_bundle_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"


# ─────────────────────────────────────────────────────────────────────────
# Optional daily rotation (DB-backed; one row/day, prune to newest N)
# ─────────────────────────────────────────────────────────────────────────

def rotate_daily_bundle(
    session: Session,
    config: Optional[dict] = None,
    *,
    keep: int = DEFAULT_DAILY_RETENTION,
    commit: bool = False,
) -> dict[str, Any]:
    """Persist a compact daily snapshot (one per day_key) and prune to newest ``keep``.

    Stores the diagnostics + scheduler status (NOT the full bundle) so the table
    stays bounded; the full zip is always available on demand via the export
    endpoint. Re-running on the same day replaces that day's row (idempotent).
    """
    keep = max(1, int(keep or DEFAULT_DAILY_RETENTION))
    today = _day_key()
    snapshot = {
        "generated_at": _now_iso(),
        "day_key": today,
        "scheduler_status": _scheduler_status(session, config),
        "exit_monitor_status": _exit_monitor_status(session, config),
        "diagnostics": daily_diagnostics(session, config, days=keep),
        "live_locked": True,
    }

    rows = list(
        session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == DAILY_BUNDLE_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
        ).all()
    )
    # Replace today's snapshot if it already exists (idempotent within a day).
    for r in rows:
        if dict(r.details_json or {}).get("day_key") == today:
            session.delete(r)

    session.add(
        SettingsActionAudit(
            action=DAILY_BUNDLE_ACTION,
            actor="scheduler",
            broker_mode="paper",
            paper_broker=True,
            live_trading_locked=True,
            live_orders_enabled=False,
            details_json=snapshot,
        )
    )

    # Prune to newest `keep` distinct-day rows (excluding the one we just added,
    # which is not yet flushed into `rows`).
    remaining = [r for r in rows if dict(r.details_json or {}).get("day_key") != today]
    for stale in remaining[keep - 1:]:
        session.delete(stale)

    # Keep the per-tick journal bounded too.
    prune_journal(session, keep_days=keep)

    if commit:
        session.commit()
    return snapshot


def list_daily_bundles(session: Session, *, limit: int = DEFAULT_DAILY_RETENTION) -> list[dict[str, Any]]:
    rows = list(
        session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == DAILY_BUNDLE_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
            .limit(limit)
        ).all()
    )
    return [dict(r.details_json or {}) for r in rows]
