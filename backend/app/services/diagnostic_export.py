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
    BacktestResult,
    BlockedTrade,
    BrokerError,
    MonteCarloResult,
    OrderRecord,
    RiskEvent,
    StrategySignal,
    StrategyState,
    SymbolCandidate,
    SystemHealth,
    TradeRecord,
)
from app.services.config_manager import ConfigManager
from app.services.cycle_persistence import (
    count_cycle_rows,
    database_fingerprint,
    latest_cycle_end,
    _risk_event_cycle_id,
)


def _serialize(rows: list) -> list[dict]:
    result = []
    for row in rows:
        data = row.model_dump() if hasattr(row, "model_dump") else dict(row)
        for k, v in data.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat() + "Z"
        result.append(data)
    return result


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
        db_counts = count_cycle_rows(session, latest_cycle_id)

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
        f"- strategy_signals: {len(signal_rows)}",
        f"- symbol_candidates: {len(candidate_rows)}",
        f"- blocked_trades: {len(blocked_rows)}",
        f"- risk_events (trade_blocked): {len(risk_rows)}",
        "",
        "## Last Cycle",
    ]

    if last_cycle:
        summary_lines.extend(
            [
                f"- Cycle run id: {last_cycle.get('cycle_run_id', 'unknown')}",
                f"- Timestamp: {last_cycle.get('ended_at') or last_cycle.get('started_at', 'unknown')}",
                f"- Status: {last_cycle.get('status', 'unknown')}",
                f"- Session mode: {(last_cycle.get('session') or {}).get('mode', 'unknown')}",
                f"- Radar count: {last_cycle.get('radar_count', 0)}",
                f"- Signals generated: {last_cycle.get('signals_generated', 0)}",
                f"- Signals created: {last_cycle.get('signals_created', 0)}",
                f"- Signals evaluated: {last_cycle.get('signals_evaluated', 0)}",
                f"- Blocked: {last_cycle.get('blocked', 0)}",
                f"- Approved: {last_cycle.get('approved', 0)}",
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

    dashboard = build_dashboard(session)

    return {
        "activity.json": _serialize(activity_rows),
        "trades.json": _serialize(list(session.exec(select(TradeRecord)).all())),
        "orders.json": _serialize(list(session.exec(select(OrderRecord)).all())),
        "blocked_trades.json": _serialize(blocked_rows),
        "risk_events.json": _serialize(risk_rows),
        "ai_reviews.json": _serialize(list(session.exec(select(AIReview)).all())),
        "ai_memories.json": _serialize(list(session.exec(select(AIMemory)).all())),
        "config_history.json": _serialize(config_mgr.list_history(100)),
        "current_config.json": config_mgr.get_current(),
        "backtest_results.json": _serialize(list(session.exec(select(BacktestResult)).all())),
        "monte_carlo_results.json": _serialize(list(session.exec(select(MonteCarloResult)).all())),
        "strategy_states.json": _serialize(strategy_rows),
        "strategy_signals.json": _serialize(signal_rows),
        "symbol_candidates.json": _serialize(candidate_rows),
        "alpaca_errors.json": _serialize(list(session.exec(select(BrokerError)).all())),
        "system_health.json": _serialize([health] if health else []),
        "system_summary.md": "\n".join(summary_lines),
        "dashboard_snapshot.json": dashboard,
        "bundle_meta.json": {
            "database_fingerprint": database_fingerprint(),
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "db_counts": db_counts,
            "last_cycle_run_id": last_cycle.get("cycle_run_id") if last_cycle else None,
        },
    }


def bundle_as_zip_bytes(session: Session) -> bytes:
    import io
    import zipfile

    bundle = export_diagnostic_bundle(session)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in bundle.items():
            if name.endswith(".md"):
                zf.writestr(name, content)
            else:
                zf.writestr(name, json.dumps(content, indent=2, default=str))
    return buf.getvalue()
