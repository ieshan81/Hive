"""Control Center — merged Settings + Danger Zone operator surface."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.product_truth_service import product_truth


def control_center_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    truth = product_truth(session, cfg)
    env = env_pause_status()
    lock = live_lock_tripwire_status(cfg)
    pp = cfg.get("push_pull") or {}
    risk = cfg.get("risk") or {}
    portfolio = cfg.get("portfolio") or {}

    return {
        "status": "ok",
        "schema_version": 1,
        "system_state": {
            "paper_learning": "On" if truth.get("operator_desired_paper_learning") else "Off",
            "scheduler": "On" if truth.get("operator_desired_scheduler") else "Off",
            "paper_execution": "On" if truth.get("operator_desired_paper_execution") else "Off",
            "live_locked": lock.get("live_lock_status") == "locked",
            "env_pause": "On" if env.get("any_env_pause") else "Off",
            "broker_sync": truth.get("paper_broker_status"),
        },
        "risk_cage": {
            "daily_loss_limit_pct": risk.get("risk_pct_paper", cfg.get("daily_loss_limit_pct", 0.02)),
            "max_open_positions": portfolio.get("max_concurrent_positions", 2),
            "cash_reserve_pct": portfolio.get("reserve_cash_pct", 60),
            "max_per_symbol_exposure_pct": risk.get("max_exposure_per_symbol_pct", 20),
            "stale_quote_limit_seconds": (cfg.get("execution") or {}).get("quote_max_age_seconds", 30),
            "stale_bar_limit_minutes": pp.get("max_bar_age_minutes", 120),
            "reconciliation_drift_halt_bps": risk.get("reconciliation_drift_halt_bps", 5),
        },
        "strategy_parameters": {
            "push_strength_min": pp.get("push_strength_min", 0.004),
            "max_spread_bps": pp.get("max_spread_bps", 50),
            "min_edge_after_cost_bps": pp.get("min_edge_after_cost_bps", 50),
            "atr_stop_multiplier": pp.get("atr_stop_multiplier", 2.0),
            "profit_target_bps": pp.get("profit_target_bps", 300),
            "timeout_minutes": pp.get("timeout_minutes", 240),
            "volume_spike_min": pp.get("volume_spike_min", 1.5),
        },
        "operator_actions": [
            {"label": "Start fresh paper learning", "endpoint": "POST /api/autonomous-paper-learning/enable"},
            {"label": "Run one paper cycle", "endpoint": "POST /api/autonomous-paper-learning/run-one-cycle"},
            {"label": "Run push-pull backtest", "endpoint": "POST /api/backtesting/run-push-pull"},
            {"label": "Export diagnostic bundle (latest)", "endpoint": "GET /api/diagnostic-bundle/download?mode=latest"},
            {"label": "Repair database bootstrap", "endpoint": "POST /api/admin/repair-database-bootstrap"},
        ],
        "danger_zone": {
            "nuke_preview": "GET /api/danger-zone/nuke-everything/preview",
            "nuke_confirm_phrase": "NUKE CAGED HIVE",
            "ready_cleanup_phrase": "READY CLEANUP",
        },
        "live_trading_enabled": False,
    }
