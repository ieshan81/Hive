"""Classify paper-autopilot block reasons into freeze/rotate/repair outcomes."""

from __future__ import annotations

from typing import Any


HARD_SAFETY = {
    "broker_not_synced",
    "broker_not_paper",
    "live_locked",
    "live_lock_not_locked",
    "live_trading_flag_set",
    "KILL_SWITCH_ACTIVE",
    "kill_switch_active",
    "RECONCILIATION_DRIFT",
    "reconciliation_drift",
    "DUPLICATE_SYMBOL_POSITION",
    "OPEN_POSITION_MISSING_EXIT_PLAN",
    "FROZEN_UNRESOLVED_EXIT",
    "BROKER_NOT_PAPER",
    "LIVE_TRADING_LOCKED",
}

CANDIDATE_ROTATE = {
    "spread_check",
    "SPREAD_WIDENED",
    "SPREAD_WIDENED_COOLDOWN",
    "weak_edge",
    "WEAK_EDGE_AFTER_COST",
    "low_signal_score",
    "WEAK_SIGNAL",
    "LOW_PROFIT_SYMBOL_COOLDOWN",
    "COOLDOWN_AFTER_EXIT",
    "CHURN_GUARD",
    "research_reject",
    "sentiment_weak",
    "liquidity_check",
    "data_stale",
    "STALE_QUOTE",
    "ADAPTIVE_BUDGET_BLOCKED",
}

STALE_REPAIR = {
    "duplicate_buy",
    "stale_open_position_blocks_entry",
    "broker_flat_local_stale",
}


def classify_block_reason(reason: str | None) -> dict[str, Any]:
    code = str(reason or "unknown")
    if code in STALE_REPAIR or code.lower() in STALE_REPAIR:
        cls = "stale_state_repair"
        rotate = False
        freeze = False
        repair = True
    elif code in HARD_SAFETY:
        cls = "hard_safety_block"
        rotate = False
        freeze = True
        repair = False
    elif code in CANDIDATE_ROTATE:
        cls = "candidate_rejection_rotate"
        rotate = True
        freeze = False
        repair = False
    else:
        cls = "candidate_rejection_rotate"
        rotate = True
        freeze = False
        repair = False
    return {
        "blocked_reason_class": cls,
        "should_rotate": rotate,
        "should_freeze": freeze,
        "repair_attempted": repair,
    }
