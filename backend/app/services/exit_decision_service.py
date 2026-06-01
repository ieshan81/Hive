"""Canonical exit reason classification for paper positions."""

from __future__ import annotations

from typing import Any


def classify_exit_decision(review: dict[str, Any]) -> dict[str, Any]:
    reason = str(review.get("reason") or "").lower()
    action = str(review.get("action") or "hold")
    if action != "exit_recommended":
        cls = "no_exit_hold"
    elif "stop" in reason:
        cls = "stop_loss_exit"
    elif "take_profit" in reason or "target" in reason:
        cls = "take_profit_exit"
    elif "invalidat" in reason or "reversal" in reason:
        cls = "signal_invalidated_exit"
    elif "max_hold" in reason or "time" in reason:
        cls = "max_hold_exit"
    elif "risk" in reason or "loss_band" in reason or "unrealized_loss" in reason:
        cls = "risk_exit"
    elif "manual" in reason:
        cls = "manual_exit"
    else:
        cls = "risk_exit"
    return {
        "exit_decision": cls,
        "time_alone_forced_loss_exit": False if reason == "max_hold_extended_fee_negative" else None,
        "stored_exit_reason": review.get("reason"),
    }
