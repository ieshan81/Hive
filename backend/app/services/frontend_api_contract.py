"""Frontend API contract metadata for diagnostic bundles."""

from __future__ import annotations

from typing import Any

FRONTEND_API_CONTRACT: list[dict[str, Any]] = [
    {
        "endpoint": "/health",
        "method": "GET",
        "expected_shape": {"status": "string"},
        "panels": ["ApiHealthProvider"],
    },
    {
        "endpoint": "/api/memory/graph",
        "method": "GET",
        "expected_shape": {"status": "optional", "nodes": "array", "edges": "array"},
        "panels": ["HiveMemoryGraphPanel", "HiveMindSection"],
        "query_params": ["category", "include_archived", "graph_default"],
    },
    {
        "endpoint": "/api/memory/lessons",
        "method": "GET",
        "expected_shape": {"lessons": "array"},
        "panels": ["HiveMindSection"],
    },
    {
        "endpoint": "/api/memory/node/{id}",
        "method": "GET",
        "expected_shape": {"node": "object"},
        "panels": ["MemoryLessonDrawer"],
    },
    {
        "endpoint": "/api/memory/hive-mind",
        "method": "GET",
        "expected_shape": {
            "trading_recent": "array",
            "system_recent": "array",
            "patterns": "array",
        },
        "panels": ["HiveMindSection"],
    },
    {
        "endpoint": "/api/decisions/latest",
        "method": "GET",
        "expected_shape": {"cycle_run_id": "string", "approved": "array", "blocked": "array"},
        "panels": ["Dashboard", "DecisionDrilldownModal"],
    },
    {
        "endpoint": "/api/decisions/approved",
        "method": "GET",
        "expected_shape": {"status": "ok", "decisions": "array"},
        "panels": ["DecisionDrilldownModal"],
        "query_params": ["cycle_run_id"],
    },
    {
        "endpoint": "/api/decisions/blocked",
        "method": "GET",
        "expected_shape": {"status": "ok", "decisions": "array"},
        "panels": ["DecisionDrilldownModal"],
        "query_params": ["cycle_run_id"],
    },
    {
        "endpoint": "/api/decisions/deferred",
        "method": "GET",
        "expected_shape": {"status": "ok", "decisions": "array"},
        "panels": ["DecisionDrilldownModal"],
    },
    {
        "endpoint": "/api/decisions/orders",
        "method": "GET",
        "expected_shape": {"status": "ok", "orders": "array"},
        "panels": ["DecisionDrilldownModal"],
    },
    {
        "endpoint": "/api/decisions/lessons",
        "method": "GET",
        "expected_shape": {"status": "ok", "lessons": "array"},
        "panels": ["DecisionDrilldownModal"],
    },
    {
        "endpoint": "/api/positions",
        "method": "GET",
        "expected_shape": {"status": "ok", "positions": "array"},
        "panels": ["PositionsPage"],
    },
    {
        "endpoint": "/api/positions/state",
        "method": "GET",
        "expected_shape": {"status": "ok", "states": "array"},
        "panels": ["PositionsPage"],
    },
    {
        "endpoint": "/api/orders",
        "method": "GET",
        "expected_shape": {"status": "ok", "orders": "array"},
        "panels": ["PositionsPage"],
    },
    {
        "endpoint": "/api/trades/history",
        "method": "GET",
        "expected_shape": {"status": "ok", "trades": "array"},
        "panels": ["PositionsPage"],
    },
    {
        "endpoint": "/api/dashboard",
        "method": "GET",
        "expected_shape": {"memoryGraph": "object", "aiFundManager": "object"},
        "panels": ["Dashboard SSR"],
        "fallback": "dashboard_snapshot.json",
    },
    {
        "endpoint": "/api/diagnostic-bundle/download",
        "method": "GET",
        "expected_shape": "application/zip",
        "panels": ["TopStatusBar"],
    },
]

UI_PANEL_DATA_SOURCES: list[dict[str, Any]] = [
    {
        "panel": "HiveMemoryGraphPanel",
        "endpoints": ["/api/memory/graph", "/api/memory/node/{id}"],
        "fallback": "dashboard_snapshot.memoryGraph",
    },
    {
        "panel": "PositionsPage",
        "endpoints": [
            "/api/positions",
            "/api/positions/state",
            "/api/trades/history",
            "/api/orders",
        ],
        "fallback": "positions.json, position_states.json, trades_history.json, orders.json",
    },
    {
        "panel": "DecisionDrilldownModal",
        "endpoints": ["/api/decisions/{type}?cycle_run_id=latest"],
        "fallback": "blocked_decisions.json, approved_decisions.json",
    },
    {
        "panel": "HiveMindSection",
        "endpoints": ["/api/memory/hive-mind", "/api/memory/graph"],
        "fallback": "dashboard_snapshot.json",
    },
    {
        "panel": "Dashboard",
        "endpoints": ["/api/dashboard"],
        "fallback": "dashboard_snapshot.json",
    },
]


def build_frontend_endpoint_status(session) -> list[dict[str, Any]]:
    """In-process probe of the same data backing API routes (no HTTP/CORS)."""
    from app.config import settings
    from app.services.config_manager import ConfigManager
    from app.services.decisions_service import blocked_decisions, latest_summary
    from app.services.lesson_memory_service import LessonMemoryService
    from app.services.positions_tab_service import (
        current_positions,
        orders_history,
        position_states,
        trades_history,
    )

    config = ConfigManager(session).get_current()
    probes: list[tuple[str, Any]] = [
        ("/api/memory/graph", lambda: LessonMemoryService(session, config).build_graph()),
        ("/api/decisions/latest", lambda: latest_summary(session, "latest")),
        (
            "/api/decisions/blocked?cycle_run_id=latest",
            lambda: {"decisions": blocked_decisions(session, "latest")},
        ),
        ("/api/positions", lambda: {"positions": current_positions(session)}),
        ("/api/positions/state", lambda: {"states": position_states(session)}),
        ("/api/orders", lambda: {"orders": orders_history(session)}),
        ("/api/trades/history", lambda: {"trades": trades_history(session)}),
    ]
    base_hint = f"http://{settings.api_host}:{settings.api_port}"
    out: list[dict[str, Any]] = []
    for path, fn in probes:
        row: dict[str, Any] = {
            "path": path,
            "url": f"{base_hint}{path.split('?')[0]}",
            "ok": False,
            "status": 200,
            "content_type": "application/json",
            "keys": [],
            "error": None,
            "fallback_used": False,
        }
        try:
            body = fn()
            if isinstance(body, dict):
                row["keys"] = list(body.keys())
            row["item_count"] = _count_items(body)
            row["ok"] = True
        except Exception as e:
            row["error"] = str(e)[:200]
            row["status"] = 500
        out.append(row)
    return out


def _count_items(body: Any) -> int | None:
    if isinstance(body, list):
        return len(body)
    if not isinstance(body, dict):
        return None
    for key in ("nodes", "positions", "states", "orders", "trades", "decisions", "blocked", "lessons"):
        if isinstance(body.get(key), list):
            return len(body[key])
    return None
