"""Diagnostic bundle export."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import (
    ActivityLog,
    AIReview,
    AIMemory,
    BacktestResult,
    BlockedTrade,
    BrokerError,
    ConfigCurrent,
    ConfigHistory,
    MonteCarloResult,
    OrderRecord,
    RiskEvent,
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
                data[k] = v.isoformat()
        result.append(data)
    return result


def export_diagnostic_bundle(session: Session) -> dict[str, Any]:
    config_mgr = ConfigManager(session)
    dashboard = build_dashboard(session)
    health = session.get(SystemHealth, 1)

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
        "## Core Principle",
        "Rules trade fast. AI learns slowly. Risk engine blocks danger.",
        "Paper trading only. No live trading. No fake data.",
    ]

    return {
        "activity.json": _serialize(list(session.exec(select(ActivityLog)).all())),
        "trades.json": _serialize(list(session.exec(select(TradeRecord)).all())),
        "orders.json": _serialize(list(session.exec(select(OrderRecord)).all())),
        "blocked_trades.json": _serialize(list(session.exec(select(BlockedTrade)).all())),
        "risk_events.json": _serialize(list(session.exec(select(RiskEvent)).all())),
        "ai_reviews.json": _serialize(list(session.exec(select(AIReview)).all())),
        "ai_memories.json": _serialize(list(session.exec(select(AIMemory)).all())),
        "config_history.json": _serialize(config_mgr.list_history(100)),
        "current_config.json": config_mgr.get_current(),
        "backtest_results.json": _serialize(list(session.exec(select(BacktestResult)).all())),
        "monte_carlo_results.json": _serialize(list(session.exec(select(MonteCarloResult)).all())),
        "strategy_states.json": _serialize(list(session.exec(select(StrategyState)).all())),
        "symbol_candidates.json": _serialize(list(session.exec(select(SymbolCandidate)).all())),
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
