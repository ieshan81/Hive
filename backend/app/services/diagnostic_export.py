"""Diagnostic bundle export."""

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
from app.services.dashboard_service import build_dashboard


def _serialize(rows: list) -> list[dict]:
    result = []
    for row in rows:
        data = row.model_dump() if hasattr(row, "model_dump") else dict(row)
        for k, v in data.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat() + "Z"
        result.append(data)
    return result


def _latest_cycle_from_activity(session: Session) -> Optional[dict]:
    row = session.exec(
        select(ActivityLog)
        .where(ActivityLog.event_type == "cycle_end")
        .order_by(ActivityLog.created_at.desc())
    ).first()
    if row and row.details:
        return row.details
    return None


def export_diagnostic_bundle(session: Session) -> dict[str, Any]:
    config_mgr = ConfigManager(session)
    dashboard = build_dashboard(session)
    health = session.get(SystemHealth, 1)

    activity_rows = list(session.exec(select(ActivityLog).order_by(ActivityLog.created_at.desc())).all())
    strategy_rows = list(session.exec(select(StrategyState)).all())
    signal_rows = list(session.exec(select(StrategySignal).order_by(StrategySignal.created_at.desc())).all())
    candidate_rows = list(session.exec(select(SymbolCandidate)).all())
    blocked_rows = list(session.exec(select(BlockedTrade)).all())
    risk_rows = list(session.exec(select(RiskEvent)).all())

    last_cycle = _latest_cycle_from_activity(session)
    if last_cycle is None and health and health.details:
        last_cycle = health.details.get("last_cycle")

    summary_lines = [
        "# Caged Hive Quant — System Summary",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "## Connection Status",
        f"- Alpaca: {'connected' if dashboard['systemStatus']['alpacaConnected'] else 'not connected'}",
        f"- Gemini: {'configured' if dashboard['systemStatus']['geminiConfigured'] else 'not configured'}",
        f"- Database: {'connected' if dashboard['systemStatus']['databaseConnected'] else 'unavailable'}",
        f"- Kill Switch: {'ACTIVE' if dashboard['systemStatus']['killSwitchActive'] else 'off'}",
        "",
        "## Backend Data Counts",
        f"- activity_logs: {len(activity_rows)}",
        f"- strategy_states: {len(strategy_rows)}",
        f"- strategy_signals: {len(signal_rows)}",
        f"- symbol_candidates: {len(candidate_rows)}",
        f"- blocked_trades: {len(blocked_rows)}",
        f"- risk_events: {len(risk_rows)}",
        "",
        "## Last Cycle",
    ]

    if last_cycle:
        summary_lines.extend(
            [
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
                "## Strategy States (last cycle)",
            ]
        )
        for st in last_cycle.get("strategy_states") or []:
            summary_lines.append(f"- {st.get('strategy')}: {st.get('status')} — {st.get('reason')}")
    else:
        summary_lines.append("- Status: never run")
        summary_lines.append("- Run POST /api/cycle/run to populate backend data")

    summary_lines.extend(
        [
            "",
            "## Core Principle",
            "Rules trade fast. AI learns slowly. Risk engine blocks danger.",
            "Paper trading only. No live trading. No fake data.",
        ]
    )

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
