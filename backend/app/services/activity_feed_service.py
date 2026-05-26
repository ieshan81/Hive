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
    tick_card = latest_tick_card(session)
    return {
        "status": "ok",
        "reset_epoch": epoch,
        "events": events[:limit],
        "count": len(events[:limit]),
        "latest_tick_card": tick_card,
    }


def latest_tick_card(session: Session) -> dict[str, Any]:
    """Structured latest tick narrative for Activity UI."""
    from app.services.config_manager import ConfigManager
    from app.services.capital_allocator import CapitalAllocatorService
    from app.services.exit_monitor_service import exit_monitor_status
    from app.services.push_pull_engine_service import PushPullEngineService
    from app.services.sentiment_status_service import ai_advisor_status, sentiment_status

    cfg = ConfigManager(session).get_current()
    tick = PushPullEngineService(session, cfg).latest_tick()
    sentiment = sentiment_status(session, cfg)
    advisor = ai_advisor_status(session, cfg)
    allocator = CapitalAllocatorService(session, cfg).status_summary()
    exit_mon = exit_monitor_status(session, cfg)

    top = tick.get("top_candidate") or tick.get("selected_candidate") or {}
    approved = int(tick.get("approved_count") or 0) > 0
    orders = int(tick.get("orders_created") or tick.get("order_count") or 0) > 0

    why = "Paper order submitted"
    if orders:
        why = "Approved and submitted to paper broker"
    elif approved:
        why = "Entry approved — awaiting broker fill"
    elif top.get("no_trade_reason"):
        why = f"Skipped — {str(top.get('no_trade_reason')).replace('_', ' ')}"
    elif tick.get("plain"):
        why = str(tick.get("plain"))[:200]

    return {
        "status": "ok",
        "tick_started": tick.get("tick_at"),
        "symbols_scanned": tick.get("symbols_scanned_count"),
        "candidates_ranked": len(tick.get("push_pull_scores") or []),
        "top_candidate": {
            "symbol": top.get("symbol"),
            "score": top.get("trade_quality_score"),
            "push_score": top.get("push_score"),
            "edge_after_cost_bps": top.get("edge_after_cost_bps"),
        },
        "strategy_used": "Crypto Push-Pull Baseline",
        "strategy_version": tick.get("strategy_version"),
        "scoring_model": tick.get("scoring_model") or "score_push_pull_setup",
        "score": top.get("trade_quality_score"),
        "why": why,
        "allocator_result": allocator.get("plain") or allocator.get("status"),
        "validator_result": tick.get("result"),
        "sentiment_status": sentiment.get("display_title"),
        "gemini_advisor_status": advisor.get("display_title"),
        "broker_result": "Order placed" if orders else ("No order" if not approved else "Pending"),
        "exit_monitor_result": exit_mon.get("plain_summary") or exit_mon.get("status"),
        "memory_created": None,
        "pl_impact": None,
        "technical": {
            "reason_breakdown": tick.get("reason_breakdown"),
            "no_trade_reason": top.get("no_trade_reason"),
            "rejected_candidates": tick.get("rejected_candidates"),
            "threshold_values": tick.get("threshold_values"),
        },
    }


def _ts(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.strftime("%H:%M") + " " + dt.strftime("%Y-%m-%d")
