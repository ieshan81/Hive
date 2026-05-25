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
    return {
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
) -> dict[str, Any]:
    details = row.details if isinstance(row.details, dict) else {}
    cycle_id = row.cycle_run_id or details.get("cycle_run_id")
    is_latest = bool(latest_cycle_id and cycle_id == latest_cycle_id)
    if not is_latest and latest_cycle_id and cycle_started and row.created_at:
        is_latest = _iso(row.created_at) >= cycle_started
    return {
        "id": row.id,
        "source": row.source,
        "operation": row.operation,
        "message": row.message,
        "details": details or None,
        "created_at": _iso(row.created_at),
        "cycle_run_id": cycle_id,
        "is_latest_cycle": is_latest,
        "historical": not is_latest,
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

    from app.services.dashboard_service import build_dashboard
    from app.services.attention_radar_service import AttentionRadarService
    from app.services.cooldown_service import CooldownService
    from app.services.kill_switch_service import KillSwitchService
    from app.services.promotion_service import PromotionService
    from app.services.paper_execution_service import PaperExecutionService
    from app.services.order_reconciliation import reconciliation_status

    dashboard = build_dashboard(session)
    attention = AttentionRadarService(session).scan(limit=25)
    config = config_mgr.get_current()
    cooldowns = CooldownService(session, config).list_all()
    kill_status = KillSwitchService(session, config).status()
    promotion = PromotionService(session, config).status()
    execution_policy = PaperExecutionService(session).status()
    from app.services.alpaca_adapter import AlpacaAdapter

    recon = reconciliation_status(session, AlpacaAdapter(session))
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
    try:
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
        graph = LessonMemoryService(session, ConfigManager(session).get_current()).build_graph(
            graph_default=True, limit=80
        )
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
            "paper_learning_status.json": pl.status(),
            "paper_experiment_config.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentConfig)).all()],
            "paper_experiment_decisions.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentDecision)).all()],
            "paper_experiment_outcomes.json": [_serialize_row(r) for r in session.exec(select(PaperExperimentOutcome)).all()],
            "paper_experiment_memories.json": pl.list_memories(40),
            "memory_graph_clusters.json": graph.get("meta", {}),
            "memory_validation_mismatches.json": mph,
            "memory_pipeline_health.json": mph,
            "system_validation_audit.json": [_serialize_row(r) for r in session.exec(select(SystemValidationAudit)).all()],
            "ai_advisory_history.json": [_serialize_row(r) for r in session.exec(select(AIReview)).all()[:30]],
        }
    except Exception as exc:
        strategy_registry_exports = {"strategy_registry_error.json": {"error": str(exc)}}

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
        "memory_graph.json": memory_graph,
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


def bundle_as_zip_bytes(session: Session) -> bytes:
    import io
    import zipfile

    bundle = export_diagnostic_bundle(session)
    ai_bundle = bundle.pop("ai_bundle", None)
    research_bundle = bundle.pop("research_bundle", None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in bundle.items():
            if name.endswith(".md"):
                zf.writestr(name, content)
            else:
                zf.writestr(name, json.dumps(content, indent=2, default=str))
        if ai_bundle:
            for name, content in ai_bundle.items():
                zf.writestr(f"ai_bundle/{name}", json.dumps(content, indent=2, default=str))
        if research_bundle:
            for name, content in research_bundle.items():
                zf.writestr(f"research_bundle/{name}", json.dumps(content, indent=2, default=str))
    return buf.getvalue()
