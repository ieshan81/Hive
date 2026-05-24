"""Memory category classification — trading vs system vs operator vs AI."""

from __future__ import annotations

from typing import Optional

# Top-level categories
CATEGORY_TRADING = "trading_memory"
CATEGORY_SYSTEM = "system_issue"
CATEGORY_OPERATOR = "operator_note"
CATEGORY_AI = "ai_review_memory"

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

CATEGORY_COLORS = {
    CATEGORY_TRADING: "#06b6d4",
    CATEGORY_SYSTEM: "#f97316",
    CATEGORY_AI: "#a855f7",
    CATEGORY_OPERATOR: "#94a3b8",
}


def classify_memory_type(memory_type: str) -> str:
    if memory_type in TRADING_TYPES:
        return CATEGORY_TRADING
    if memory_type in SYSTEM_TYPES:
        return CATEGORY_SYSTEM
    if memory_type in OPERATOR_TYPES:
        return CATEGORY_OPERATOR
    if memory_type in AI_TYPES:
        return CATEGORY_AI
    if memory_type in LEGACY_TYPE_MAP:
        return LEGACY_TYPE_MAP[memory_type][1]
    # Heuristic fallback
    if any(x in memory_type for x in ("bug", "export", "serializer", "stale", "dashboard", "reconciliation")):
        return CATEGORY_SYSTEM
    if "ai" in memory_type or memory_type.startswith("ai_"):
        return CATEGORY_AI
    if memory_type == "operator_note":
        return CATEGORY_OPERATOR
    return CATEGORY_TRADING


def normalize_memory_type(memory_type: str) -> str:
    if memory_type in LEGACY_TYPE_MAP:
        return LEGACY_TYPE_MAP[memory_type][0]
    return memory_type


def default_visibility(category: str, memory_type: str, severity: str) -> dict[str, bool]:
    """Defaults for new memories."""
    if category == CATEGORY_SYSTEM:
        return {
            "visible_in_graph": True,
            "visible_to_ai": False,
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
    if category == CATEGORY_AI:
        return "AI Review Memory"
    if category == CATEGORY_OPERATOR:
        return "Operator Note"
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
    if "pattern" in mt:
        return "pattern"
    hrs = getattr(row, "human_review_status", "pending") or "pending"
    if hrs == "approved":
        return "approved"
    if hrs == "pending":
        return "pending review"
    return "lesson"
