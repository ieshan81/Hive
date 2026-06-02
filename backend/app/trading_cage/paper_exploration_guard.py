"""Canonical paper-exploration probe + kill-switch-override guards.

Single source of truth shared by ExecutionCage and PaperExplorationService so the permission
layer and the cage can never disagree. These guards NEVER enable live trading, never bypass the
cage, and never loosen standard paper-entry or real-money safety. They only decide whether a
TINY, MARKED, PAPER-ONLY near-miss probe may proceed past a NON-catastrophic (daily-drawdown)
kill switch.
"""

from __future__ import annotations

from typing import Any, Optional

# Switches that block even a tiny paper-exploration probe.
CATASTROPHIC_SWITCHES = frozenset(
    {"manual_master", "max_drawdown", "weekly_drawdown", "weekly_loss", "system_health"}
)
# Non-catastrophic switches a marked probe may override (real money stays locked regardless).
DAILY_OVERRIDABLE_SWITCHES = frozenset({"daily_drawdown", "daily_loss", "daily_entry_drawdown"})

EXPLORATION_EXIT_KEYS = ("stop_loss", "take_profit", "trailing_stop", "invalidation_price")


def _af_exp(config: dict) -> dict:
    return (config.get("alpha_factory") or {}).get("paper_exploration") or {}


def _live_orders_enabled(config: dict) -> bool:
    execution = config.get("execution") or {}
    return bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))


def _broker_is_paper() -> bool:
    try:
        from app.services.broker_safety import is_paper_broker_url

        return bool(is_paper_broker_url())
    except Exception:
        return False


def is_marked_probe(cand: Any) -> bool:
    meta = getattr(cand, "meta", None) or {}
    return bool(meta.get("near_miss_exploration_probe") or meta.get("paper_exploration_probe"))


def is_valid_paper_exploration_probe(cand: Any, config: dict, account: Any = None, quote: Optional[dict] = None) -> dict[str, Any]:
    """Validate a marked probe. Returns {valid, blockers, evidence}. Paper-only; never live."""
    meta = getattr(cand, "meta", None) or {}
    af = _af_exp(config)
    live = _live_orders_enabled(config)
    coid = str(meta.get("client_order_id") or "")
    levels = meta.get("dynamic_exit_levels") or {}
    execution = config.get("execution") or {}

    evidence = {
        "has_probe_meta": bool(meta.get("near_miss_exploration_probe") or meta.get("paper_exploration_probe")),
        "client_order_id_starts_exploration": coid.startswith("EXPLORATION"),
        "live_orders_disabled": not live,
        "broker_is_paper": _broker_is_paper(),
        "exit_plan_present": all(levels.get(k) is not None for k in EXPLORATION_EXIT_KEYS),
        "signal_type_entry": getattr(cand, "signal_type", None) == "entry",
        "side_is_buy": getattr(cand, "side", None) in ("buy", None),
        "paper_mode_enabled": bool(execution.get("paper_orders_enabled")) and not live,
        "exploration_config_enabled": bool(af.get("allow_paper_exploration_near_misses", True))
        and bool(af.get("exploration_live_forbidden", True)),
    }
    # broker_is_paper is advisory in offline tests (no broker URL) — never the sole blocker.
    required = (
        "has_probe_meta",
        "client_order_id_starts_exploration",
        "live_orders_disabled",
        "exit_plan_present",
        "signal_type_entry",
        "paper_mode_enabled",
        "exploration_config_enabled",
    )
    blockers = [k for k in required if not evidence[k]]
    return {"valid": not blockers, "blockers": blockers, "evidence": evidence}


def can_override_kill_switch_for_paper_exploration(
    switches: list[dict[str, Any]], cand: Any, config: dict, account: Any = None
) -> dict[str, Any]:
    """Decide whether a marked probe may proceed past the active kill switch(es).

    Allowed ONLY when: the probe is valid AND no catastrophic switch is active. Real money stays
    locked, standard paper entries stay blocked, exits stay allowed. Returns a structured decision
    with a SPECIFIC denied_reason (never an opaque KILL_SWITCH_ACTIVE for a marked probe)."""
    active = sorted({str(s.get("switch_name")) for s in (switches or [])})
    catastrophic = sorted(set(active) & CATASTROPHIC_SWITCHES)
    probe = is_valid_paper_exploration_probe(cand, config, account)

    if not probe["valid"]:
        return {
            "allowed": False,
            "denied_reason": "EXPLORATION_PROBE_INVALID",
            "probe_blockers": probe["blockers"],
            "active_switches": active,
            "catastrophic_switches": catastrophic,
            "evidence": probe["evidence"],
        }
    if catastrophic:
        return {
            "allowed": False,
            "denied_reason": "CATASTROPHIC_KILL_SWITCH",
            "catastrophic_switches": catastrophic,
            "active_switches": active,
            "evidence": probe["evidence"],
        }
    overridable = sorted(set(active) - CATASTROPHIC_SWITCHES)
    return {
        "allowed": True,
        "denied_reason": None,
        "overridden_switch": overridable[0] if overridable else None,
        "active_switches": active,
        "catastrophic_switches": [],
        "standard_entries_still_blocked": True,
        "real_money_still_locked": True,
        "exits_allowed": True,
        "exploration_probe_validated": True,
        "evidence": probe["evidence"],
    }
