"""
Gemini proposal gate — advisor outputs never apply directly.

All proposals: pending → accepted/rejected/archived (human approval required).
"""

from __future__ import annotations

import re
from typing import Any, Optional

FORBIDDEN_TARGETS = frozenset(
    {
        "execution.live_orders_enabled",
        "live_trading_enabled",
        "kill_switch_active",
        "LIVE_TRADING_ARMED",
        "execution.paper_orders_enabled",
        "promotion_stage",
        "operator_secret",
        "alpaca_secret_key",
        "alpaca_api_key",
    }
)

FORBIDDEN_PATTERNS = (
    re.compile(r"live[_\.]?trading", re.I),
    re.compile(r"disable[_\.]?safety", re.I),
    re.compile(r"bypass[_\.]?validator", re.I),
)


def validate_gemini_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Schema + safety validation for Gemini config/strategy proposals."""
    errors: list[str] = []
    ptype = str(proposal.get("type") or proposal.get("proposal_type") or "unknown")
    target = str(proposal.get("target") or proposal.get("param") or "")
    value = proposal.get("value") or proposal.get("proposed_value")
    evidence = proposal.get("evidence") or proposal.get("evidence_used")

    if target in FORBIDDEN_TARGETS:
        errors.append(f"Forbidden target: {target}")
    for pat in FORBIDDEN_PATTERNS:
        if pat.search(str(proposal)):
            errors.append(f"Forbidden pattern in proposal: {pat.pattern}")

    if not evidence and ptype in ("parameter_change_proposal", "config_change_proposal"):
        errors.append("Missing required evidence for parameter change")

    old = proposal.get("current_value")
    if old is not None and value is not None:
        try:
            o, n = float(old), float(value)
            if o != 0 and abs(n - o) / abs(o) > 0.5:
                errors.append("Parameter change exceeds 50% single-step limit")
        except (TypeError, ValueError):
            pass

    return {
        "valid": len(errors) == 0,
        "status": "pending" if len(errors) == 0 else "rejected",
        "errors": errors,
        "proposal_type": ptype,
        "requires_human_approval": True,
        "can_auto_apply": False,
        "gemini_can_trade": False,
    }
