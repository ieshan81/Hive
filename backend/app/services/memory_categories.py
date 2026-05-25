"""Memory category classification — trading, research, system, operator, AI."""

from __future__ import annotations

from typing import Optional

# Top-level categories
CATEGORY_TRADING = "trading_memory"
CATEGORY_RESEARCH = "research_memory"
CATEGORY_STRATEGY = "strategy_memory"
CATEGORY_BACKTEST = "backtest_memory"
CATEGORY_WALK_FORWARD = "walk_forward_memory"
CATEGORY_SYMBOL_PATTERN = "symbol_pattern"
CATEGORY_EXECUTION = "execution_memory"
CATEGORY_BROKER = "broker_behavior"
CATEGORY_SYSTEM = "system_issue"
CATEGORY_OPERATOR = "operator_note"
CATEGORY_AI = "ai_review_memory"
CATEGORY_LEGACY = "legacy_reference"

# Legacy type → new memory_type + category defaults
LEGACY_TYPE_MAP: dict[str, tuple[str, str]] = {
    "reconciliation_lesson": ("reconciliation_bug", CATEGORY_SYSTEM),
    "dashboard_truth_issue": ("ui_truth_bug", CATEGORY_SYSTEM),
    "position_management_issue": ("position_management_lesson", CATEGORY_TRADING),
}

TRADING_TYPES = frozenset(
    {
        "trade_lesson",
        "symbol_pattern",
        "strategy_pattern",
        "execution_lesson",
        "risk_lesson",
        "fee_lesson",
        "position_management_lesson",
        "blocked_trade_pattern",
        "broker_behavior",
        "paper_trade_filled",
        "open_position_monitor",
    }
)

RESEARCH_MEMORY_TYPES = frozenset(
    {
        "backtest_success_pattern",
        "backtest_failure_pattern",
        "walk_forward_failure",
        "walk_forward_success",
        "insufficient_walk_forward_data",
        "strategy_overfit_warning",
        "parameter_sensitivity_warning",
        "parameter_sweep_no_variation",
        "regime_dependency_pattern",
        "symbol_backtest_pattern",
        "cost_drag_pattern",
        "spread_kills_edge_pattern",
        "liquidity_filter_required",
        "exit_rule_performance_pattern",
        "rejected_strategy_memory",
        "promoted_strategy_candidate",
        "do_not_promote_recommendation",
        "sample_size_warning",
        "repeated_losing_parameter_family",
    }
)

SYSTEM_TYPES = frozenset(
    {
        "dashboard_bug",
        "export_bug",
        "reconciliation_bug",
        "serializer_bug",
        "stale_data_bug",
        "ui_truth_bug",
        "api_bug",
        "data_pipeline_bug",
        "duplicate_position_rows",
    }
)

OPERATOR_TYPES = frozenset({"operator_note", "human_review", "manual_override_note"})

AI_TYPES = frozenset(
    {
        "ai_review_issue",
        "ai_skipped_pattern",
        "ai_budget_pattern",
        "ai_config_proposal",
    }
)

LEGACY_TYPES = frozenset(
    {
        "stale_exit_detection",
        "capital_trap_detection",
        "price_divergence_guard",
        "liquidity_recovery_exit",
        "exit_worker_heartbeat",
        "repeated_warning_pattern",
    }
)

CATEGORY_COLORS = {
    CATEGORY_TRADING: "#06b6d4",
    CATEGORY_RESEARCH: "#8b5cf6",
    CATEGORY_BACKTEST: "#a855f7",
    CATEGORY_WALK_FORWARD: "#6366f1",
    CATEGORY_SYMBOL_PATTERN: "#14b8a6",
    CATEGORY_EXECUTION: "#0ea5e9",
    CATEGORY_BROKER: "#64748b",
    CATEGORY_SYSTEM: "#f97316",
    CATEGORY_AI: "#c084fc",
    CATEGORY_OPERATOR: "#94a3b8",
    CATEGORY_LEGACY: "#475569",
}

GRAPH_FILTER_CATEGORIES = {
    "trading": CATEGORY_TRADING,
    "research": CATEGORY_RESEARCH,
    "backtests": CATEGORY_BACKTEST,
    "patterns": CATEGORY_SYMBOL_PATTERN,
    "system": CATEGORY_SYSTEM,
    "ai": CATEGORY_AI,
    "operator": CATEGORY_OPERATOR,
}


def classify_memory_type(memory_type: str) -> str:
    if memory_type in RESEARCH_MEMORY_TYPES:
        if "walk_forward" in memory_type:
            return CATEGORY_WALK_FORWARD
        if "backtest" in memory_type or "overfit" in memory_type or "parameter" in memory_type:
            return CATEGORY_BACKTEST
        return CATEGORY_RESEARCH
    if memory_type in TRADING_TYPES:
        return CATEGORY_TRADING
    if memory_type in SYSTEM_TYPES:
        return CATEGORY_SYSTEM
    if memory_type in OPERATOR_TYPES:
        return CATEGORY_OPERATOR
    if memory_type in AI_TYPES:
        return CATEGORY_AI
    if memory_type in LEGACY_TYPES:
        return CATEGORY_LEGACY
    if memory_type in LEGACY_TYPE_MAP:
        return LEGACY_TYPE_MAP[memory_type][1]
    if any(x in memory_type for x in ("bug", "export", "serializer", "stale", "dashboard", "reconciliation")):
        return CATEGORY_SYSTEM
    if "ai" in memory_type or memory_type.startswith("ai_"):
        return CATEGORY_AI
    if memory_type == "operator_note":
        return CATEGORY_OPERATOR
    if "backtest" in memory_type or "walk_forward" in memory_type or "strategy" in memory_type:
        return CATEGORY_RESEARCH
    return CATEGORY_TRADING


def normalize_memory_type(memory_type: str) -> str:
    if memory_type in LEGACY_TYPE_MAP:
        return LEGACY_TYPE_MAP[memory_type][0]
    return memory_type


def default_visibility(category: str, memory_type: str, severity: str) -> dict[str, bool]:
    """Defaults for new memories."""
    if category == CATEGORY_SYSTEM:
        return {
            "visible_in_graph": False,
            "visible_to_ai": False,
            "can_influence_ranking": False,
        }
    if category == CATEGORY_LEGACY:
        return {
            "visible_in_graph": False,
            "visible_to_ai": False,
            "can_influence_ranking": False,
        }
    if category in (CATEGORY_RESEARCH, CATEGORY_BACKTEST, CATEGORY_WALK_FORWARD):
        return {
            "visible_in_graph": True,
            "visible_to_ai": True,
            "can_influence_ranking": False,
        }
    if category == CATEGORY_AI:
        return {
            "visible_in_graph": True,
            "visible_to_ai": True,
            "can_influence_ranking": False,
        }
    if category == CATEGORY_OPERATOR:
        return {
            "visible_in_graph": True,
            "visible_to_ai": True,
            "can_influence_ranking": False,
        }
    return {
        "visible_in_graph": True,
        "visible_to_ai": True,
        "can_influence_ranking": True,
    }


def drawer_title(category: str) -> str:
    if category == CATEGORY_SYSTEM:
        return "System Issue"
    if category in (CATEGORY_RESEARCH, CATEGORY_BACKTEST, CATEGORY_WALK_FORWARD):
        return "Research Memory"
    if category == CATEGORY_AI:
        return "AI Review Memory"
    if category == CATEGORY_OPERATOR:
        return "Operator Note"
    if category == CATEGORY_LEGACY:
        return "Legacy Reference"
    return "Lesson Learned"


def trading_impact(category: str) -> Optional[str]:
    if category != CATEGORY_TRADING:
        return None
    return "May affect symbol ranking via bounded memory penalty when active and approved."


def system_impact(category: str) -> Optional[str]:
    if category != CATEGORY_SYSTEM:
        return None
    return "Platform/UI/data issue — does not teach market behavior; fix in code or ops."


def node_badge(row) -> str:
    st = getattr(row, "status", "active") or "active"
    cat = getattr(row, "category", "") or ""
    mt = getattr(row, "memory_type", "") or ""
    if st in ("archived", "deleted"):
        return st
    if cat == CATEGORY_SYSTEM:
        return "bug"
    if cat in (CATEGORY_RESEARCH, CATEGORY_BACKTEST):
        return "research"
    if "pattern" in mt:
        return "pattern"
    hrs = getattr(row, "human_review_status", "pending") or "pending"
    if hrs == "approved":
        return "approved"
    if hrs == "pending":
        return "pending review"
    return "lesson"
