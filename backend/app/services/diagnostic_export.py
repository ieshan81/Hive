"""Diagnostic bundle export — DB truth first, dashboard last."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    ActivityLog,
    AIReview,
    AIMemory,
    AIConfigProposal,
    AIUsageLog,
    BacktestResult,
    BlockedTrade,
    BrokerError,
    ExecutionLog,
    KillSwitchEvent,
    MonteCarloResult,
    OrderRecord,
    PortfolioDecision,
    PositionSnapshot,
    RiskEvent,
    StrategySignal,
    StrategyState,
    SymbolCandidate,
    SystemHealth,
    TradeRecord,
    LessonNode,
    MemoryEdge,
    MemoryEvidence,
)
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.config_manager import ConfigManager
from app.services.cycle_persistence import (
    count_cycle_rows,
    database_fingerprint,
    latest_cycle_end,
    _risk_event_cycle_id,
)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


def _latest_stale_quote_log(session: Session) -> dict[str, Any]:
    row = session.exec(
        select(ExecutionLog)
        .where(ExecutionLog.reject_reason == "STALE_QUOTE")
        .order_by(ExecutionLog.created_at.desc())
    ).first()
    if not row:
        return {"status": "none"}
    gf = row.gates_failed_json if isinstance(row.gates_failed_json, dict) else {}
    return {
        "symbol": row.symbol,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "quote_refreshed": gf.get("quote_refreshed"),
        "quote_refresh_result": gf.get("quote_refresh_result"),
        "quote_age_seconds_at_submit": gf.get("quote_age_seconds_at_submit"),
    }


def _serialize_row(row) -> dict[str, Any]:
    """Generic ORM serializer — materialize immediately to survive session expiry."""
    if hasattr(row, "model_dump"):
        data = row.model_dump(mode="python")
    else:
        data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = _iso(value)
    return data


def _paper_learning_status_export(
    session: Session, config: dict, apl_svc: Any, apl_sched: Any
) -> dict[str, Any]:
    from app.services.paper_learning_truth import paper_learning_display_status

    display = paper_learning_display_status(session, config)
    sched = apl_sched.status()
    return {
        **display,
        "mode_enabled": display.get("mode_enabled"),
        "can_place_paper_orders": display.get("can_place_paper_orders"),
        "scheduler_enabled": bool(sched.get("scheduler_enabled")),
        "current_mode": display.get("current_mode"),
        "scheduler": sched,
    }


def _is_useful_row(data: dict[str, Any]) -> bool:
    if not data:
        return False
    return any(v is not None for k, v in data.items() if k != "id") or data.get("id") is not None


def serialize_activity(row: ActivityLog) -> dict[str, Any]:
    details = row.details if isinstance(row.details, dict) else {}
    evidence = details.get("evidence_json")
    if evidence is None and details and row.event_type not in ("cycle_end", "cycle_start"):
        evidence = details
    msg = getattr(row, "message", None) or details.get("message")
    if not msg:
        msg = f"{row.event_type}: {details.get('symbol') or 'system'}"
    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "cycle_run_id": details.get("cycle_run_id"),
        "event_type": row.event_type,
        "source": details.get("source", "system"),
        "message": msg,
        "symbol": details.get("symbol"),
        "strategy": details.get("strategy"),
        "status": details.get("status"),
        "evidence_json": evidence,
    }


def serialize_strategy_signal(row: StrategySignal) -> dict[str, Any]:
    meta = row.signal_metadata if isinstance(row.signal_metadata, dict) else {}
    return {
        "id": row.id,
        "cycle_run_id": row.cycle_run_id,
        "symbol": row.symbol,
        "asset_class": row.asset_class,
        "strategy_name": row.strategy,
        "side": row.side,
        "signal_strength": row.strength,
        "confidence": row.confidence,
        "signal_type": row.signal_type,
        "signal": row.signal,
        "status": row.status,
        "entry_reason": meta.get("entry_reason") or meta.get("reason"),
        "invalidation_reason": meta.get("invalidation_reason"),
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "expected_hold_time": meta.get("expected_hold_time"),
        "created_at": _iso(row.created_at),
    }


def serialize_risk_event(row: RiskEvent) -> dict[str, Any]:
    details = row.details if isinstance(row.details, dict) else {}
    evidence = details.get("evidence") if isinstance(details.get("evidence"), dict) else {}
    return {
        "id": row.id,
        "cycle_run_id": evidence.get("cycle_run_id") or details.get("cycle_run_id"),
        "symbol": evidence.get("symbol"),
        "strategy": evidence.get("strategy"),
        "event_type": row.event_type,
        "risk_rule": details.get("risk_rule"),
        "block_reason_code": details.get("block_reason_code"),
        "human_reason": details.get("human_reason"),
        "evidence_json": evidence or None,
        "created_at": _iso(row.created_at),
    }


def serialize_portfolio_decision(row: PortfolioDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "cycle_run_id": row.cycle_run_id,
        "signal_id": row.signal_id,
        "symbol": row.symbol,
        "side": row.side,
        "signal_type": row.signal_type,
        "portfolio_status": row.portfolio_status,
        "portfolio_reason_code": row.portfolio_reason_code,
        "human_reason": row.human_reason,
        "ranking_score": row.ranking_score,
        "portfolio_rank": row.portfolio_rank,
        "selected_for_execution": row.selected_for_execution,
        "evidence_json": row.evidence_json,
        "created_at": _iso(row.created_at),
    }


def serialize_execution_log(row: ExecutionLog) -> dict[str, Any]:
    from app.services.order_display import enrich_execution_row

    base = {
        "event_id": row.event_id,
        "cycle_run_id": row.cycle_run_id,
        "signal_id": row.signal_id,
        "portfolio_decision_id": row.portfolio_decision_id,
        "symbol": row.symbol,
        "side": row.side,
        "signal_type": row.signal_type,
        "requested_qty": row.requested_qty,
        "requested_notional": row.requested_notional,
        "limit_price": row.limit_price,
        "tif": row.tif,
        "bid_at_decision": row.bid_at_decision,
        "ask_at_decision": row.ask_at_decision,
        "mid_at_decision": row.mid_at_decision,
        "spread_pct_at_decision": row.spread_pct_at_decision,
        "atr14_at_decision": row.atr14_at_decision,
        "expected_move_pct": row.expected_move_pct,
        "edge_over_cost": row.edge_over_cost,
        "risk_pct": row.risk_pct,
        "gates_passed_json": row.gates_passed_json,
        "gates_failed_json": row.gates_failed_json,
        "broker_order_id": row.broker_order_id,
        "broker_client_order_id": row.broker_client_order_id,
        "status": row.status,
        "reject_reason": row.reject_reason,
        "created_at": _iso(row.created_at),
    }
    return enrich_execution_row(base)


def serialize_blocked_trade(row: BlockedTrade) -> dict[str, Any]:
    return {
        "id": row.id,
        "cycle_run_id": row.cycle_run_id,
        "symbol": row.symbol,
        "strategy": row.strategy,
        "side": row.side,
        "reason": row.reason,
        "block_reason_code": row.block_reason_code,
        "human_reason": row.human_reason,
        "risk_rule": row.risk_rule,
        "evidence_json": row.evidence_json,
        "risk_engine_result": row.risk_engine_result,
        "risk_checks_failed": row.risk_checks_failed,
        "proposed_qty": row.proposed_qty,
        "signal_id": row.signal_id,
        "created_at": _iso(row.created_at),
    }


def serialize_broker_error(
    row: BrokerError,
    *,
    latest_cycle_id: Optional[str],
    cycle_started: Optional[str],
    scheduler_enabled_at: Optional[str] = None,
    scheduler_last_tick_at: Optional[str] = None,
) -> dict[str, Any]:
    details = row.details if isinstance(row.details, dict) else {}
    cycle_id = row.cycle_run_id or details.get("cycle_run_id")
    created_iso = _iso(row.created_at)

    # "Latest" should mean "latest scheduler tick window" when scheduler is enabled.
    # If scheduler is enabled but no tick has run yet, do not mark any broker errors as latest-cycle.
    is_latest = False
    if scheduler_enabled_at and not scheduler_last_tick_at:
        is_latest = False
    elif scheduler_last_tick_at and created_iso:
        is_latest = created_iso >= scheduler_last_tick_at
    elif latest_cycle_id and cycle_id == latest_cycle_id:
        # Fallback: legacy last-cycle heuristic (non-scheduler use cases).
        is_latest = True
    elif latest_cycle_id and cycle_started and created_iso:
        is_latest = created_iso >= cycle_started

    historical = True
    source_window = "historical"
    if scheduler_enabled_at and created_iso and created_iso >= scheduler_enabled_at:
        historical = False
        source_window = "since_scheduler_enable"
    if scheduler_last_tick_at and created_iso and created_iso >= scheduler_last_tick_at:
        historical = False
        source_window = "since_last_tick"
    return {
        "id": row.id,
        "source": row.source,
        "operation": row.operation,
        "message": row.message,
        "details": details or None,
        "created_at": created_iso,
        "cycle_run_id": cycle_id,
        "is_latest_cycle": is_latest,
        "historical": historical,
        "source_window": source_window,
    }


def _materialize(rows: list, serializer) -> list[dict[str, Any]]:
    out = [serializer(r) for r in rows]
    return [r for r in out if _is_useful_row(r)]


def _annotate_source_window(
    rows: list[dict[str, Any]],
    *,
    scheduler_enabled_at: str | None,
    scheduler_last_tick_at: str | None,
    created_key: str = "created_at",
) -> list[dict[str, Any]]:
    """Tag rows with whether they are historical vs scheduler/tick windows."""
    out: list[dict[str, Any]] = []
    for r in rows:
        created = (r or {}).get(created_key)
        source_window = "historical"
        historical = True
        if scheduler_enabled_at and created and created >= scheduler_enabled_at:
            source_window = "since_scheduler_enable"
            historical = False
        if scheduler_last_tick_at and created and created >= scheduler_last_tick_at:
            source_window = "since_last_tick"
            historical = False
        out.append({**r, "historical": historical, "source_window": source_window})
    return out


def _row_created_at(row) -> str:
    created = getattr(row, "created_at", None)
    if created is None:
        return ""
    return created.isoformat() + "Z"


def _filter_cycle_rows(
    rows: list,
    cycle_run_id: Optional[str],
    started_at: Optional[str],
    *,
    cycle_id_getter,
) -> list:
    if not cycle_run_id:
        return rows
    by_id = [r for r in rows if cycle_id_getter(r) == cycle_run_id]
    if by_id:
        return by_id
    if started_at:
        return [r for r in rows if _row_created_at(r) >= started_at]
    return rows


def _resolve_cycle_status(last_cycle: dict[str, Any], health: Optional[SystemHealth]) -> str:
    status = last_cycle.get("status")
    if status:
        return status
    if health and health.details:
        health_cycle = health.details.get("last_cycle") or {}
        if health_cycle.get("cycle_run_id") == last_cycle.get("cycle_run_id"):
            status = health_cycle.get("status")
            if status:
                return status
    if last_cycle.get("errors"):
        return "partial"
    if last_cycle.get("alpaca_configured") is False:
        return "ok"
    if last_cycle.get("account_synced"):
        return "ok"
    return "partial"


def _export_latest_order_attempt(session: Session, config: dict) -> dict[str, Any]:
    from app.services.paper_order_proof_service import PaperOrderProofService

    proof = PaperOrderProofService(session, config).summary()
    return {"status": "ok", "latest_order_attempt": proof.get("latest_order_attempt")}


def _export_alpaca_rejections(session: Session) -> dict[str, Any]:
    rows = list(
        session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.status == "paper_order_rejected")
            .order_by(ExecutionLog.created_at.desc())
            .limit(30)
        ).all()
    )
    out = []
    for row in rows:
        gf = row.gates_failed_json if isinstance(row.gates_failed_json, dict) else {}
        out.append(
            {
                "cycle_run_id": row.cycle_run_id,
                "symbol": row.symbol,
                "side": row.side,
                "reject_reason": row.reject_reason,
                "requested_qty": row.requested_qty,
                "limit_price": row.limit_price,
                "broker_order_id": row.broker_order_id,
                "broker_client_order_id": row.broker_client_order_id,
                "http_status": gf.get("http_status"),
                "alpaca_code": gf.get("alpaca_code"),
                "alpaca_message": gf.get("alpaca_message") or gf.get("broker_message"),
                "broker_error_body": gf.get("broker_error_body"),
                "request_payload": gf.get("request_payload"),
                "submitted_to_broker": gf.get("submitted_to_broker", True),
                "created_at": _iso(row.created_at),
            }
        )
    return {"status": "ok", "rejections": out, "count": len(out)}


def _export_alpaca_order_payloads(session: Session) -> dict[str, Any]:
    rows = list(
        session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.status.in_(("paper_order_rejected", "paper_order_submitted", "paper_order_filled")))
            .order_by(ExecutionLog.created_at.desc())
            .limit(30)
        ).all()
    )
    payloads = []
    for row in rows:
        gf = row.gates_failed_json if isinstance(row.gates_failed_json, dict) else {}
        gp = row.gates_passed_json if isinstance(row.gates_passed_json, dict) else {}
        payloads.append(
            {
                "cycle_run_id": row.cycle_run_id,
                "symbol": row.symbol,
                "status": row.status,
                "request_payload": gf.get("request_payload")
                or (gp.get("crypto_validator") or {}).get("normalized_payload"),
            }
        )
    return {"status": "ok", "payloads": payloads}


def _export_strategy_test_results(session: Session, config: dict) -> dict[str, Any]:
    from app.services.research_backtest_engine import ResearchBacktestEngine

    engine = ResearchBacktestEngine(session, config)
    runs = engine.list_runs(20)
    return {"status": "ok", "runs": runs, "count": len(runs)}


def _export_memory_tier(session: Session, *, tier: str) -> dict[str, Any]:
    from sqlmodel import select

    from app.database import LessonNode
    from app.services.memory_policy_service import MemoryPolicyService

    policy = MemoryPolicyService(session)
    epoch_id = (policy.epoch or {}).get("reset_epoch_id")
    rows = list(session.exec(select(LessonNode).order_by(LessonNode.created_at.desc()).limit(500)).all())
    filtered = []
    for r in rows:
        if not policy._epoch_match(r, epoch_id):
            continue
        mt = r.memory_type or ""
        if tier == "raw_event" and mt == "raw_event":
            filtered.append(r)
        elif tier == "validated" and mt not in ("raw_event", "pending", "consolidated_memory"):
            filtered.append(r)
        elif tier == "consolidated_memory" and (mt == "consolidated_memory" or (r.occurrence_count or 0) > 1):
            filtered.append(r)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "reset_epoch_id": epoch_id,
        "tier": tier,
        "count": len(filtered),
        "memories": [
            {
                "id": r.id,
                "title": r.title,
                "summary": r.summary,
                "symbol": r.symbol,
                "memory_type": r.memory_type,
                "occurrence_count": r.occurrence_count or 1,
                "status": r.status,
            }
            for r in filtered[:100]
        ],
    }


def _export_memory_quality_report(session: Session) -> dict[str, Any]:
    from app.services.memory_policy_service import MemoryPolicyService

    policy = MemoryPolicyService(session)
    st = policy.status()
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "schema_version": 1,
        **st,
        "quality_gates": {
            "raw_events_not_hive_mind": True,
            "gemini_pending_not_validated": True,
            "consolidation_window_hours": 24,
            "merge_blockers_enabled": True,
        },
    }


def _research_bundle_meta(
    session: Session,
    *,
    db_counts: dict,
    last_cycle: dict,
    cycle_status: str,
    latest_cycle_errors: list,
    historical_alpaca_errors: list,
) -> dict[str, Any]:
    import os

    from app.services.nuke_epoch_service import get_latest_reset_epoch

    epoch = get_latest_reset_epoch(session)
    sched = {}
    try:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        sched = AutonomousPaperScheduler(session).status()
    except Exception:
        pass
    return {
        "schema_version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "architecture": "caged_hive_quant_research_v1",
        "reset_epoch_id": (epoch or {}).get("reset_epoch_id"),
        "bot_run_id": os.environ.get("RAILWAY_DEPLOYMENT_ID") or os.environ.get("RAILWAY_REPLICA_ID"),
        "backend_commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev")[:12],
        "frontend_commit": os.environ.get("FRONTEND_GIT_COMMIT_SHA", "unknown")[:12],
        "latest_tick_id": sched.get("last_tick_at"),
        "latest_cycle_id": last_cycle.get("cycle_run_id") if last_cycle else None,
        "database_fingerprint": database_fingerprint(),
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "db_counts": db_counts,
        "last_cycle_run_id": last_cycle.get("cycle_run_id") if last_cycle else None,
        "last_cycle_status": cycle_status,
        "latest_cycle_error_count": len(latest_cycle_errors),
        "historical_error_count": len(historical_alpaca_errors),
        "gemini_can_trade": False,
        "live_trading_enabled": False,
    }


def export_diagnostic_bundle(session: Session) -> dict[str, Any]:
    session.commit()
    session.expire_all()

    config_mgr = ConfigManager(session)
    health = session.get(SystemHealth, 1)

    activity_rows = list(session.exec(select(ActivityLog).order_by(ActivityLog.created_at.desc())).all())
    strategy_rows = list(session.exec(select(StrategyState)).all())
    signal_rows = list(session.exec(select(StrategySignal).order_by(StrategySignal.created_at.desc())).all())
    candidate_rows = list(session.exec(select(SymbolCandidate)).all())
    blocked_rows = list(session.exec(select(BlockedTrade).order_by(BlockedTrade.created_at.desc())).all())
    risk_rows = list(
        session.exec(
            select(RiskEvent)
            .where(RiskEvent.event_type == "trade_blocked")
            .order_by(RiskEvent.created_at.desc())
        ).all()
    )
    broker_error_rows = list(session.exec(select(BrokerError).order_by(BrokerError.created_at.desc())).all())
    portfolio_rows = list(session.exec(select(PortfolioDecision).order_by(PortfolioDecision.created_at.desc())).all())
    execution_rows = list(session.exec(select(ExecutionLog).order_by(ExecutionLog.created_at.desc())).all())
    kill_rows = list(session.exec(select(KillSwitchEvent).order_by(KillSwitchEvent.created_at.desc())).all())

    db_counts = count_cycle_rows(session)
    cycle_log = latest_cycle_end(session)
    last_cycle = cycle_log.details if cycle_log and cycle_log.details else None
    if last_cycle is None and health and health.details:
        last_cycle = health.details.get("last_cycle")

    latest_cycle_id = last_cycle.get("cycle_run_id") if last_cycle else None
    cycle_started = last_cycle.get("started_at") if last_cycle else None

    # Scheduler/tick attribution for "latest" classification.
    scheduler_enabled_at = None
    try:
        row = (
            session.exec(
                select(SettingsActionAudit)
                .where(SettingsActionAudit.action == "scheduler_enable")
                .order_by(SettingsActionAudit.created_at.desc())
            ).first()
        )
        scheduler_enabled_at = _iso(row.created_at) if row and row.created_at else None
    except Exception:
        scheduler_enabled_at = None
    scheduler_last_tick_at = None
    try:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        scheduler_last_tick_at = AutonomousPaperScheduler(session, cfg_brain).status().get("last_tick_at")
    except Exception:
        scheduler_last_tick_at = None
    if latest_cycle_id:
        signal_rows = _filter_cycle_rows(
            signal_rows,
            latest_cycle_id,
            cycle_started,
            cycle_id_getter=lambda r: r.cycle_run_id,
        )
        blocked_rows = _filter_cycle_rows(
            blocked_rows,
            latest_cycle_id,
            cycle_started,
            cycle_id_getter=lambda r: r.cycle_run_id,
        )
        risk_rows = _filter_cycle_rows(
            risk_rows,
            latest_cycle_id,
            cycle_started,
            cycle_id_getter=_risk_event_cycle_id,
        )
        portfolio_rows = _filter_cycle_rows(
            portfolio_rows,
            latest_cycle_id,
            cycle_started,
            cycle_id_getter=lambda r: r.cycle_run_id,
        )
        execution_rows = _filter_cycle_rows(
            execution_rows,
            latest_cycle_id,
            cycle_started,
            cycle_id_getter=lambda r: r.cycle_run_id,
        )
        db_counts = count_cycle_rows(session, latest_cycle_id)

    # Materialize rows before build_dashboard() — its commit expires ORM instances.
    activity_data = _materialize(activity_rows, serialize_activity)
    signal_data = _materialize(signal_rows, serialize_strategy_signal)
    blocked_data = _materialize(blocked_rows, serialize_blocked_trade)
    risk_data = _materialize(risk_rows, serialize_risk_event)
    portfolio_data = _materialize(portfolio_rows, serialize_portfolio_decision)
    execution_data = _materialize(execution_rows, serialize_execution_log)
    broker_errors_all = [
        serialize_broker_error(
            row,
            latest_cycle_id=latest_cycle_id,
            cycle_started=cycle_started,
            scheduler_enabled_at=scheduler_enabled_at,
            scheduler_last_tick_at=scheduler_last_tick_at,
        )
        for row in broker_error_rows
    ]
    latest_cycle_errors = [e for e in broker_errors_all if e.get("is_latest_cycle") and not e.get("historical")]
    historical_alpaca_errors = [e for e in broker_errors_all if e.get("historical")]

    cycle_status = _resolve_cycle_status(last_cycle, health) if last_cycle else "never_run"

    summary_lines = [
        "# Caged Hive Quant — System Summary",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        f"Database fingerprint: {database_fingerprint()}",
        "",
        "## Connection Status",
        f"- Alpaca: {'connected' if health and health.alpaca_connected else 'not connected'}",
        f"- Gemini: {'configured' if health and health.gemini_configured else 'not configured'}",
        f"- Database: {'connected' if health and health.database_connected else 'unavailable'}",
        f"- Kill Switch: {'ACTIVE' if health and health.kill_switch_active else 'off'}",
        "",
        "## Backend Data Counts (from DB)",
        f"- activity_logs: {len(activity_rows)}",
        f"- strategy_states: {len(strategy_rows)}",
        f"- strategy_signals: {len(signal_data)}",
        f"- symbol_candidates: {len(candidate_rows)}",
        f"- blocked_trades: {len(blocked_data)}",
        f"- risk_events (trade_blocked): {len(risk_data)}",
        "",
        "## Last Cycle",
    ]

    if last_cycle:
        summary_lines.extend(
            [
                f"- Cycle run id: {last_cycle.get('cycle_run_id', 'unknown')}",
                f"- Timestamp: {last_cycle.get('ended_at') or last_cycle.get('started_at', 'unknown')}",
                f"- Status: {cycle_status}",
                f"- Session mode: {(last_cycle.get('session') or {}).get('mode', 'unknown')}",
                f"- Radar count: {last_cycle.get('radar_count', 0)}",
                f"- Signals generated: {last_cycle.get('signals_generated', 0)}",
                f"- Signals created: {last_cycle.get('signals_created', 0)}",
                f"- Signals evaluated: {last_cycle.get('signals_evaluated', 0)}",
                f"- Blocked: {last_cycle.get('blocked', 0)}",
                f"- Risk approved: {last_cycle.get('risk_approved', 0)}",
                f"- Portfolio deferred: {last_cycle.get('portfolio_deferred', 0)}",
                f"- Selected for execution: {last_cycle.get('selected_for_execution', 0)}",
                f"- Approved (incl. no-order): {last_cycle.get('approved', 0)}",
                f"- Orders submitted: {last_cycle.get('orders_submitted', 0)}",
                f"- Errors: {', '.join(last_cycle.get('errors') or []) or 'none'}",
                "",
                "## Persistence Check",
                f"- DB strategy_signals: {db_counts['strategy_signals']}",
                f"- DB blocked_trades: {db_counts['blocked_trades']}",
                f"- DB risk_events: {db_counts['risk_events']}",
                f"- Match signals: {db_counts['strategy_signals'] == last_cycle.get('signals_created', 0)}",
                f"- Match blocked: {db_counts['blocked_trades'] == last_cycle.get('blocked', 0)}",
                f"- Match risk events: {db_counts['risk_events'] == last_cycle.get('blocked', 0)}",
                "",
                "## Strategy States (last cycle)",
            ]
        )
        for st in last_cycle.get("strategy_states") or []:
            summary_lines.append(f"- {st.get('strategy')}: {st.get('status')} — {st.get('reason')}")
    else:
        summary_lines.append("- Status: never run")
        summary_lines.append("- Run POST /api/cycle/run to populate backend data")

    if strategy_rows:
        summary_lines.extend(["", "## Strategy States (DB)"])
        for st in strategy_rows:
            summary_lines.append(f"- {st.strategy}: {st.status} — {st.status_reason or ''}")

    summary_lines.extend(
        [
            "",
            "## Core Principle",
            "Rules trade fast. AI learns slowly. Risk engine blocks danger.",
            "Paper trading only. No live trading. No fake data.",
        ]
    )

    from app.services.safe_responses import lightweight_dashboard_snapshot
    from app.services.attention_radar_service import AttentionRadarService
    from app.services.cooldown_service import CooldownService
    from app.services.kill_switch_service import KillSwitchService
    from app.services.promotion_service import PromotionService
    from app.services.paper_execution_service import PaperExecutionService
    from app.services.order_reconciliation import reconciliation_status

    dashboard = lightweight_dashboard_snapshot(session)
    attention = AttentionRadarService(session).scan(limit=25)
    config = config_mgr.get_current()
    cooldowns = CooldownService(session, config).list_all()
    kill_status = KillSwitchService(session, config).status()
    promotion = PromotionService(session, config).status()
    execution_policy = PaperExecutionService(session).status()
    from app.services.alpaca_adapter import AlpacaAdapter

    try:
        recon = reconciliation_status(session, AlpacaAdapter(session))
    except Exception as recon_exc:
        recon = {"status": "degraded", "error": type(recon_exc).__name__, "message": str(recon_exc)[:200]}
    from app.services.lesson_memory_service import LessonMemoryService

    from app.services.nuke_epoch_service import filter_lessons_post_nuke, filter_rows_post_nuke, nuke_status_export

    lesson_rows = filter_lessons_post_nuke(
        session,
        list(session.exec(select(LessonNode).order_by(LessonNode.last_seen_at.desc())).all()),
    )
    edge_rows = list(session.exec(select(MemoryEdge)).all())
    evidence_rows = list(session.exec(select(MemoryEvidence)).all())
    memory_graph = LessonMemoryService(session, config).build_graph()

    def _lesson_row(r: LessonNode) -> dict:
        return {
            "id": r.id,
            "category": getattr(r, "category", None),
            "memory_type": r.memory_type,
            "title": r.title,
            "summary": r.summary,
            "detailed_lesson": r.detailed_lesson,
            "severity": r.severity,
            "confidence": r.confidence,
            "source": r.source,
            "status": getattr(r, "status", "active"),
            "visible_in_graph": getattr(r, "visible_in_graph", True),
            "visible_to_ai": getattr(r, "visible_to_ai", True),
            "can_influence_ranking": getattr(r, "can_influence_ranking", True),
            "human_review_status": getattr(r, "human_review_status", "pending"),
            "cycle_run_id": r.cycle_run_id,
            "signal_id": r.signal_id,
            "broker_order_id": r.broker_order_id,
            "symbol": r.symbol,
            "strategy_name": r.strategy_name,
            "evidence_json": r.evidence_json,
            "proposed_action": r.proposed_action,
            "action_status": r.action_status,
            "occurrence_count": r.occurrence_count,
            "archive_reason": getattr(r, "archive_reason", None),
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }

    from app.services.decisions_service import latest_summary
    from app.services.positions_tab_service import (
        current_positions,
        orders_history,
        position_states,
        trades_history,
    )
    from app.services.memory_categories import CATEGORY_SYSTEM, CATEGORY_TRADING

    decisions_latest = latest_summary(session, "latest")
    cid = decisions_latest.get("cycle_run_id")
    trading_rows = [r for r in lesson_rows if getattr(r, "category", "") == CATEGORY_TRADING]
    system_rows = [r for r in lesson_rows if getattr(r, "category", "") == CATEGORY_SYSTEM]
    archived_rows = [r for r in lesson_rows if getattr(r, "status", "") in ("archived", "deleted")]

    ai_reviews_all = [_serialize_row(r) for r in session.exec(select(AIReview)).all()]
    latest_ai = ai_reviews_all[-1] if ai_reviews_all else None
    ai_bundle = {
        "ai_reviews.json": ai_reviews_all,
        "ai_usage_logs.json": [_serialize_row(r) for r in session.exec(select(AIUsageLog)).all()],
        "ai_memories.json": [
            _serialize_row(r)
            for r in filter_rows_post_nuke(session, list(session.exec(select(AIMemory)).all()))
        ],
        "ai_config_proposals.json": [_serialize_row(r) for r in session.exec(select(AIConfigProposal)).all()],
        "ai_strategy_notes.json": [],
        "ai_review_freshness.json": {
            "latest_cycle_run_id": cid,
            "latest_review": latest_ai,
        },
        "ai_budget_status.json": AIBudgetGuard(session).status(),
        "ai_prompt_summaries.json": [
            {
                "cycle_run_id": (r.get("payload") or {}).get("cycle_run_id"),
                "model": (r.get("payload") or {}).get("model"),
                "status": r.get("review_status"),
                "summary": (r.get("summary") or "")[:500],
            }
            for r in ai_reviews_all[-10:]
        ],
        "ai_errors.json": [r for r in ai_reviews_all if (r.get("review_status") or "") != "success"],
        "ai_decision_context_latest.json": decisions_latest if cid else {"status": "no_cycle"},
    }

    from app.services.frontend_api_contract import (
        FRONTEND_API_CONTRACT,
        UI_PANEL_DATA_SOURCES,
        build_frontend_endpoint_status,
    )
    from app.database import (
        HistoricalDataCoverage,
        HistoricalDataError,
        ParameterSetResult,
        ResearchBacktestRun,
        StrategyCandidate,
        StrategyDefinition,
        WalkForwardResult,
    )
    from app.services.memory_categories import RESEARCH_MEMORY_TYPES

    try:
        frontend_endpoint_status = build_frontend_endpoint_status(session)
    except Exception as exc:
        frontend_endpoint_status = [{"error": f"probe_failed: {exc}"}]

    research_rows = list(session.exec(select(ResearchBacktestRun)).all())
    research_bundle = {
        "historical_data_coverage.json": [
            _serialize_row(r) for r in session.exec(select(HistoricalDataCoverage)).all()
        ],
        "backtest_runs.json": [_serialize_row(r) for r in research_rows],
        "backtest_results.json": [_serialize_row(r) for r in session.exec(select(BacktestResult)).all()],
        "parameter_sets.json": [_serialize_row(r) for r in session.exec(select(ParameterSetResult)).all()],
        "strategy_candidates.json": [_serialize_row(r) for r in session.exec(select(StrategyCandidate)).all()],
        "rejected_strategies.json": [
            _serialize_row(r) for r in session.exec(select(StrategyCandidate).where(StrategyCandidate.status == "rejected")).all()
        ],
        "walk_forward_results.json": [_serialize_row(r) for r in session.exec(select(WalkForwardResult)).all()],
        "strategy_leaderboard.json": [],
        "research_memories.json": [
            _lesson_row(r)
            for r in lesson_rows
            if getattr(r, "memory_type", "") in RESEARCH_MEMORY_TYPES
        ],
        "research_errors.json": [_serialize_row(r) for r in session.exec(select(HistoricalDataError)).all()],
        "strategy_definitions.json": [_serialize_row(r) for r in session.exec(select(StrategyDefinition)).all()],
    }
    try:
        from app.services.research_lab_service import ResearchLabService

        research_bundle["strategy_leaderboard.json"] = ResearchLabService(session).leaderboard()
    except Exception:
        pass

    strategy_registry_exports: dict = {}
    export_errors: list[dict[str, Any]] = []
    try:
        from app.services.export_safe import safe_export_section
        from app.database import (
            StrategyAllocation,
            StrategyConflict,
            StrategyEligibilityWindow,
            StrategyLifecycleEvent,
            StrategyMemoryLink,
            StrategyRegistry,
            StrategyRejection,
            StrategyRetirement,
            StrategyScorecard,
            StrategyValidationResult,
            SystemValidationAudit,
        )
        from app.services.strategy_registry_service import StrategyRegistryService

        from app.database import PaperExperimentConfig, PaperExperimentDecision, PaperExperimentOutcome
        from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
        from app.services.strategy_registry_export import (
            ensure_strategy_rejection_records,
            list_active_registry,
            list_rejected_registry,
            list_research_only_registry,
            memory_validation_mismatches,
        )
        from app.services.lesson_memory_service import LessonMemoryService

        reg_svc = StrategyRegistryService(session)
        snap = reg_svc.tab_snapshot()
        pl = AggressivePaperLearningService(session)
        elig = pl.scan_experiment_eligibility()
        cfg_brain = ConfigManager(session).get_current()
        from app.services.hive_brain_graph_service import HiveBrainGraphService
        from app.services.training_execution_service import TrainingExecutionService
        from app.services.open_position_review_service import OpenPositionReviewService
        from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector
        from app.services.memory_consolidation_service import MemoryConsolidationService
        from app.services.ai_learning_memory_service import AILearningMemoryService
        from app.services.live_lock_tripwire import live_lock_tripwire_status
        from app.services.memory_policy import load_memory_policy

        from app.services.position_hold_time_service import audit_all_open_positions
        from app.services.hardcoded_symbol_scan import scan_repository as hardcoded_scan

        brain_graph = HiveBrainGraphService(session, cfg_brain).build_full()
        hold_audit = audit_all_open_positions(session)
        hc_scan = hardcoded_scan()
        from app.services.hive_brain_node_service import HiveBrainNodeService
        from app.services.broker_reconciliation_service import BrokerReconciliationService

        brain_node_svc = HiveBrainNodeService(session, cfg_brain)
        sample_node = brain_node_svc.get_node("position-DOGEUSD")
        if sample_node.get("status") != "ok":
            sample_node = None
            for n in brain_graph.get("nodes", []):
                if n.get("type") in ("position", "historical", "anomaly") and str(n.get("id", "")).startswith(
                    "position-"
                ):
                    sample_node = brain_node_svc.get_node(n["id"])
                    if sample_node.get("status") == "ok":
                        break
        if sample_node and sample_node.get("status") == "ok":
            from app.database import OrderRecord

            recon_svc = BrokerReconciliationService(session, cfg_brain)
            doge_keys = ("DOGE", "DOGEUSD", "DOGE/USD")
            sample_node["linked_orders"] = [
                _serialize_row(o)
                for o in session.exec(select(OrderRecord)).all()
                if any(k in (o.symbol or "").upper() for k in doge_keys)
            ]
            sample_node["linked_rejects"] = [
                r for r in recon_svc.broker_rejects(20) if "DOGE" in (r.get("symbol") or "").upper()
            ]
        graph = brain_graph
        cons_svc = MemoryConsolidationService(session, cfg_brain)
        ai_svc = AILearningMemoryService(session, cfg_brain)
        train_svc = TrainingExecutionService(session, cfg_brain)
        from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop
        from app.services.fast_training_exit_only_service import FastTrainingExitOnlyService
        from app.services.technical_candle_analysis_service import TechnicalCandleAnalysisService
        from app.services.strategy_import_service import StrategyImportService
        from app.services.fast_training_exit_diagnostics import build_exit_diagnostic_exports
        from app.services.broker_reconciliation_service import BrokerReconciliationService

        recon_exports = BrokerReconciliationService(session, cfg_brain).build_diagnostic_exports()
        ft_loop = FastCryptoTrainingLoop(session, cfg_brain)
        from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
        from app.services.confidence_engine import ConfidenceEngine
        from app.services.account_pair_eligibility_service import AccountPairEligibilityService
        from app.services.strategy_proposal_service import StrategyProposalService
        from app.services.promotion_readiness_service import PromotionReadinessService
        from app.services.research_lab_service import ResearchLabService

        apl_svc = AutonomousPaperLearningService(session, cfg_brain)
        apl_sched = AutonomousPaperScheduler(session, cfg_brain)
        conf_eng = ConfidenceEngine(session, cfg_brain)
        elig_svc = AccountPairEligibilityService(session, cfg_brain)
        prop_svc = StrategyProposalService(session, cfg_brain)
        promo_svc = PromotionReadinessService(session, cfg_brain)
        exit_only_svc = FastTrainingExitOnlyService(session, cfg_brain)
        exit_diag = build_exit_diagnostic_exports(session, cfg_brain)
        candle_svc = TechnicalCandleAnalysisService(session, cfg_brain)
        import_svc = StrategyImportService(session, cfg_brain)
        pos_review = OpenPositionReviewService(session, cfg_brain).review_all()
        meme_recent = MemeVolatilitySpikeDetector(session, cfg_brain).recent(15)
        from app.services.strategy_memory_validation_service import StrategyMemoryValidationService

        scheduler_enabled_at = None
        scheduler_last_tick_at = None
        try:
            row = (
                session.exec(
                    select(SettingsActionAudit)
                    .where(SettingsActionAudit.action == "scheduler_enable")
                    .order_by(SettingsActionAudit.created_at.desc())
                ).first()
            )
            scheduler_enabled_at = _iso(row.created_at) if row and row.created_at else None
        except Exception:
            scheduler_enabled_at = None
        try:
            scheduler_last_tick_at = (apl_sched.status() or {}).get("last_tick_at")
        except Exception:
            scheduler_last_tick_at = None

        StrategyMemoryValidationService(session, ConfigManager(session).get_current()).sync_link_status_to_lessons()
        mph = memory_validation_mismatches(session)
        strategy_registry_exports = {
            "strategy_registry.json": [_serialize_row(r) for r in session.exec(select(StrategyRegistry)).all()],
            "all_strategies.json": reg_svc.list_registry(),
            "active_strategies.json": list_active_registry(session),
            "rejected_strategies.json": list_rejected_registry(session),
            "research_only_strategies.json": list_research_only_registry(session),
            "experiment_eligible_strategies.json": elig.get("eligible", []),
            "experiment_blocked_strategies.json": elig.get("blocked", []),
            "strategy_lifecycle_events.json": [_serialize_row(r) for r in session.exec(select(StrategyLifecycleEvent)).all()],
            "strategy_scorecards.json": [_serialize_row(r) for r in session.exec(select(StrategyScorecard)).all()],
            "strategy_validation_results.json": [_serialize_row(r) for r in session.exec(select(StrategyValidationResult)).all()],
            "strategy_promotion_audit.json": [_serialize_row(r) for r in session.exec(select(SystemValidationAudit)).all()],
            "strategy_rejections.json": ensure_strategy_rejection_records(session),
            "strategy_retirements.json": [_serialize_row(r) for r in session.exec(select(StrategyRetirement)).all()],
            "strategy_conflicts.json": [_serialize_row(r) for r in session.exec(select(StrategyConflict)).all()],
            "strategy_allocations.json": [_serialize_row(r) for r in session.exec(select(StrategyAllocation)).all()],
            "strategy_memory_links.json": [_serialize_row(r) for r in session.exec(select(StrategyMemoryLink)).all()],
            "strategy_eligibility_windows.json": [_serialize_row(r) for r in session.exec(select(StrategyEligibilityWindow)).all()],
            "paper_candidates.json": reg_svc.list_registry(stage="paper_candidate"),
            "strategy_tab_snapshot.json": snap,
            "paper_learning_status.json": safe_export_section(
                "paper_learning_status.json",
                lambda: _paper_learning_status_export(session, cfg_brain, apl_svc, apl_sched),
                export_errors,
            ),
            "autonomous_learning_scheduler.json": safe_export_section(
                "autonomous_learning_scheduler.json", apl_sched.status, export_errors
            ),
            "confidence_level.json": safe_export_section(
                "confidence_level.json",
                lambda: __import__(
                    "app.services.safe_responses", fromlist=["safe_confidence_summary"]
                ).safe_confidence_summary(session, cfg_brain),
                export_errors,
            ),
            "strategy_confidence.json": safe_export_section(
                "strategy_confidence.json", conf_eng.by_strategy, export_errors
            ),
            "symbol_confidence.json": safe_export_section(
                "symbol_confidence.json", conf_eng.by_symbol, export_errors
            ),
            "account_pair_eligibility.json": safe_export_section(
                "account_pair_eligibility.json",
                lambda: __import__(
                    "app.services.safe_responses", fromlist=["safe_account_pair_eligibility"]
                ).safe_account_pair_eligibility(session, cfg_brain),
                export_errors,
            ),
            "backtest_lab_results.json": safe_export_section(
                "backtest_lab_results.json",
                lambda: ResearchLabService(session).propose_backtests_from_memory(limit=10),
                export_errors,
            ),
            "strategy_proposals.json": safe_export_section(
                "strategy_proposals.json", lambda: prop_svc.list_proposals(limit=30), export_errors
            ),
            "promotion_readiness.json": safe_export_section(
                "promotion_readiness.json", promo_svc.checklist, export_errors
            ),
            "capital_allocator_plan.json": safe_export_section(
                "capital_allocator_plan.json",
                lambda: __import__(
                    "app.services.capital_allocator", fromlist=["CapitalAllocatorService"]
                ).CapitalAllocatorService(session, cfg_brain).build_plan(),
                export_errors,
            ),
            "capital_allocator_settings.json": safe_export_section(
                "capital_allocator_settings.json",
                lambda: __import__(
                    "app.services.capital_allocator", fromlist=["CapitalAllocatorService"]
                ).CapitalAllocatorService(session, cfg_brain).settings(),
                export_errors,
            ),
            "capital_allocator_decisions.json": safe_export_section(
                "capital_allocator_decisions.json",
                lambda: {
                    "decisions": __import__(
                        "app.services.capital_allocator", fromlist=["CapitalAllocatorService"]
                    ).CapitalAllocatorService(session, cfg_brain).recent_decisions(),
                },
                export_errors,
            ),
            "capital_allocator_errors.json": safe_export_section(
                "capital_allocator_errors.json",
                lambda: {
                    "status": __import__(
                        "app.services.capital_allocator", fromlist=["CapitalAllocatorService"]
                    )
                    .CapitalAllocatorService(session, cfg_brain)
                    .status_summary()
                    .get("status"),
                    "warnings": __import__(
                        "app.services.capital_allocator", fromlist=["CapitalAllocatorService"]
                    )
                    .CapitalAllocatorService(session, cfg_brain)
                    .build_plan()
                    .get("degraded_warnings", []),
                },
                export_errors,
            ),
            "paper_learning_capacity.json": safe_export_section(
                "paper_learning_capacity.json",
                lambda: __import__(
                    "app.services.autonomous_paper_learning_service",
                    fromlist=["AutonomousPaperLearningService"],
                )
                .AutonomousPaperLearningService(session, cfg_brain)
                ._learning_capacity(),
                export_errors,
            ),
            "paper_learning_scheduler.json": safe_export_section(
                "paper_learning_scheduler.json", apl_sched.status, export_errors
            ),
            "allocator_confidence.json": safe_export_section(
                "allocator_confidence.json",
                lambda: __import__(
                    "app.services.confidence_engine", fromlist=["ConfidenceEngine"]
                )
                .ConfidenceEngine(session, cfg_brain)
                ._allocator_confidence_score(),
                export_errors,
            ),
            "latest_tick_execution_logs.json": safe_export_section(
                "latest_tick_execution_logs.json",
                lambda: __import__(
                    "app.services.execution_logs_query_service",
                    fromlist=["list_execution_logs"],
                ).list_execution_logs(session, scope="latest_tick", limit=100),
                export_errors,
            ),
            "since_scheduler_enable_execution_logs.json": safe_export_section(
                "since_scheduler_enable_execution_logs.json",
                lambda: __import__(
                    "app.services.execution_logs_query_service",
                    fromlist=["list_execution_logs"],
                ).list_execution_logs(session, scope="since_scheduler_enable", limit=200),
                export_errors,
            ),
            "historical_execution_logs.json": safe_export_section(
                "historical_execution_logs.json",
                lambda: __import__(
                    "app.services.execution_logs_query_service",
                    fromlist=["list_execution_logs"],
                ).list_execution_logs(session, scope="historical", limit=200),
                export_errors,
            ),
            "env_pause_status.json": safe_export_section(
                "env_pause_status.json",
                lambda: __import__(
                    "app.services.env_pause_service", fromlist=["env_pause_status"]
                ).env_pause_status(),
                export_errors,
            ),
            "live_lock_status.json": safe_export_section(
                "live_lock_status.json",
                lambda: __import__(
                    "app.services.live_lock_tripwire", fromlist=["live_lock_tripwire_status"]
                ).live_lock_tripwire_status(cfg_brain),
                export_errors,
            ),
            "mission_control_status.json": safe_export_section(
                "mission_control_status.json",
                lambda: __import__(
                    "app.services.mission_control_service", fromlist=["mission_control_status"]
                ).mission_control_status(session, cfg_brain),
                export_errors,
            ),
            "push_pull_latest_tick.json": safe_export_section(
                "push_pull_latest_tick.json",
                lambda: __import__(
                    "app.services.push_pull_engine_service", fromlist=["PushPullEngineService"]
                ).PushPullEngineService(session, cfg_brain).latest_tick(),
                export_errors,
            ),
            "push_pull_candidates.json": safe_export_section(
                "push_pull_candidates.json",
                lambda: __import__(
                    "app.services.push_pull_engine_service", fromlist=["PushPullEngineService"]
                ).PushPullEngineService(session, cfg_brain).decisions(100),
                export_errors,
            ),
            "push_pull_decisions.json": safe_export_section(
                "push_pull_decisions.json",
                lambda: __import__(
                    "app.services.push_pull_engine_service", fromlist=["PushPullEngineService"]
                ).PushPullEngineService(session, cfg_brain).decisions(200),
                export_errors,
            ),
            "push_pull_lessons.json": safe_export_section(
                "push_pull_lessons.json",
                lambda: __import__(
                    "app.services.push_pull_engine_service", fromlist=["PushPullEngineService"]
                ).PushPullEngineService(session, cfg_brain).lessons(100),
                export_errors,
            ),
            "ai_memory.json": safe_export_section(
                "ai_memory.json",
                lambda: __import__(
                    "app.services.ai_manager_service", fromlist=["AIManagerService"]
                ).AIManagerService(session, cfg_brain).memories(100),
                export_errors,
            ),
            "ai_memory_raw_events.json": safe_export_section(
                "ai_memory_raw_events.json",
                lambda: _export_memory_tier(session, tier="raw_event"),
                export_errors,
            ),
            "ai_memory_validated.json": safe_export_section(
                "ai_memory_validated.json",
                lambda: _export_memory_tier(session, tier="validated"),
                export_errors,
            ),
            "ai_memory_consolidated.json": safe_export_section(
                "ai_memory_consolidated.json",
                lambda: _export_memory_tier(session, tier="consolidated_memory"),
                export_errors,
            ),
            "memory_quality_report.json": safe_export_section(
                "memory_quality_report.json",
                lambda: _export_memory_quality_report(session),
                export_errors,
            ),
            "universe_sources.json": safe_export_section(
                "universe_sources.json",
                lambda: __import__(
                    "app.services.universe_sources_service", fromlist=["universe_sources"]
                ).universe_sources(session, cfg_brain),
                export_errors,
            ),
            "ai_strategy_lessons.json": safe_export_section(
                "ai_strategy_lessons.json",
                lambda: __import__(
                    "app.services.ai_manager_service", fromlist=["AIManagerService"]
                ).AIManagerService(session, cfg_brain).lessons(100),
                export_errors,
            ),
            "system_log.json": safe_export_section(
                "system_log.json",
                lambda: __import__(
                    "app.services.reports_hub_service", fromlist=["ReportsHubService"]
                ).ReportsHubService(session, cfg_brain).system_log(200),
                export_errors,
            ),
            "audit_trail.json": safe_export_section(
                "audit_trail.json",
                lambda: __import__(
                    "app.services.reports_hub_service", fromlist=["ReportsHubService"]
                ).ReportsHubService(session, cfg_brain).audit_trail(100),
                export_errors,
            ),
            "paper_experiment_config.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentConfig)).all()],
            "paper_experiment_decisions.json": _annotate_source_window(
                [_serialize_row(r) for r in session.exec(select(PaperExperimentDecision)).all()],
                scheduler_enabled_at=scheduler_enabled_at,
                scheduler_last_tick_at=scheduler_last_tick_at,
            ),
            "paper_experiment_outcomes.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentOutcome)).all()],
            "paper_experiment_memories.json": pl.list_memories(40),
            "memory_graph_clusters.json": graph.get("meta", {}),
            "memory_validation_mismatches.json": mph,
            "memory_pipeline_health.json": mph,
            "system_validation_audit.json": [_serialize_row(r) for r in session.exec(select(SystemValidationAudit)).all()],
            "ai_advisory_history.json": [_serialize_row(r) for r in session.exec(select(AIReview)).all()[:30]],
            "memory_consolidation_status.json": cons_svc.status(),
            "consolidated_memories.json": cons_svc.list_consolidated(50),
            "core_ai_learning_memories.json": ai_svc.list_ai_learning(50),
            "memory_policy_config.json": load_memory_policy(session, cfg_brain),
            "hive_brain_graph.json": brain_graph,
            "hive_brain_clusters.json": brain_graph.get("clusters", []),
            "hive_brain_edges.json": brain_graph.get("edges", [])[:100],
            "hive_brain_legend.json": brain_graph.get("legend", []),
            "hive_brain_shape_legend.json": brain_graph.get("shape_legend", []),
            "hive_brain_layout_meta.json": brain_graph.get("meta", {}),
            "hive_brain_node_details_sample.json": sample_node or {},
            "true_hold_time_audit.json": recon_exports.get("true_hold_time_audit.json", hold_audit),
            "hardcoded_symbol_scan.json": hc_scan,
            "training_cycle_decisions.json": _annotate_source_window(
                pl.list_decisions(),
                scheduler_enabled_at=scheduler_enabled_at,
                scheduler_last_tick_at=scheduler_last_tick_at,
            ),
            "training_execution_queue.json": [
                _serialize_row(r)
                for r in session.exec(select(PaperExperimentDecision).where(PaperExperimentDecision.decision == "approved")).all()
            ],
            "training_orders.json": [_serialize_row(r) for r in session.exec(select(OrderRecord)).all()],
            "training_open_positions.json": train_svc.open_training_positions(),
            "training_exit_monitor.json": train_svc.monitor_exits(),
            "fast_training_status.json": ft_loop.status(),
            "fast_training_loop_status.json": {
                "loop": ft_loop.status(),
                "lease": ft_loop.lease.status(),
                "in_process_loop_supported": False,
            },
            "fast_training_exit_only_status.json": exit_diag.get(
                "fast_training_exit_only_status.json", exit_only_svc.status()
            ),
            "fast_training_exit_decisions.json": exit_diag.get("fast_training_exit_decisions.json", []),
            "fast_training_exit_orders.json": exit_diag.get("fast_training_exit_orders.json", {}),
            "preflight_decisions.json": exit_diag.get("preflight_decisions.json", []),
            "candle_lab_status.json": candle_svc.status(),
            "candle_lab_analysis.json": candle_svc.analyze("DOGE/USD", timeframe="5Min"),
            "strategy_import_status.json": import_svc.status(),
            "imported_strategies.json": import_svc.list_imported(),
            "meme_spike_v2_status.json": MemeVolatilitySpikeDetector(session, cfg_brain).status(),
            "fast_training_decisions.json": _annotate_source_window(
                [
                    _serialize_row(r)
                    for r in session.exec(
                        select(PaperExperimentDecision)
                        .order_by(PaperExperimentDecision.created_at.desc())
                        .limit(50)
                    ).all()
                ],
                scheduler_enabled_at=scheduler_enabled_at,
                scheduler_last_tick_at=scheduler_last_tick_at,
            ),
            "fast_training_orders.json": {
                "orders": [_serialize_row(r) for r in session.exec(select(OrderRecord)).all()],
                "training_blockers": ft_loop.status().get("blockers", []),
                "can_submit_orders": ft_loop.status().get("can_submit_orders", False),
            },
            "training_outcomes.json": exit_diag.get(
                "training_outcomes.json",
                [_serialize_row(r) for r in session.exec(select(PaperExperimentOutcome)).all()],
            ),
            "training_memories.json": train_svc.list_training_memories(40),
            "meme_spike_evaluations.json": meme_recent,
            "meme_spike_recent.json": meme_recent,
            "live_lock_tripwire_status.json": live_lock_tripwire_status(cfg_brain),
            "open_position_reviews.json": recon_exports.get(
                "open_position_reviews.json", exit_diag.get("open_position_reviews.json", pos_review)
            ),
            "broker_position_availability_audit.json": recon_exports.get(
                "broker_position_availability_audit.json", {}
            ),
            "doge_broker_availability_audit.json": recon_exports.get("doge_broker_availability_audit.json", {}),
            "ghost_position_candidates.json": recon_exports.get("ghost_position_candidates.json", []),
            "broker_rejects.json": recon_exports.get("broker_rejects.json", []),
            "exit_only_reconciliation_status.json": recon_exports.get(
                "exit_only_reconciliation_status.json", {}
            ),
            "stale_position_memories.json": [
                _lesson_row(r)
                for r in session.exec(select(LessonNode).where(LessonNode.memory_type == "stale_position_memory").limit(20)).all()
            ],
            "brain_bundle.json": {
                "hive_brain_graph_meta": brain_graph.get("meta"),
                "consolidation": cons_svc.status(),
                "ai_learning_count": len(ai_svc.list_ai_learning(100)),
            },
            "diagnostic_export_errors.json": export_errors,
        }
    except Exception as exc:
        import traceback

        export_errors.append(
            {
                "section": "strategy_registry_block",
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
                "traceback_summary": traceback.format_exc()[-2000:],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        strategy_registry_exports = {
            "strategy_registry_error.json": {"error": str(exc)},
            "diagnostic_export_errors.json": export_errors,
        }
        try:
            from app.services.hive_brain_graph_service import HiveBrainGraphService
            from app.services.position_hold_time_service import audit_all_open_positions
            from app.services.open_position_review_service import OpenPositionReviewService
            from app.services.hardcoded_symbol_scan import scan_repository as hardcoded_scan

            cfg_fb = ConfigManager(session).get_current()
            brain_graph = HiveBrainGraphService(session, cfg_fb).build_full()
            strategy_registry_exports.update(
                {
                    "hive_brain_graph.json": brain_graph,
                    "hive_brain_clusters.json": brain_graph.get("clusters", []),
                    "hive_brain_edges.json": brain_graph.get("edges", [])[:100],
                    "hive_brain_legend.json": brain_graph.get("legend", []),
                    "hive_brain_shape_legend.json": brain_graph.get("shape_legend", []),
                    "hive_brain_layout_meta.json": brain_graph.get("meta", {}),
                    "true_hold_time_audit.json": audit_all_open_positions(session),
                    "hardcoded_symbol_scan.json": {"status": "scan_error", "error": str(exc)},
                    "open_position_reviews.json": OpenPositionReviewService(session, cfg_fb).review_all(),
                }
            )
        except Exception as brain_exc:
            strategy_registry_exports["hive_brain_export_error.json"] = {"error": str(brain_exc)}

    brain_exports = strategy_registry_exports if "hive_brain_graph.json" in strategy_registry_exports else {}

    bundle = {
        "activity.json": activity_data,
        "trades.json": [_serialize_row(r) for r in session.exec(select(TradeRecord)).all()],
        "orders.json": [_serialize_row(r) for r in session.exec(select(OrderRecord)).all()],
        "blocked_trades.json": blocked_data,
        "risk_events.json": risk_data,
        "ai_reviews.json": [_serialize_row(r) for r in session.exec(select(AIReview)).all()],
        "ai_memories.json": [
            _serialize_row(r)
            for r in filter_rows_post_nuke(session, list(session.exec(select(AIMemory)).all()))
        ],
        "ai_config_proposals.json": [_serialize_row(r) for r in session.exec(select(AIConfigProposal)).all()],
        "ai_usage_logs.json": [_serialize_row(r) for r in session.exec(select(AIUsageLog)).all()],
        "positions.json": [_serialize_row(r) for r in session.exec(select(PositionSnapshot)).all()],
        "attention_radar.json": attention,
        "config_history.json": [_serialize_row(r) for r in config_mgr.list_history(100)],
        "current_config.json": config_mgr.get_current(),
        "backtest_results.json": [_serialize_row(r) for r in session.exec(select(BacktestResult)).all()],
        "monte_carlo_results.json": [_serialize_row(r) for r in session.exec(select(MonteCarloResult)).all()],
        "strategy_states.json": [_serialize_row(r) for r in strategy_rows],
        "strategy_signals.json": signal_data,
        "portfolio_decisions.json": portfolio_data,
        "execution_logs.json": execution_data,
        "execution_policy.json": execution_policy,
        "reconciliation_status.json": recon,
        "cooldowns.json": cooldowns,
        "promotion_status.json": promotion,
        "kill_switch_status.json": kill_status,
        "kill_switch_events.json": [_serialize_row(r) for r in kill_rows],
        "symbol_candidates.json": [_serialize_row(r) for r in candidate_rows],
        "alpaca_errors.json": broker_errors_all,
        "latest_cycle_errors.json": latest_cycle_errors,
        "historical_alpaca_errors.json": historical_alpaca_errors,
        "system_health.json": [_serialize_row(health)] if health else [],
        "system_summary.md": "\n".join(summary_lines),
        "dashboard_snapshot.json": dashboard,
        "memory_graph.json": brain_exports.get("hive_brain_graph.json", memory_graph) if brain_exports else memory_graph,
        "ai_memory_graph.json": brain_exports.get("hive_brain_graph.json", memory_graph) if brain_exports else memory_graph,
        "lesson_nodes.json": [_lesson_row(r) for r in lesson_rows],
        "memory_edges.json": [_serialize_row(r) for r in edge_rows],
        "memory_evidence.json": [_serialize_row(r) for r in evidence_rows],
        "symbol_memory.json": [_lesson_row(r) for r in lesson_rows if r.symbol],
        "strategy_memory.json": [_lesson_row(r) for r in lesson_rows if r.strategy_name],
        "execution_memory.json": [_lesson_row(r) for r in trading_rows if "execution" in r.memory_type or "trade" in r.memory_type],
        "risk_memory.json": [_lesson_row(r) for r in trading_rows if "risk" in r.memory_type or "block" in r.memory_type],
        "system_issues.json": [_lesson_row(r) for r in system_rows],
        "archived_memories.json": [_lesson_row(r) for r in archived_rows],
        "operator_notes.json": [_lesson_row(r) for r in lesson_rows if r.memory_type == "operator_note"],
        "decisions_latest.json": decisions_latest,
        "approved_decisions.json": decisions_latest.get("approved", []),
        "blocked_decisions.json": decisions_latest.get("blocked", []),
        "deferred_decisions.json": decisions_latest.get("deferred", []),
        "position_states.json": position_states(session),
        "trades_history.json": trades_history(session),
        "reset_epoch.json": safe_export_section(
            "reset_epoch.json",
            lambda: __import__(
                "app.services.nuke_reset_service", fromlist=["reset_epoch_export"]
            ).reset_epoch_export(session),
            export_errors,
        ),
        "post_nuke_table_counts.json": safe_export_section(
            "post_nuke_table_counts.json",
            lambda: __import__(
                "app.services.nuke_reset_service", fromlist=["post_nuke_table_counts"]
            ).post_nuke_table_counts(session),
            export_errors,
        ),
        "database_bootstrap_status.json": safe_export_section(
            "database_bootstrap_status.json",
            lambda: __import__(
                "app.services.database_bootstrap_service", fromlist=["repair_database_bootstrap"]
            ).repair_database_bootstrap(session),
            export_errors,
        ),
        "missing_tables.json": safe_export_section(
            "missing_tables.json",
            lambda: {
                "missing": __import__(
                    "app.services.database_bootstrap_service", fromlist=["list_missing_tables"]
                ).list_missing_tables()
            },
            export_errors,
        ),
        "nuke_status.json": safe_export_section(
            "nuke_status.json",
            lambda: __import__(
                "app.services.nuke_epoch_service", fromlist=["nuke_status_export"]
            ).nuke_status_export(session),
            export_errors,
        ),
        "universe.json": safe_export_section(
            "universe.json",
            lambda: __import__(
                "app.services.universe_service", fromlist=["universe_status"]
            ).universe_status(session, cfg_brain),
            export_errors,
        ),
        "universe_scan_summary.json": safe_export_section(
            "universe_scan_summary.json",
            lambda: __import__(
                "app.services.universe_service", fromlist=["universe_scan_summary"]
            ).universe_scan_summary(session, cfg_brain),
            export_errors,
        ),
        "bar_freshness.json": safe_export_section(
            "bar_freshness.json",
            lambda: __import__(
                "app.services.market_data_refresh_service", fromlist=["MarketDataRefreshService"]
            ).MarketDataRefreshService(session, cfg_brain).freshness_report(asset_type="crypto"),
            export_errors,
        ),
        "market_data_refresh.json": safe_export_section(
            "market_data_refresh.json",
            lambda: {
                "note": "Run POST /api/market-data/refresh-bars to populate; export is freshness snapshot only.",
                **__import__(
                    "app.services.market_data_refresh_service", fromlist=["MarketDataRefreshService"]
                ).MarketDataRefreshService(session, cfg_brain).freshness_report(asset_type="crypto"),
            },
            export_errors,
        ),
        "strategy_eligibility.json": safe_export_section(
            "strategy_eligibility.json",
            lambda: __import__(
                "app.services.push_pull_strategy_seed", fromlist=["strategy_eligibility_export"]
            ).strategy_eligibility_export(session),
            export_errors,
        ),
        "quote_freshness.json": safe_export_section(
            "quote_freshness.json",
            lambda: __import__(
                "app.routers.market_data", fromlist=["quote_freshness"]
            ).quote_freshness(asset_type="crypto", session=session),
            export_errors,
        ),
        "paper_order_proof.json": safe_export_section(
            "paper_order_proof.json",
            lambda: __import__(
                "app.services.paper_order_proof_service", fromlist=["PaperOrderProofService"]
            ).PaperOrderProofService(session, cfg_brain).summary(),
            export_errors,
        ),
        "latest_order_attempt.json": safe_export_section(
            "latest_order_attempt.json",
            lambda: _export_latest_order_attempt(session, cfg_brain),
            export_errors,
        ),
        "alpaca_rejection_details.json": safe_export_section(
            "alpaca_rejection_details.json",
            lambda: _export_alpaca_rejections(session),
            export_errors,
        ),
        "alpaca_order_payloads.json": safe_export_section(
            "alpaca_order_payloads.json",
            lambda: _export_alpaca_order_payloads(session),
            export_errors,
        ),
        "alpaca_asset_metadata.json": safe_export_section(
            "alpaca_asset_metadata.json",
            lambda: __import__(
                "app.services.alpaca_crypto_assets", fromlist=["fetch_crypto_assets"]
            ).fetch_crypto_assets(force=True),
            export_errors,
        ),
        "autonomous_backtesting_status.json": safe_export_section(
            "autonomous_backtesting_status.json",
            lambda: __import__(
                "app.services.research_lab_service", fromlist=["ResearchLabService"]
            ).ResearchLabService(session).status(),
            export_errors,
        ),
        "backtest_runs.json": safe_export_section(
            "backtest_runs.json",
            lambda: __import__(
                "app.routers.backtesting", fromlist=["backtesting_runs"]
            ).backtesting_runs(50, session),
            export_errors,
        ),
        "strategy_test_results.json": safe_export_section(
            "strategy_test_results.json",
            lambda: _export_strategy_test_results(session, cfg_brain),
            export_errors,
        ),
        "ai_strategy_lessons.json": safe_export_section(
            "ai_strategy_lessons.json",
            lambda: __import__(
                "app.services.ai_manager_service", fromlist=["AIManagerService"]
            ).AIManagerService(session).lessons(40),
            export_errors,
        ),
        "activity_candle_timeline.json": safe_export_section(
            "activity_candle_timeline.json",
            lambda: __import__(
                "app.services.activity_feed_service", fromlist=["activity_feed"]
            ).activity_feed(session, 80),
            export_errors,
        ),
        "strategy_performance.json": safe_export_section(
            "strategy_performance.json",
            lambda: __import__(
                "app.services.strategy_performance_service", fromlist=["StrategyPerformanceService"]
            ).StrategyPerformanceService(session, cfg_brain).summary(),
            export_errors,
        ),
        "broker_responses.json": safe_export_section(
            "broker_responses.json",
            lambda: _export_alpaca_rejections(session),
            export_errors,
        ),
        "order_payloads.json": safe_export_section(
            "order_payloads.json",
            lambda: _export_alpaca_order_payloads(session),
            export_errors,
        ),
        "push_pull_candle_cycles.json": safe_export_section(
            "push_pull_candle_cycles.json",
            lambda: __import__(
                "app.services.push_pull_engine_service", fromlist=["PushPullEngineService"]
            ).PushPullEngineService(session, cfg_brain).latest_tick(),
            export_errors,
        ),
        "gemini_fund_manager_reviews.json": safe_export_section(
            "gemini_fund_manager_reviews.json",
            lambda: {
                "schema_version": 1,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "reviews": _materialize(
                    list(session.exec(select(AIReview).order_by(AIReview.created_at.desc()).limit(30)).all()),
                    lambda r: {
                        "id": r.id,
                        "subject_type": r.subject_type,
                        "decision": r.decision,
                        "summary": r.summary,
                        "payload": r.payload,
                        "created_at": _iso(r.created_at),
                    },
                ),
            },
            export_errors,
        ),
        "ai_lessons.json": safe_export_section(
            "ai_lessons.json",
            lambda: __import__(
                "app.services.ai_manager_service", fromlist=["AIManagerService"]
            ).AIManagerService(session).lessons(40),
            export_errors,
        ),
        "pre_submit_quote_refresh.json": safe_export_section(
            "pre_submit_quote_refresh.json",
            lambda: {
                "note": "Populated on each paper submit attempt via gates_passed/failed on execution logs.",
                "latest_preflight_stale_quote": _latest_stale_quote_log(session),
            },
            export_errors,
        ),
        "push_pull_signals.json": safe_export_section(
            "push_pull_signals.json",
            lambda: __import__(
                "app.services.push_pull_engine_service", fromlist=["PushPullEngineService"]
            ).PushPullEngineService(session, cfg_brain).signals(),
            export_errors,
        ),
        "activity_feed.json": safe_export_section(
            "activity_feed.json",
            lambda: __import__(
                "app.services.activity_feed_service", fromlist=["activity_feed"]
            ).activity_feed(session, 100),
            export_errors,
        ),
        "equity_curve.json": safe_export_section(
            "equity_curve.json",
            lambda: __import__(
                "app.services.performance_service", fromlist=["equity_curve"]
            ).equity_curve(session),
            export_errors,
        ),
        "performance_summary.json": safe_export_section(
            "performance_summary.json",
            lambda: __import__(
                "app.services.performance_service", fromlist=["performance_summary"]
            ).performance_summary(session, cfg_brain),
            export_errors,
        ),
        "confidence_summary.json": safe_export_section(
            "confidence_summary.json",
            lambda: __import__(
                "app.services.confidence_engine", fromlist=["ConfidenceEngine"]
            ).ConfidenceEngine(session, cfg_brain).summary(),
            export_errors,
        ),
        "bundle_meta.json": _research_bundle_meta(
            session,
            db_counts=db_counts,
            last_cycle=last_cycle,
            cycle_status=cycle_status,
            latest_cycle_errors=latest_cycle_errors,
            historical_alpaca_errors=historical_alpaca_errors,
        ),
        "frontend_api_contract.json": FRONTEND_API_CONTRACT,
        "frontend_endpoint_status.json": frontend_endpoint_status,
        "ui_panel_data_sources.json": UI_PANEL_DATA_SOURCES,
        "ai_bundle": ai_bundle,
        "research_bundle": research_bundle,
        **strategy_registry_exports,
    }
    return finalize_diagnostic_bundle(session, bundle)


BUNDLE_FILE_GROUPS: dict[str, list[str]] = {
    "Account / Broker": [
        "alpaca_account_snapshot.json",
        "alpaca_non_marginable_buying_power.json",
        "alpaca_positions_truth.json",
        "alpaca_orders_truth.json",
        "broker_sync_status.json",
        "performance_summary.json",
        "equity_curve.json",
    ],
    "Universe / Market Data": ["universe.json", "bar_freshness.json", "quote_freshness.json"],
    "Push-Pull": [
        "push_pull_latest_tick.json",
        "push_pull_scores.json",
        "push_pull_decisions.json",
        "no_trade_reason_breakdown.json",
    ],
    "Orders / Execution": ["latest_order_attempt.json", "paper_order_proof.json", "execution_cage_decisions.json"],
    "Portfolio / Performance": ["positions_local.json", "reconciliation_status.json", "trade_history_current_epoch.json"],
    "Strategy / Backtesting": ["strategy_registry.json", "backtest_runs.json", "backtest_results.json"],
    "AI / Memory": ["ai_memory.json", "ai_lessons.json", "memory_quality_report.json"],
    "Activity / Audit": ["activity_feed.json", "reset_epoch.json", "nuke_status.json"],
    "System / Errors": ["system_health.json", "diagnostic_export_errors.json", "live_lock_status.json"],
    "Page API Snapshots": [
        "page_mission_control.json",
        "page_universe.json",
        "page_portfolio_execution.json",
        "page_performance.json",
        "page_activity.json",
        "page_ai_manager.json",
        "page_hive_mind.json",
        "page_reports.json",
        "page_control_center.json",
        "page_push_pull_trader.json",
    ],
}


def build_bundle_manifest(session: Session, bundle: dict[str, Any]) -> dict[str, Any]:
    import hashlib
    import json
    import os

    from app.services.export_safe import json_safe
    from app.services.nuke_epoch_service import get_latest_reset_epoch

    epoch = get_latest_reset_epoch(session)
    meta = bundle.get("bundle_meta.json") if isinstance(bundle.get("bundle_meta.json"), dict) else {}
    file_names = sorted(k for k in bundle.keys() if k.endswith(".json"))
    grouped: dict[str, list[str]] = {}
    for group, patterns in BUNDLE_FILE_GROUPS.items():
        grouped[group] = [f for f in file_names if f in patterns or any(f.startswith(p.replace(".json", "")) for p in patterns)]
    digest_src = json.dumps(json_safe({k: bundle[k] for k in file_names}), sort_keys=True, default=str)
    bundle_hash = hashlib.sha256(digest_src.encode()).hexdigest()[:16]
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "reset_epoch_id": (epoch or {}).get("reset_epoch_id") or meta.get("reset_epoch_id"),
        "backend_commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", meta.get("backend_commit", "dev"))[:12],
        "frontend_commit": os.environ.get("FRONTEND_GIT_COMMIT_SHA", meta.get("frontend_commit", "unknown"))[:12],
        "file_count": len(file_names),
        "grouped_file_list": grouped,
        "all_files": file_names,
        "bundle_hash": bundle_hash,
    }


def diagnostic_bundle_filename(session: Session) -> str:
    from app.services.nuke_epoch_service import get_latest_reset_epoch

    epoch = get_latest_reset_epoch(session)
    epoch_id = (epoch or {}).get("reset_epoch_id") or "no-reset-epoch"
    if epoch_id.startswith("reset-"):
        epoch_part = epoch_id
    else:
        epoch_part = f"reset-{epoch_id}" if epoch_id != "no-reset-epoch" else "no-reset-epoch"
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%SZ")
    return f"caged-hive-diagnostic-{stamp}-{epoch_part}.zip"


def finalize_diagnostic_bundle(session: Session, bundle: dict[str, Any]) -> dict[str, Any]:
    errors = list(bundle.get("diagnostic_export_errors.json") or [])
    try:
        from app.services.page_api_snapshots import export_all_page_snapshots

        bundle.update(export_all_page_snapshots(session))
    except Exception as exc:
        errors.append(
            {
                "section": "page_api_snapshots",
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
    try:
        bundle["bundle_manifest.json"] = build_bundle_manifest(session, bundle)
    except Exception as exc:
        errors.append(
            {
                "section": "bundle_manifest",
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
    if errors:
        bundle["diagnostic_export_errors.json"] = errors
    return bundle


def _emergency_bundle(session: Session, errors: list[dict[str, Any]], root_error: Optional[str] = None) -> dict[str, Any]:
    from app.services.live_lock_tripwire import live_lock_tripwire_status
    from app.config import settings

    if root_error:
        errors.insert(
            0,
            {
                "section": "export_root",
                "error_type": "ExportError",
                "message": root_error[:500],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        )
    trip = {}
    try:
        trip = live_lock_tripwire_status(ConfigManager(session).get_current())
    except Exception as exc:
        trip = {"error": type(exc).__name__, "message": str(exc)[:200]}
    return {
        "bundle_meta.json": {
            "status": "emergency",
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "note": "Partial export — see diagnostic_export_errors.json",
        },
        "diagnostic_export_errors.json": errors,
        "health_snapshot.json": {
            "alpaca_configured": settings.alpaca_configured,
            "gemini_configured": settings.gemini_configured,
            "database_configured": settings.database_configured,
        },
        "live_lock_tripwire_status.json": trip,
    }


def export_diagnostic_bundle_safe(session: Session) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    try:
        bundle = export_diagnostic_bundle(session)
        bundle["diagnostic_export_errors.json"] = errors + bundle.get("diagnostic_export_errors.json", [])
        if errors:
            meta = bundle.get("bundle_meta.json") or {}
            if isinstance(meta, dict):
                meta["partial"] = True
                meta["error_count"] = len(errors)
                bundle["bundle_meta.json"] = meta
        return bundle
    except Exception as exc:
        import traceback

        errors.append(
            {
                "section": "export_root",
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
                "traceback_summary": traceback.format_exc()[-3000:],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        return _emergency_bundle(session, errors, str(exc))


def bundle_as_zip_bytes_safe(session: Session) -> bytes:
    import io
    import zipfile

    from app.services.export_safe import json_safe

    errors: list[dict[str, Any]] = []
    try:
        bundle = export_diagnostic_bundle(session)
    except Exception as exc:
        import traceback

        errors.append(
            {
                "section": "export_root",
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
                "traceback_summary": traceback.format_exc()[-3000:],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        bundle = _emergency_bundle(session, errors, str(exc))

    bundle["diagnostic_export_errors.json"] = list(bundle.get("diagnostic_export_errors.json") or []) + errors
    if errors and isinstance(bundle.get("bundle_meta.json"), dict):
        bundle["bundle_meta.json"]["partial"] = True
        bundle["bundle_meta.json"]["error_count"] = len(bundle["diagnostic_export_errors.json"])

    ai_bundle = bundle.pop("ai_bundle", None)
    research_bundle = bundle.pop("research_bundle", None)
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in bundle.items():
                if name.endswith(".md"):
                    zf.writestr(name, str(content))
                else:
                    zf.writestr(name, json.dumps(json_safe(content), indent=2))
            if ai_bundle:
                for name, content in ai_bundle.items():
                    zf.writestr(f"ai_bundle/{name}", json.dumps(json_safe(content), indent=2))
            if research_bundle:
                for name, content in research_bundle.items():
                    zf.writestr(f"research_bundle/{name}", json.dumps(json_safe(content), indent=2))
        return buf.getvalue()
    except Exception as zip_exc:
        import traceback

        errors.append(
            {
                "section": "zip_encode",
                "error_type": type(zip_exc).__name__,
                "message": str(zip_exc)[:500],
                "traceback_summary": traceback.format_exc()[-2000:],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        emergency = _emergency_bundle(session, errors, str(zip_exc))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in emergency.items():
                zf.writestr(name, json.dumps(json_safe(content), indent=2))
        return buf.getvalue()


def bundle_as_zip_bytes(session: Session) -> bytes:
    return bundle_as_zip_bytes_safe(session)
