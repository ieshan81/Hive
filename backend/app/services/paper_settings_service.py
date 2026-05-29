"""
Paper-trading Settings Service.

This is the operator control panel backing /api/settings/*. It surfaces and
safely mutates the PAPER-ONLY subset of config; it is forbidden from changing
any live-trading flags or broker URLs.

Hard guarantees enforced here (in addition to the central ConfigManager's
`_apply_locked_caps`):
  - `live_trading_enabled` cannot be changed; always forced False.
  - `execution.live_orders_enabled` cannot be changed; always forced False.
  - Alpaca base URL is never touched.
  - Operator token is required by the router; AI actors are rejected.
  - Every mutation goes through ConfigManager._activate() so the change lands
    in `config_history` with `changed_by` + `reason`.

The service NEVER submits an order, NEVER runs a cycle, NEVER calls Gemini.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.config import settings
from app.services.broker_safety import (
    broker_base_url,
    is_paper_broker_url,
    live_lock_status,
    paper_execution_blockers,
)
from app.services.config_manager import ConfigManager

logger = logging.getLogger(__name__)

# Forbidden config paths — service refuses to write any of these.
FORBIDDEN_PATHS: frozenset[str] = frozenset({
    "live_trading_enabled",
    "execution.live_orders_enabled",
    "paper_trading_only",          # always True
    "locked_safety_caps",          # cannot mutate the safety cap definitions
    "alpaca_base_url",
    "alpaca_api_key",
    "alpaca_secret_key",
    "gemini_api_key",
    "database_url",
    "operator_secret",
    "railway_api_key",
})

# Allowed paper-only paths the operator can mutate via apply/preset.
ALLOWED_PAPER_PATHS: frozenset[str] = frozenset({
    "execution.paper_orders_enabled",
    "execution.max_orders_per_cycle",
    "execution.max_orders_per_hour",
    "execution.max_orders_per_day",
    "execution.min_seconds_between_orders_per_symbol",
    "execution.quote_max_age_seconds",
    "execution.max_paper_notional_per_trade_usd",
    "execution.duplicate_symbol_protection_enabled",
    "execution.min_trade_notional_usd",
    "autonomous_paper_learning.mode_enabled",
    "autonomous_paper_learning.scheduler_enabled",
    "autonomous_paper_learning.scheduler_interval_seconds",
    "autonomous_paper_learning.max_paper_trades_per_day",
    "autonomous_paper_learning.max_paper_notional_per_trade_usd",
    "autonomous_paper_learning.default_paper_notional_usd",
    "autonomous_paper_learning.max_open_paper_positions",
    "autonomous_paper_learning.max_daily_paper_loss_pct",
    "autonomous_paper_learning.max_weekly_paper_loss_pct",
    "portfolio.max_concurrent_positions",
    "portfolio.max_total_exposure_pct",
    "portfolio.reserve_cash_pct",
    "risk.daily_drawdown_pct",
    "risk.max_drawdown_pct",
    "risk.max_exposure_per_symbol_pct",
    "min_edge_after_cost_bps",
})


def _get_at(cfg: dict, path: str) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_at(cfg: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = cfg
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _paper_subset(cfg: dict) -> dict[str, Any]:
    return {p: _get_at(cfg, p) for p in sorted(ALLOWED_PAPER_PATHS)}


# ──────────────────────────────────────────────────────────────────────
# Status / readiness
# ──────────────────────────────────────────────────────────────────────

def settings_status(session: Session) -> dict[str, Any]:
    """READ ONLY: full system mode + paper-trading config snapshot."""
    cfg = ConfigManager(session).get_current()
    live = live_lock_status(cfg)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "system_mode": {
            "environment_mode": str(cfg.get("environment_mode", "paper")),
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "live_lock_status": live.get("live_lock_status"),
            "broker_base_url": broker_base_url(),
            "broker_mode_detected": "paper" if is_paper_broker_url() else "non_paper_blocked",
            "alpaca_connected": bool(settings.alpaca_configured),
            "gemini_configured": bool(settings.gemini_configured),
            "database_configured": bool(settings.database_configured),
        },
        "paper_subset": _paper_subset(cfg),
        "live_subset_readonly": {
            "live_trading_enabled": bool(cfg.get("live_trading_enabled", False)),
            "execution.live_orders_enabled": bool((cfg.get("execution") or {}).get("live_orders_enabled", False)),
            "note": "Live trading cannot be enabled from this page.",
        },
        "active_config_version": int(cfg.get("config_version", 0) or 0),
    }


def paper_settings(session: Session) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "paper_subset": _paper_subset(cfg),
        "allowed_paths": sorted(ALLOWED_PAPER_PATHS),
        "forbidden_paths": sorted(FORBIDDEN_PATHS),
    }


def paper_readiness(session: Session) -> dict[str, Any]:
    """Mirrors what Cockpit shows. Submits no order."""
    cfg = ConfigManager(session).get_current()
    paper_blockers = paper_execution_blockers(cfg, alpaca_configured=settings.alpaca_configured)

    out: dict[str, Any] = {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "paper_broker_connected": is_paper_broker_url(),
        "alpaca_configured": settings.alpaca_configured,
        "paper_orders_enabled": bool((cfg.get("execution") or {}).get("paper_orders_enabled", False)),
        "paper_learning_enabled": bool((cfg.get("autonomous_paper_learning") or {}).get("mode_enabled", False)),
        "scheduler_enabled": bool((cfg.get("autonomous_paper_learning") or {}).get("scheduler_enabled", False)),
        "blockers": paper_blockers,
        "blockers_count": len(paper_blockers),
        "live_trading_unchanged": True,
        "submitted_order": False,
    }

    # Pull kill-switch + drawdown reasons honestly from existing service.
    try:
        from app.services.kill_switch_service import kill_switch_status
        ks = kill_switch_status(session)
        out["kill_switch_active"] = bool(ks.get("active") or ks.get("kill_switch_active"))
        out["kill_switch_reason"] = ks.get("reason") or ks.get("explain")
    except Exception:
        out["kill_switch_active"] = None
        out["kill_switch_reason"] = None

    try:
        from app.services.mission_control_cockpit_service import mission_control_cockpit
        cockpit = mission_control_cockpit(session)
        out["bot_can_trade"] = bool(cockpit.get("bot_can_trade") if isinstance(cockpit.get("bot_can_trade"), bool) else False)
        out["next_action"] = cockpit.get("next_action_hint") or cockpit.get("plain_message")
    except Exception:
        out["bot_can_trade"] = False
        out["next_action"] = "Mission Control unavailable — review cockpit page for full readiness."

    return out


# ──────────────────────────────────────────────────────────────────────
# Dry-run / apply (operator only — caller enforces operator token)
# ──────────────────────────────────────────────────────────────────────

PRESET_PAPER_LEARNING_NAME = "paper_learning_v1"

def _build_paper_learning_preset(current_cfg: dict) -> dict[str, Any]:
    """
    Conservative paper preset for a $200 account. Does NOT change live flags,
    does NOT change daily_drawdown_pct (operator must opt in via apply with the
    explicit acknowledgement field).
    """
    return {
        "execution.paper_orders_enabled": True,
        "execution.max_orders_per_cycle": 3,
        "execution.max_orders_per_hour": 10,
        "execution.max_orders_per_day": 25,
        "execution.min_seconds_between_orders_per_symbol": 300,
        "execution.quote_max_age_seconds": 15,
        "execution.max_paper_notional_per_trade_usd": 25,
        "execution.duplicate_symbol_protection_enabled": True,
        "execution.min_trade_notional_usd": 1,
        "autonomous_paper_learning.mode_enabled": True,
        "autonomous_paper_learning.scheduler_enabled": True,
        "autonomous_paper_learning.scheduler_interval_seconds": 120,
        "autonomous_paper_learning.max_paper_trades_per_day": 20,
        "autonomous_paper_learning.max_paper_notional_per_trade_usd": 25,
        "autonomous_paper_learning.default_paper_notional_usd": 10,
        "autonomous_paper_learning.max_open_paper_positions": 3,
        "autonomous_paper_learning.max_daily_paper_loss_pct": 3.0,
        "autonomous_paper_learning.max_weekly_paper_loss_pct": 8.0,
        "portfolio.max_concurrent_positions": 3,
        "portfolio.max_total_exposure_pct": 75.0,
        "portfolio.reserve_cash_pct": 10.0,
        "min_edge_after_cost_bps": 25,
    }


def _safety_check(changes: dict[str, Any]) -> dict[str, Any]:
    """Returns dict of safety findings. Refuses to touch forbidden paths."""
    rejected = {p: v for p, v in changes.items() if p in FORBIDDEN_PATHS}
    not_allowed = {p: v for p, v in changes.items() if p not in ALLOWED_PAPER_PATHS and p not in FORBIDDEN_PATHS}
    return {
        "rejected_forbidden_paths": list(rejected.keys()),
        "rejected_unknown_paths": list(not_allowed.keys()),
        "live_trading_unchanged": True,
        "submitted_order": False,
    }


def _apply_changes_to_cfg(base_cfg: dict, changes: dict[str, Any]) -> tuple[dict, dict[str, Any], dict[str, Any]]:
    """Returns (new_cfg, old_subset, new_subset). Only ALLOWED paths land."""
    new_cfg = copy.deepcopy(base_cfg)
    old_subset: dict[str, Any] = {}
    new_subset: dict[str, Any] = {}
    for path, value in changes.items():
        if path not in ALLOWED_PAPER_PATHS:
            continue
        old_subset[path] = _get_at(base_cfg, path)
        _set_at(new_cfg, path, value)
        new_subset[path] = value
    # Hard-force the live flags off no matter what the merge tried to do.
    new_cfg["live_trading_enabled"] = False
    new_cfg.setdefault("execution", {})["live_orders_enabled"] = False
    new_cfg["paper_trading_only"] = True
    return new_cfg, old_subset, new_subset


def dry_run(session: Session, body: dict, *, actor: str = "operator") -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    preset_name = body.get("preset")
    if preset_name == PRESET_PAPER_LEARNING_NAME:
        changes = _build_paper_learning_preset(cfg)
    else:
        changes = body.get("changes") or {}

    safety = _safety_check(changes)
    new_cfg, old_subset, new_subset = _apply_changes_to_cfg(cfg, changes)

    return {
        "status": "ok",
        "dry_run": True,
        "preset_applied": preset_name,
        "actor": actor,
        "old_config_subset": old_subset,
        "new_config_subset": new_subset,
        "changed_keys": list(new_subset.keys()),
        "rejected_paths": safety["rejected_forbidden_paths"] + safety["rejected_unknown_paths"],
        "safety_checks": safety,
        "live_trading_unchanged": True,
        "submitted_order": False,
        "next_step": "POST /api/settings/paper-trading/apply with the same body and confirmation phrase.",
    }


def apply(session: Session, body: dict, *, actor: str = "operator", actor_type: Optional[str] = None) -> dict[str, Any]:
    if str(actor_type or "").lower() == "ai":
        return {
            "status": "rejected",
            "reason": "ai_actor_not_allowed",
            "live_trading_unchanged": True,
            "submitted_order": False,
        }

    confirmation = str(body.get("confirmation") or body.get("confirmation_phrase") or "").strip().upper()
    required = "APPLY PAPER LEARNING PRESET"
    preset_name = body.get("preset")
    if preset_name == PRESET_PAPER_LEARNING_NAME and confirmation != required:
        return {
            "status": "rejected",
            "reason": "missing_confirmation_phrase",
            "required_phrase": required,
            "live_trading_unchanged": True,
            "submitted_order": False,
        }

    cfg = ConfigManager(session).get_current()
    if preset_name == PRESET_PAPER_LEARNING_NAME:
        changes = _build_paper_learning_preset(cfg)
        reason = "Paper Learning preset applied"
    else:
        changes = body.get("changes") or {}
        reason = body.get("reason") or "Operator paper-trading settings update"

    safety = _safety_check(changes)
    new_cfg, old_subset, new_subset = _apply_changes_to_cfg(cfg, changes)

    if not new_subset:
        return {
            "status": "noop",
            "reason": "no_allowed_changes",
            "rejected_paths": safety["rejected_forbidden_paths"] + safety["rejected_unknown_paths"],
            "live_trading_unchanged": True,
            "submitted_order": False,
        }

    activated = ConfigManager(session)._activate(new_cfg, changed_by=actor, reason=reason)

    return {
        "status": "ok",
        "dry_run": False,
        "preset_applied": preset_name,
        "actor": actor,
        "config_version": getattr(activated, "version", None),
        "old_config_subset": old_subset,
        "new_config_subset": new_subset,
        "changed_keys": list(new_subset.keys()),
        "rejected_paths": safety["rejected_forbidden_paths"] + safety["rejected_unknown_paths"],
        "safety_checks": safety,
        "live_trading_unchanged": True,
        "submitted_order": False,
        "reason": reason,
    }


def set_paper_orders(session: Session, *, enabled: bool, actor: str = "operator", actor_type: Optional[str] = None) -> dict[str, Any]:
    return apply(
        session,
        {"changes": {"execution.paper_orders_enabled": bool(enabled)}, "reason": ("Paper orders enabled" if enabled else "Paper orders disabled")},
        actor=actor,
        actor_type=actor_type,
    )


def set_paper_learning(session: Session, *, enabled: bool, actor: str = "operator", actor_type: Optional[str] = None) -> dict[str, Any]:
    return apply(
        session,
        {
            "changes": {
                "autonomous_paper_learning.mode_enabled": bool(enabled),
                "autonomous_paper_learning.scheduler_enabled": bool(enabled),
            },
            "reason": ("Paper learning resumed" if enabled else "Paper learning paused"),
        },
        actor=actor,
        actor_type=actor_type,
    )
