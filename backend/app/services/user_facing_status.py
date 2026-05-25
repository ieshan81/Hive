"""Plain-language status helpers for APIs and diagnostic bundle."""

from __future__ import annotations

from typing import Any

BLOCKER_LABELS: dict[str, str] = {
    "fast_training_loop_disabled": "Fast training loop is off (by design on Railway).",
    "training_mode_disabled": "Training Mode is OFF — the bot cannot open new paper trades.",
    "fast_training_execute_orders_disabled": "Order execution is disabled in settings.",
    "reconciliation:ghost_position_candidates": "A local/broker position mismatch needs review.",
    "reconciliation:doge_availability_conflict": "Broker shows a position but available sell qty was zero.",
    "reconciliation:local_ghost_position": "Local database shows a position the broker does not hold.",
    "reconciliation:broker_activity_mismatch": "Broker activity does not match order history.",
    "open_position_blocks_duplicate_entry": "An open broker position blocks a duplicate entry.",
    "open_position_exists": "Historical record only — broker holds no open position for this symbol.",
    "BROKER_NOT_PAPER": "Broker URL is not paper — all submissions blocked.",
    "ALPACA_NOT_CONFIGURED": "Alpaca credentials are not configured.",
    "PAPER_EXECUTION_DISABLED": "Paper order execution is disabled in settings.",
    "KILL_SWITCH_ACTIVE": "Kill switch is active.",
}

CLASSIFICATION_LABELS: dict[str, str] = {
    "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY": "Broker holds no position. Old buy is history only.",
    "BROKER_AVAILABILITY_CONFLICT": "Broker position exists but available qty was zero on exit.",
    "LOCAL_STALE_POSITION": "Local record mismatch — broker is flat.",
    "BROKER_ACTIVITY_MISMATCH": "Broker activity does not match stored orders.",
}


def friendly_blockers(blockers: list[str]) -> list[str]:
    out = []
    for b in blockers:
        if b in BLOCKER_LABELS:
            out.append(BLOCKER_LABELS[b])
        elif b.startswith("reconciliation:"):
            out.append(f"Reconciliation: {b.split(':', 1)[-1].replace('_', ' ')}")
        elif b.startswith("open_position"):
            out.append(BLOCKER_LABELS.get("open_position_exists", b.replace("_", " ")))
        else:
            out.append(b.replace("_", " ").capitalize())
    return out


def wrap_status_payload(
    payload: dict[str, Any],
    *,
    plain_message: str,
    user_facing_status: str,
    action_required: str | None = None,
    safe_actions: list[str] | None = None,
    dangerous_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        **payload,
        "plain_message": plain_message,
        "user_facing_status": user_facing_status,
        "action_required": action_required,
        "safe_actions": safe_actions or ["resync_broker_truth", "download_diagnostic_bundle", "view_hive_brain"],
        "dangerous_actions": dangerous_actions or [],
    }


def trade_broker_status(classification: str | None, *, broker_open: bool, local_qty: float) -> dict[str, str]:
    if broker_open or local_qty > 0:
        return {
            "broker_confirmed_status": "active",
            "user_status_label": "Open (broker)",
            "user_status_message": "Broker currently reports an open position.",
        }
    if classification == "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY":
        return {
            "broker_confirmed_status": "historical_only",
            "user_status_label": "Historical Only",
            "user_status_message": "Historical Only — broker holds no position for this symbol.",
        }
    if classification in ("BROKER_AVAILABILITY_CONFLICT", "LOCAL_STALE_POSITION"):
        return {
            "broker_confirmed_status": "conflict",
            "user_status_label": "Needs Review",
            "user_status_message": CLASSIFICATION_LABELS.get(classification, "Broker truth conflict."),
        }
    return {
        "broker_confirmed_status": "broker_flat",
        "user_status_label": "Flat",
        "user_status_message": "Broker reports no open position.",
    }
