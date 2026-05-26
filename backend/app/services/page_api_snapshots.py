"""Page-level API snapshots for diagnostic bundle."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager

SCHEMA_VERSION = 1
CONTRACT_VERSION = "2026-05-26-v1"


def _snap(
    session: Session,
    *,
    page_route: str,
    endpoints: list[tuple[str, Callable[[Session], dict]]],
) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    called: list[dict[str, Any]] = []
    warnings: list[str] = []
    payloads: dict[str, Any] = {}

    for name, fn in endpoints:
        try:
            data = fn(session)
            status = data.get("status", "ok")
            called.append({"endpoint": name, "status": status})
            payloads[name.split("/")[-1]] = data
            if status not in ("ok", "degraded"):
                warnings.append(f"{name} returned {status}")
        except Exception as exc:
            called.append({"endpoint": name, "status": "error", "error": type(exc).__name__})
            warnings.append(f"{name} failed: {type(exc).__name__}")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "page_route": page_route,
        "endpoints_called": [e["endpoint"] for e in called],
        "response_statuses": called,
        "frontend_api_contract_version": CONTRACT_VERSION,
        "warnings": warnings,
        "payloads": payloads,
        "visible_cards_expected": _cards_for_route(page_route),
        "empty_states": [w for w in warnings if "empty" in w.lower()],
    }


def _cards_for_route(route: str) -> list[str]:
    mapping = {
        "/": ["account_truth", "capital_graph", "allocator", "latest_mission", "system_banner"],
        "/universe": ["symbol_counts", "crypto_list", "stock_list", "freshness"],
        "/portfolio": ["broker_truth", "local_truth", "reconciliation"],
        "/performance": ["equity_curve", "pl_summary", "open_positions"],
        "/activity": ["candle_cycles", "recent_events"],
        "/ai-manager": ["memory_categories", "strategy_lab", "backtest_lab"],
        "/reports": ["bundle_groups", "download_meta"],
        "/control-center": ["system_state", "risk_cage", "operator_actions", "danger_zone"],
        "/push-pull": ["candle_cycle", "order_proof", "exit_monitor"],
    }
    return mapping.get(route, ["main_panel"])


def export_all_page_snapshots(session: Session) -> dict[str, Any]:
    from app.services.mission_control_cockpit_service import mission_control_cockpit
    from app.services.universe_service import universe_status
    from app.services.activity_feed_service import activity_feed
    from app.services.performance_service import performance_summary, equity_curve
    from app.services.ai_manager_service import AIManagerService
    from app.services.memory_policy_service import MemoryPolicyService
    from app.services.control_center_service import control_center_status
    from app.services.push_pull_engine_service import PushPullEngineService
    from app.services.paper_order_proof_service import PaperOrderProofService
    from app.services.exit_monitor_service import exit_monitor_status
    from app.services.reports_hub_service import ReportsHubService

    cfg = ConfigManager(session).get_current()
    ai = AIManagerService(session)

    pages = {
        "page_mission_control.json": _snap(
            session,
            page_route="/",
            endpoints=[("/api/mission-control/status", lambda s: mission_control_cockpit(s, cfg))],
        ),
        "page_universe.json": _snap(
            session,
            page_route="/universe",
            endpoints=[("/api/universe/status", lambda s: universe_status(s, cfg))],
        ),
        "page_portfolio_execution.json": _snap(
            session,
            page_route="/portfolio",
            endpoints=[
                ("/api/portfolio/reconciliation", lambda s: __import__(
                    "app.services.portfolio_reconciliation_service",
                    fromlist=["portfolio_reconciliation"],
                ).portfolio_reconciliation(s, cfg)),
                ("/api/push-pull/paper-order-proof", lambda s: PaperOrderProofService(s, cfg).summary()),
            ],
        ),
        "page_performance.json": _snap(
            session,
            page_route="/performance",
            endpoints=[
                ("/api/performance/summary", lambda s: performance_summary(s, cfg)),
                ("/api/performance/equity-curve", lambda s: equity_curve(s)),
            ],
        ),
        "page_activity.json": _snap(
            session,
            page_route="/activity",
            endpoints=[
                ("/api/activity/feed", lambda s: activity_feed(s, 50)),
                ("/api/activity/latest-tick-card", lambda s: __import__(
                    "app.services.activity_feed_service", fromlist=["latest_tick_card"]
                ).latest_tick_card(s)),
            ],
        ),
        "page_ai_manager.json": _snap(
            session,
            page_route="/ai-manager",
            endpoints=[
                ("/api/ai-manager/status", lambda s: ai.status()),
                ("/api/ai-manager/lessons", lambda s: ai.lessons(20)),
                ("/api/sentiment/status", lambda s: __import__(
                    "app.services.sentiment_status_service", fromlist=["sentiment_status"]
                ).sentiment_status(s, cfg)),
                ("/api/ai-advisor/status", lambda s: __import__(
                    "app.services.sentiment_status_service", fromlist=["ai_advisor_status"]
                ).ai_advisor_status(s, cfg)),
            ],
        ),
        "page_hive_mind.json": _snap(
            session,
            page_route="/ai-manager",
            endpoints=[
                ("/api/ai-manager/memories", lambda s: ai.memories(30)),
                ("/api/memory-policy/status", lambda s: MemoryPolicyService(s).status()),
            ],
        ),
        "page_reports.json": _snap(
            session,
            page_route="/reports",
            endpoints=[("/api/reports/diagnostic-bundle/status", lambda s: ReportsHubService(s, cfg).diagnostic_bundle_status())],
        ),
        "page_control_center.json": _snap(
            session,
            page_route="/control-center",
            endpoints=[("/api/control-center/status", lambda s: control_center_status(s))],
        ),
        "page_push_pull_trader.json": _snap(
            session,
            page_route="/push-pull",
            endpoints=[
                ("/api/push-pull/latest-tick", lambda s: PushPullEngineService(s, cfg).latest_tick()),
                ("/api/push-pull/exit-monitor/status", lambda s: exit_monitor_status(s, cfg)),
            ],
        ),
    }
    return pages
