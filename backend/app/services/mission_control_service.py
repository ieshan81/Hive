"""Mission Control — single-page operator truth for paper push-pull bot."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.capital_allocator import CapitalAllocatorService
from app.services.config_manager import ConfigManager
from app.services.execution_logs_query_service import list_execution_logs
from app.services.performance_service import equity_curve, performance_summary
from app.services.product_truth_service import product_truth
from app.services.push_pull_engine_service import PushPullEngineService
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.nuke_epoch_service import get_latest_reset_epoch
from app.database import AccountSnapshot
from sqlmodel import select


def _account_truth(session: Session, cfg: dict) -> dict[str, Any]:
    alpaca = AlpacaAdapter(session)
    snap = alpaca.sync_account_cached(force=False)
    if not snap:
        snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
    epoch = get_latest_reset_epoch(session)
    raw = (getattr(snap, "raw_payload", None) or {}) if snap else {}
    positions = alpaca.sync_positions_cached() or []
    open_upl = sum(float(getattr(p, "unrealized_pl", 0) or 0) for p in positions)
    equity = float(snap.equity or 0) if snap else 0.0
    cash = float(snap.cash or 0) if snap else 0.0
    bp = float(snap.buying_power or 0) if snap else 0.0
    nmbp = float(raw.get("non_marginable_buying_power") or bp)
    portfolio_val = float(snap.portfolio_value or 0) if snap else 0.0
    starting = equity
    if epoch:
        starting = float(epoch.get("starting_equity") or epoch.get("equity_at_reset") or equity)
    perf = performance_summary(session, cfg)
    return {
        "current_paper_equity": round(equity, 2),
        "starting_equity_reset_epoch": round(starting, 2),
        "cash": round(cash, 2),
        "buying_power": round(bp, 2),
        "non_marginable_buying_power": round(nmbp, 2),
        "open_positions_value": round(max(portfolio_val - cash, 0), 2),
        "realized_pl": perf.get("pl_dollars"),
        "unrealized_pl": round(open_upl, 2),
        "total_pl": round(equity - starting, 2),
        "today_pl": round(float(snap.daily_pl or 0) if snap else 0, 2),
        "broker_sync_status": "synced" if snap else "unknown",
        "synced_at": snap.synced_at.isoformat() + "Z" if snap and snap.synced_at else None,
        "reset_epoch_id": (epoch or {}).get("reset_epoch_id"),
    }


def mission_control_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    truth = product_truth(session, cfg)
    push_pull = PushPullEngineService(session, cfg).status()
    allocator = CapitalAllocatorService(session, cfg).status_summary()
    plan = CapitalAllocatorService(session, cfg).build_plan()
    latest_logs = list_execution_logs(session, scope="latest_tick", limit=5)
    last_tick = push_pull.get("last_tick") or {}
    account = _account_truth(session, cfg)
    graph = equity_curve(session, limit=90)

    env = truth.get("env_pause_status") or {}
    headline = _headline(truth, env)

    return {
        "status": "ok",
        **truth,
        "fresh_brain": truth.get("fresh_brain"),
        "nuke_status": truth.get("nuke_status"),
        "account_truth": account,
        "capital_graph": graph,
        "capital_allocator_detail": {
            "deployable_capital": plan.get("deployable_capital"),
            "cash_reserve": plan.get("required_cash_reserve") or plan.get("cash_reserve_budget"),
            "crypto_budget": plan.get("crypto_allocation_budget"),
            "stock_budget": plan.get("stock_allocation_budget"),
            "max_open_positions": (plan.get("learning_capacity") or {}).get("max_open_positions_cap"),
            "current_exposure": round(
                float(plan.get("current_stock_exposure") or 0) + float(plan.get("current_crypto_exposure") or 0),
                2,
            ),
            "remaining_allocation": plan.get("deployable_capital"),
        },
        "latest_mission": {
            "latest_tick": last_tick,
            "symbols_scanned": last_tick.get("symbols_scanned"),
            "top_candidates": last_tick.get("top_candidates"),
            "selected_candidate": last_tick.get("selected_candidate"),
            "selection_reason": last_tick.get("selection_reason") or last_tick.get("plain"),
            "latest_order_attempt": latest_logs.get("execution_logs", [{}])[0] if latest_logs.get("execution_logs") else None,
            "next_tick_time": truth.get("scheduler", {}).get("next_tick_at"),
        },
        "system_state_banner": {
            "headline": headline,
            "subline": truth.get("operator_next_action") or last_tick.get("plain"),
            "live_locked": truth.get("live_lock_status") == "locked",
            "paper_broker": truth.get("paper_broker_status") == "paper",
            "degraded": allocator.get("status") == "degraded",
        },
        "push_pull_engine": push_pull,
        "paper_learning": {
            "desired_enabled": truth.get("operator_desired_paper_learning"),
            "effective_enabled": truth.get("effective_can_scan"),
            "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
            "paper_learning_on": "ON" if truth.get("operator_desired_paper_learning") else "OFF",
            "paper_execution_on": "ON" if truth.get("operator_desired_paper_execution") else "OFF",
        },
        "scheduler": truth.get("scheduler") or {},
        "env_pause": env,
        "live_lock": {"live_lock_status": truth.get("live_lock_status")},
        "last_tick_summary": last_tick,
        "last_execution_logs": latest_logs.get("execution_logs", []),
        "capital_allocator": allocator,
        "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
        "next_action_plain": truth.get("operator_next_action"),
    }


def _headline(truth: dict, env: dict) -> str:
    if env.get("any_env_pause"):
        return "Env pause active — execution blocked until Railway env vars cleared"
    mode = truth.get("current_mode")
    if mode == "paper_learning_off":
        return "Paper learning OFF — use Start Fresh Paper Learning"
    if mode == "push_pull_paper_learning":
        return "Push-Pull Paper Learning active — scans on schedule"
    if mode == "push_pull_scanning":
        return "Push-Pull scanning — waiting for entry or fixing blocker"
    return truth.get("current_mode_label") or "System status"
