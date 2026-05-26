"""Expand mission control with full cockpit payload."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select, func

from app.database import ExecutionLog, LessonNode, PaperExperimentDecision
from app.services.capital_allocator import CapitalAllocatorService
from app.services.confidence_engine import ConfidenceEngine
from app.services.config_manager import ConfigManager
from app.services.execution_logs_query_service import list_execution_logs
from app.services.exit_monitor_service import exit_monitor_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.memory_policy_service import MemoryPolicyService
from app.services.performance_service import equity_curve, performance_summary
from app.services.product_truth_service import product_truth
from app.services.push_pull_engine_service import PushPullEngineService
from app.services.sentiment_status_service import ai_advisor_status, sentiment_status
from app.services.strategy_status_service import candidate_rankings, last_tick_narrative, strategy_status
from app.services.universe_mode_service import universe_mode_status
from app.services.mission_control_service import _account_truth, _headline


def mission_control_cockpit(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    truth = product_truth(session, cfg)
    push_pull = PushPullEngineService(session, cfg).status()
    allocator = CapitalAllocatorService(session, cfg).status_summary()
    plan = CapitalAllocatorService(session, cfg).build_plan()
    account = _account_truth(session, cfg)
    graph = equity_curve(session, limit=120)
    memory = MemoryPolicyService(session).status()
    conf = ConfidenceEngine(session, cfg).summary()
    env = truth.get("env_pause_status") or {}
    lock = live_lock_tripwire_status(cfg)
    advisor = ai_advisor_status(session, cfg)
    sentiment = sentiment_status(session, cfg)
    strategy = strategy_status(session, cfg)
    universe_mode = universe_mode_status(session, cfg)
    exit_mon = exit_monitor_status(session, cfg)
    tick_narr = last_tick_narrative(session, cfg)
    candidates = candidate_rankings(session, cfg)
    latest_logs = list_execution_logs(session, scope="latest_tick", limit=3)

    hive_preview = _hive_brain_preview(session, memory)

    return {
        "status": "ok",
        **truth,
        "cockpit_bar": {
            "live_trading": "Locked" if lock.get("live_lock_status") == "locked" else lock.get("live_lock_status"),
            "paper_learning": "On" if truth.get("operator_desired_paper_learning") else "Off",
            "current_mode": truth.get("current_mode_label"),
            "confidence": conf.get("overall_label") or conf.get("overall"),
            "broker_sync": account.get("broker_sync_status"),
            "paper_broker": truth.get("paper_broker_status"),
            "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
            "last_sync_at": account.get("synced_at"),
        },
        "mission_summary": {
            "headline": _headline(truth, env),
            "engine_doing": tick_narr.get("narrative"),
            "scans_on_schedule": truth.get("operator_desired_scheduler"),
            "entries_allowed": truth.get("effective_can_place_paper_orders"),
            "exits_monitored": exit_mon.get("open_positions_count", 0) > 0,
            "learning_recording": truth.get("operator_desired_paper_learning"),
            "broker_sync_healthy": account.get("broker_sync_status") == "synced",
        },
        "hive_brain_preview": hive_preview,
        "account_survival": account,
        "capital_allocator": {
            **allocator,
            "detail": {
                "deployable_capital": plan.get("deployable_capital"),
                "cash_reserve": plan.get("required_cash_reserve"),
                "crypto_budget": plan.get("crypto_allocation_budget"),
                "stock_budget": plan.get("stock_allocation_budget"),
                "allocation_health": plan.get("diversification_health"),
            },
            "sparkline": [p.get("equity") for p in (graph.get("points") or [])[-20:]],
        },
        "ai_fund_manager": {
            "active": advisor.get("advisor_active"),
            "configured": advisor.get("gemini_configured"),
            "current_decision": (advisor.get("latest_review") or {}).get("decision") if advisor.get("latest_review") else "No review yet",
            "confidence": (advisor.get("latest_review") or {}).get("confidence"),
            "reason_summary": (advisor.get("latest_review") or {}).get("summary") if advisor.get("latest_review") else "Gemini advisor inactive or no reviews run.",
            "memory_used": memory.get("latest_useful_lesson"),
            "approval_result": "Advisory only — cannot approve live trading or direct orders",
            "sentiment_engines": sentiment.get("sources"),
        },
        "push_pull_engine": push_pull,
        "strategy_status": strategy,
        "paper_learning": {
            "learning_status": "On" if truth.get("operator_desired_paper_learning") else "Off",
            "scheduler": truth.get("scheduler"),
            "lesson_recording": memory.get("counts", {}).get("validated_count", 0) > 0,
            "memory_quality": memory.get("counts"),
        },
        "latest_insight": {
            **tick_narr,
            "latest_order": latest_logs.get("execution_logs", [{}])[0] if latest_logs.get("execution_logs") else None,
        },
        "risk_cage": {
            "stop_loss_required": cfg.get("stop_loss_required", True),
            "deployment_caps": plan.get("learning_capacity"),
            "drawdown_rules": cfg.get("max_drawdown_limit_pct"),
            "duplicate_entry_protection": True,
            "stale_data_guard": True,
            "quote_age_guard_seconds": (cfg.get("execution") or {}).get("quote_max_age_seconds", 30),
            "live_locked": lock.get("live_lock_status") == "locked",
        },
        "capital_graph": graph,
        "market_radar": candidates,
        "universe_mode": universe_mode,
        "exit_monitor": exit_mon,
        "memory_policy": memory,
        "account_truth": account,
        "capital_allocator_detail": plan,
        "fresh_brain": memory.get("counts", {}).get("meaningful_memory_count", 0) == 0,
        "live_lock": lock,
    }


def _hive_brain_preview(session: Session, memory: dict) -> dict[str, Any]:
    counts = memory.get("counts") or {}
    epoch_id = memory.get("reset_epoch_id")
    q = select(LessonNode.memory_type, func.count()).group_by(LessonNode.memory_type)
    if epoch_id:
        rows = session.exec(q).all()
    else:
        rows = session.exec(q).all()
    by_type = {str(k or "unknown"): int(v) for k, v in rows}
    return {
        "meaningful_memory_count": counts.get("meaningful_memory_count", 0),
        "validated_count": counts.get("validated_count", 0),
        "consolidated_count": counts.get("consolidated_count", 0),
        "categories": {
            "lessons": by_type.get("risk_memory", 0) + by_type.get("strategy_parameter_lesson", 0),
            "mistakes": by_type.get("paper_trade_failure", 0),
            "blocked_trades": by_type.get("consolidated_memory", 0),
            "strategies": by_type.get("strategy_parameter_lesson", 0),
        },
        "latest_lesson": memory.get("latest_useful_lesson"),
    }
