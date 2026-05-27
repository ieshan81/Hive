"""One-click resume after NUKE or idle state — paper learning ready without manual sequence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.activity_logger import log_activity
from app.services.config_manager import ConfigManager, _deep_merge
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.paper_learning_blockers import compute_push_pull_blockers
from app.services.paper_learning_truth import paper_learning_display_status


def start_fresh_paper_learning(session: Session, operator: str = "operator") -> dict[str, Any]:
    """
    Enable paper execution + push-pull learning + scheduler.
    Does not enable live trading or env pause flags.
    """
    env = env_pause_status()
    if env.get("any_env_pause"):
        return {
            "status": "refused",
            "reason": "env_pause_active",
            "env_pause": env,
            "message": "Cannot start fresh while Railway env pause vars are set.",
        }

    cfg_mgr = ConfigManager(session)
    cur = cfg_mgr.get_current()
    lock = live_lock_tripwire_status(cur)
    if lock.get("live_lock_status") != "locked":
        return {"status": "refused", "reason": "live_lock_not_locked", **lock}

    from app.services.paper_execution_service import PaperExecutionService

    from app.services.push_pull_strategy_seed import ensure_crypto_push_pull_baseline

    ensure_crypto_push_pull_baseline(session, cfg_mgr.get_current())
    PaperExecutionService(session).enable(operator=operator)

    from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop

    ft_out = FastCryptoTrainingLoop(session).enable(operator)
    if ft_out.get("status") not in ("ok",):
        return {
            "status": "refused",
            "reason": ft_out.get("reason") or "fast_training_enable_failed",
            "detail": ft_out,
        }

    apl = dict(cur.get("autonomous_paper_learning") or {})
    ft_cfg = dict(cur.get("fast_training") or {})
    merged = _deep_merge(
        cur,
        {
            "autonomous_paper_learning": {
                **apl,
                "mode_enabled": True,
                "scheduler_enabled": True,
                "max_paper_trades_per_day": 0,
                "max_paper_notional_per_trade_usd": 0,
                "max_open_paper_positions": 0,
                "use_capital_allocator": True,
            },
            "live_trading_enabled": False,
            "execution": {
                **(cur.get("execution") or {}),
                "live_orders_enabled": False,
                "paper_orders_enabled": True,
                "max_orders_per_cycle": 0,
                "max_orders_per_hour": 0,
                "max_orders_per_day": 0,
            },
            "fast_training": {
                **ft_cfg,
                "fast_training_loop_enabled": True,
                "fast_training_execute_orders": True,
                "fast_training_max_trades_per_day": 0,
                "fast_training_max_open_positions": 0,
            },
            "aggressive_paper_learning": {
                **(cur.get("aggressive_paper_learning") or {}),
                "mode_enabled": True,
                "max_experiment_notional_per_trade_usd": 0,
                "max_experiment_positions_total": 0,
                "max_experiment_trades_per_day": 0,
                "max_experiment_trades_per_strategy_per_day": 0,
                "max_open_experiment_positions": 0,
                "use_capital_allocator": True,
            },
            "exploration": {
                **(cur.get("exploration") or {}),
                "enabled": True,
                "max_trade_notional_usd": 0,
                "max_positions": 0,
                "dynamic_formula_mode": True,
            },
            "capital_allocator": {
                **(cur.get("capital_allocator") or {}),
                "cash_reserve_weight": 0.05,
                "crypto_night_reserve_weight": 0.35,
                "max_single_stock_exposure_weight": 0.95,
                "max_single_crypto_exposure_weight": 0.95,
                "max_asset_class_exposure_weight": 1.0,
                "operator_emergency_max_open_positions": 0,
            },
        },
    )
    cfg_mgr._activate(merged, operator, "start_fresh_paper_learning")

    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    sched_out = AutonomousPaperScheduler(session, cfg_mgr.get_current()).enable(operator)

    log_activity(
        session,
        "start_fresh_paper_learning",
        "Fresh paper learning started — push-pull ready",
        {"operator": operator, "at": datetime.utcnow().isoformat() + "Z"},
    )
    session.flush()

    display = paper_learning_display_status(session, cfg_mgr.get_current())
    blockers = compute_push_pull_blockers(session, cfg_mgr.get_current())
    return {
        "status": "ok",
        "message": "Fresh paper learning started. Scheduler will run push-pull ticks. Live remains locked.",
        "current_mode": "push_pull_paper_learning",
        "paper_orders_enabled": True,
        "mode_enabled": True,
        "scheduler_enabled": True,
        "can_place_paper_orders": blockers.get("can_place_paper_orders"),
        "scheduler": sched_out,
        "live_lock_status": lock.get("live_lock_status"),
        "live_trading_enabled": False,
        "config_pause_flags_changed": False,
        "display": display,
        "blockers": blockers.get("blockers_plain", []),
    }
