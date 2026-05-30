"""Single source of truth for what the AI advisor may and may not do.

The AI (Gemini / "ai_advisor") is an ADVISORY reviewer. It MAY read state, write
*pending* lessons/memories, summarize/explain outcomes, and *propose* parameter
changes. It may NEVER:

  - place, cancel, or liquidate orders/positions
  - enable live trading or change the live lock
  - disable or weaken the kill switch / risk caps / absolute autopilot caps
  - apply config directly (proposals require operator approval + validator)
  - bypass the operator token or the execution cage
  - deploy or merge code

Every mutating API route is additionally protected by the operator token; this
module is the defense-in-depth *policy* layer plus the allowlist used to classify
AI config proposals. Nothing here executes anything — pure policy/classification.
"""

from __future__ import annotations

from typing import Any

# Actor strings that identify a non-human / AI caller.
AI_FORBIDDEN_ACTORS = frozenset(
    {
        "ai",
        "gemini",
        "agent",
        "ai_advisor",
        "ai_advisory",
        "ai_research",
        "llm",
        "claude",
        "auto",
        "autopilot",
    }
)

# Capability matrix — the /ai-advisor/capabilities route mirrors this verbatim.
AI_CAPABILITIES: dict[str, Any] = {
    "can_submit_orders": False,
    "can_cancel_orders": False,
    "can_liquidate_positions": False,
    "can_change_live_lock": False,
    "can_enable_live_trading": False,
    "can_disable_kill_switch": False,
    "can_apply_config_directly": False,
    "can_change_risk_or_caps": False,
    "can_bypass_operator_token": False,
    "can_bypass_execution_cage": False,
    "can_deploy_or_merge": False,
    "can_write_pending_memories": True,
    "can_summarize_or_explain": True,
    "can_propose_param_changes": True,
    "can_propose_backtests": True,
    "validator_required_for_proposals": True,
    "operator_approval_required_for_apply": True,
    "max_param_delta_per_cycle_pct": 50,
    "role": "advisory_reviewer_only",
}

# Config keys/prefixes the AI may NEVER propose to change (auto OR via proposal).
# Matched as dotted-path prefixes against proposed change keys.
AI_CONFIG_FORBIDDEN_PREFIXES = (
    "live_trading_enabled",
    "paper_trading_only",
    "execution.live_orders_enabled",
    "execution.paper_orders_enabled",
    "promotion.",
    "kill.",
    "risk.",
    "operator",
    "broker",
    "alpaca",
    "locked_config_keys",
    "autonomous_paper_learning.scheduler_enabled",
    "autonomous_paper_learning.mode_enabled",
    "autonomous_paper_learning.absolute_max_",
    "autonomous_paper_learning.auto_pause_after_",
    "autonomous_paper_learning.no_averaging_down",
    "autonomous_paper_learning.no_duplicate_symbol_buy",
    "autonomous_paper_learning.block_new_entry_if_unmanaged_position",
    "autonomous_paper_learning.use_capital_allocator",
)

# Paper-only-safe keys the AI MAY propose AND that MAY auto-apply (still paper).
# Deliberately narrow: learning/scan tunables that cannot loosen a safety cage,
# enable live, or affect order placement directly.
AI_CONFIG_PAPER_SAFE_ALLOWLIST = (
    "autonomous_paper_learning.refresh_lookback_hours",
    "autonomous_paper_learning.run_backtest_lab_every_n_ticks",
    "autonomous_paper_learning.backtest_lab_limit",
    "exploration.require_stronger_edge",
    "ranking.min_rank_score",
    "universe_ranking.min_rank_score",
)


def is_ai_actor(actor: Any) -> bool:
    return str(actor or "").strip().lower() in AI_FORBIDDEN_ACTORS


def assert_actor_not_ai(actor: Any, *, action: str = "this action") -> None:
    """Raise PermissionError if the actor is an AI / non-human caller."""
    if is_ai_actor(actor):
        raise PermissionError(f"AI/advisory actors may not perform {action}; operator required.")


def _matches(key: str, prefixes: tuple[str, ...]) -> bool:
    k = str(key or "")
    return any(k == p or k.startswith(p) for p in prefixes)


def is_forbidden_config_key(key: str) -> bool:
    return _matches(key, AI_CONFIG_FORBIDDEN_PREFIXES)


def is_paper_safe_config_key(key: str) -> bool:
    return _matches(key, AI_CONFIG_PAPER_SAFE_ALLOWLIST) and not is_forbidden_config_key(key)


def _flatten_keys(changes: dict, prefix: str = "") -> list[str]:
    out: list[str] = []
    for key, value in (changes or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out.extend(_flatten_keys(value, prefix=f"{path}."))
        else:
            out.append(path)
    return out


def classify_config_proposal(changes: dict) -> dict[str, list[str]]:
    """Split proposed dotted-path changes into auto-applicable / operator-required / forbidden.

    ``forbidden`` keys must be dropped entirely (the AI may not touch them even
    via an operator-approved proposal — they require a deliberate operator config
    edit). ``auto_applicable`` keys are paper-safe enough to apply without operator
    sign-off *if* an operator has enabled auto-apply. Everything else needs
    explicit operator approval.
    """
    auto: list[str] = []
    operator_required: list[str] = []
    forbidden: list[str] = []
    for key in _flatten_keys(changes):
        if is_forbidden_config_key(key):
            forbidden.append(key)
        elif is_paper_safe_config_key(key):
            auto.append(key)
        else:
            operator_required.append(key)
    return {
        "auto_applicable": auto,
        "requires_operator": operator_required,
        "forbidden": forbidden,
    }
