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
    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "cycle_run_id": details.get("cycle_run_id"),
        "event_type": row.event_type,
        "source": details.get("source", "system"),
        "message": row.message,
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
    # If no tick has run yet, do not mark any broker errors as latest-cycle.
    is_latest = False
    if scheduler_last_tick_at and created_iso:
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
    latest_cycle_errors = [e for e in broker_errors_all if e.get("is_latest_cycle")]
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

    lesson_rows = list(session.exec(select(LessonNode).order_by(LessonNode.last_seen_at.desc())).all())
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
        "ai_memories.json": [_serialize_row(r) for r in session.exec(select(AIMemory)).all()],
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
            "paper_experiment_config.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentConfig)).all()],
            "paper_experiment_decisions.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentDecision)).all()],
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
            "training_cycle_decisions.json": pl.list_decisions(),
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
            "fast_training_decisions.json": [
                _serialize_row(r)
                for r in session.exec(
                    select(PaperExperimentDecision)
                    .order_by(PaperExperimentDecision.created_at.desc())
                    .limit(50)
                ).all()
            ],
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

    return {
        "activity.json": activity_data,
        "trades.json": [_serialize_row(r) for r in session.exec(select(TradeRecord)).all()],
        "orders.json": [_serialize_row(r) for r in session.exec(select(OrderRecord)).all()],
        "blocked_trades.json": blocked_data,
        "risk_events.json": risk_data,
        "ai_reviews.json": [_serialize_row(r) for r in session.exec(select(AIReview)).all()],
        "ai_memories.json": [_serialize_row(r) for r in session.exec(select(AIMemory)).all()],
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
        "bundle_meta.json": {
            "database_fingerprint": database_fingerprint(),
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "db_counts": db_counts,
            "last_cycle_run_id": last_cycle.get("cycle_run_id") if last_cycle else None,
            "last_cycle_status": cycle_status,
            "latest_cycle_error_count": len(latest_cycle_errors),
            "historical_error_count": len(historical_alpaca_errors),
        },
        "frontend_api_contract.json": FRONTEND_API_CONTRACT,
        "frontend_endpoint_status.json": frontend_endpoint_status,
        "ui_panel_data_sources.json": UI_PANEL_DATA_SOURCES,
        "ai_bundle": ai_bundle,
        "research_bundle": research_bundle,
        **strategy_registry_exports,
    }


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
