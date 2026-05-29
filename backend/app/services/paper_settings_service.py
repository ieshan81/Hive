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
    # Entry kill-switch thresholds (the keys KillSwitchService actually reads).
    # Mutating these is paper-only operational config and goes through the
    # same operator-token + ConfigManager audit path. Live flags are still
    # untouchable (FORBIDDEN_PATHS).
    "kill.daily_drawdown_pct",
    "kill.weekly_drawdown_pct",
    "kill.max_drawdown_pct",
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
    """
    Mirrors Cockpit/Mission Control truth exactly.

    Uses the canonical sources:
      - mission_control_read_model.build_mission_control_status(session)
      - KillSwitchService(session, cfg).status()  (NOT a nonexistent
        standalone kill_switch_status function — that was the bug)

    Returns a FLAT response matching what PaperSettingsPanel renders.
    Submits no order. Never touches live flags.
    """
    cfg = ConfigManager(session).get_current()
    paper_blockers = paper_execution_blockers(cfg, alpaca_configured=settings.alpaca_configured)

    # Canonical readiness from Mission Control (paper_execution block)
    mc_status: dict[str, Any] = {}
    paper_exec: dict[str, Any] = {}
    try:
        from app.services.mission_control_read_model import build_mission_control_status
        mc_status = build_mission_control_status(session) or {}
        paper_exec = mc_status.get("paper_execution") or {}
    except Exception:
        # Mission Control should always work; if it doesn't, fall back to
        # config-level signals but still surface a flat shape.
        paper_exec = {}

    # Kill-switch truth — direct from the existing service (not a renamed alias).
    kill_status: dict[str, Any] = paper_exec.get("kill_switch") or {}
    if not kill_status:
        try:
            from app.services.kill_switch_service import KillSwitchService
            kill_status = KillSwitchService(session, cfg).status() or {}
        except Exception:
            kill_status = {}

    entries_allowed = bool(kill_status.get("entries_allowed", True))
    kill_switch_active = not entries_allowed
    active_switches = kill_status.get("active_switches") or []
    kill_switch_reason: str | None = None
    if active_switches and isinstance(active_switches[0], dict):
        kill_switch_reason = str(active_switches[0].get("message") or active_switches[0].get("switch_name") or "")
    elif kill_switch_active:
        kill_switch_reason = "Kill switch active — see cockpit for details."

    # Prefer Mission Control's flat fields; fall back to config reads.
    paper_broker_connected = bool(paper_exec.get("paper_broker_connected", paper_exec.get("paper_broker", is_paper_broker_url())))
    paper_orders_enabled = bool(paper_exec.get("paper_orders_enabled", (cfg.get("execution") or {}).get("paper_orders_enabled", False)))
    paper_learning_enabled = bool(paper_exec.get("paper_learning_on", (cfg.get("autonomous_paper_learning") or {}).get("mode_enabled", False)))
    scheduler_enabled = bool(paper_exec.get("scheduler_enabled", (cfg.get("autonomous_paper_learning") or {}).get("scheduler_enabled", False)))
    bot_can_trade = bool(paper_exec.get("can_place_paper_orders_now", False))

    # Merge readiness blockers: paper execution preflight + Mission Control
    mc_blockers = paper_exec.get("blockers") or []
    blockers: list[str] = []
    for b in list(paper_blockers) + list(mc_blockers):
        if b and b not in blockers:
            blockers.append(b)

    next_action = paper_exec.get("next_action") or mc_status.get("next_recommended_operator_action")
    if not next_action:
        if kill_switch_active and kill_switch_reason:
            next_action = kill_switch_reason
        elif blockers:
            next_action = blockers[0]
        else:
            next_action = "Paper entries may submit when a candidate passes the cage."

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "paper_broker_connected": paper_broker_connected,
        "alpaca_configured": settings.alpaca_configured,
        "paper_orders_enabled": paper_orders_enabled,
        "paper_learning_enabled": paper_learning_enabled,
        "scheduler_enabled": scheduler_enabled,
        "kill_switch_active": kill_switch_active,
        "kill_switch_reason": kill_switch_reason,
        "active_kill_switches": active_switches,
        "bot_can_trade": bot_can_trade,
        "blockers": blockers,
        "blockers_count": len(blockers),
        "next_action": next_action,
        # Drawdown context surfaces the kill-switch thresholds the operator can
        # change explicitly via /api/settings/paper-trading/set-drawdown-limit.
        "drawdown": {
            "daily_pl_pct": kill_status.get("account_daily_pl_pct"),
            "drawdown_pct": kill_status.get("account_drawdown_pct"),
            "daily_limit_pct": float((cfg.get("kill") or {}).get("daily_drawdown_pct", 2.0)),
            "max_limit_pct": float((cfg.get("kill") or {}).get("max_drawdown_pct", 15.0)),
            "weekly_limit_pct": float((cfg.get("kill") or {}).get("weekly_drawdown_pct", 5.0)),
        },
        "live_trading_unchanged": True,
        "submitted_order": False,
    }


# ──────────────────────────────────────────────────────────────────────
# Dry-run / apply (operator only — caller enforces operator token)
# ──────────────────────────────────────────────────────────────────────

PRESET_PAPER_LEARNING_NAME = "paper_learning_v1"

# Paths the preset MUST NEVER include. The drawdown kill switch is mutated
# only via the dedicated set_paper_daily_drawdown action so the operator
# decision is always explicit and individually audited.
PRESET_PROHIBITED_PATHS: frozenset[str] = frozenset({
    "kill.daily_drawdown_pct",
    "kill.weekly_drawdown_pct",
    "kill.max_drawdown_pct",
    "risk.daily_drawdown_pct",
    "risk.max_drawdown_pct",
    "live_trading_enabled",
    "execution.live_orders_enabled",
})


def _build_paper_learning_preset(current_cfg: dict) -> dict[str, Any]:
    """
    Conservative paper preset for a $200 account. Does NOT change live flags,
    does NOT change daily_drawdown_pct (operator must opt in via apply with the
    explicit acknowledgement field).
    """
    preset = {
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
    # Defensive guard — if a future edit accidentally adds a prohibited key,
    # strip it. The preset MUST stay isolated from drawdown and live flags.
    for forbidden in list(preset.keys()):
        if forbidden in PRESET_PROHIBITED_PATHS:
            preset.pop(forbidden, None)
    return preset


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


# Explicit, deliberately separate operator action — NOT bundled into the
# preset. Mutates only kill.daily_drawdown_pct. Same safety contract as
# everything else in this module: paper-only, audited, no order submission,
# no live-flag changes.
PAPER_DRAWDOWN_CONFIRMATION = "SET PAPER DAILY DRAWDOWN"
MIN_DAILY_DRAWDOWN_PCT = 0.25
MAX_DAILY_DRAWDOWN_PCT = 10.0


def _drawdown_safety_check(new_pct: float) -> tuple[bool, str]:
    if not isinstance(new_pct, (int, float)):
        return False, "value_must_be_numeric"
    if new_pct < MIN_DAILY_DRAWDOWN_PCT or new_pct > MAX_DAILY_DRAWDOWN_PCT:
        return False, f"value_out_of_range_{MIN_DAILY_DRAWDOWN_PCT}_to_{MAX_DAILY_DRAWDOWN_PCT}"
    return True, "ok"


def set_paper_daily_drawdown(
    session: Session,
    body: dict,
    *,
    actor: str = "operator",
    actor_type: Optional[str] = None,
) -> dict[str, Any]:
    """
    Explicit paper-only operator action.

    - Requires actor_type != "ai"
    - Requires confirmation phrase: "SET PAPER DAILY DRAWDOWN"
    - Only mutates `kill.daily_drawdown_pct`
    - Never touches live flags, broker URL, secrets
    - Submits no order, runs no cycle
    """
    if str(actor_type or "").lower() == "ai":
        return {
            "status": "rejected",
            "reason": "ai_actor_not_allowed",
            "live_trading_unchanged": True,
            "submitted_order": False,
        }

    confirmation = str(body.get("confirmation") or body.get("confirmation_phrase") or "").strip().upper()
    if confirmation != PAPER_DRAWDOWN_CONFIRMATION:
        return {
            "status": "rejected",
            "reason": "missing_confirmation_phrase",
            "required_phrase": PAPER_DRAWDOWN_CONFIRMATION,
            "live_trading_unchanged": True,
            "submitted_order": False,
        }

    try:
        new_pct = float(body.get("daily_drawdown_pct"))
    except (TypeError, ValueError):
        return {
            "status": "rejected",
            "reason": "invalid_daily_drawdown_pct",
            "live_trading_unchanged": True,
            "submitted_order": False,
        }
    ok, reason = _drawdown_safety_check(new_pct)
    if not ok:
        return {
            "status": "rejected",
            "reason": reason,
            "min": MIN_DAILY_DRAWDOWN_PCT,
            "max": MAX_DAILY_DRAWDOWN_PCT,
            "live_trading_unchanged": True,
            "submitted_order": False,
        }

    cfg = ConfigManager(session).get_current()
    old_value = (cfg.get("kill") or {}).get("daily_drawdown_pct", None)
    changes = {"kill.daily_drawdown_pct": round(new_pct, 4)}
    new_cfg, old_subset, new_subset = _apply_changes_to_cfg(cfg, changes)
    activated = ConfigManager(session)._activate(
        new_cfg,
        changed_by=actor,
        reason=f"Operator set paper daily drawdown limit to {new_pct}% via explicit action",
    )

    # Readiness after change — useful for the UI to confirm the blocker cleared.
    readiness_after = paper_readiness(session)

    return {
        "status": "ok",
        "dry_run": False,
        "actor": actor,
        "config_version": getattr(activated, "version", None),
        "changed_keys": list(new_subset.keys()),
        "old_config_subset": {**old_subset, "kill.daily_drawdown_pct": old_value},
        "new_config_subset": new_subset,
        "safety_checks": {
            "rejected_forbidden_paths": [],
            "rejected_unknown_paths": [],
            "live_trading_unchanged": True,
            "submitted_order": False,
        },
        "readiness_after_change": readiness_after,
        "live_trading_unchanged": True,
        "submitted_order": False,
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
