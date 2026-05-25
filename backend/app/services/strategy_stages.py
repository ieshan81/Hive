"""Strategy lifecycle stages and allowed transitions."""

from __future__ import annotations

STAGES = frozenset(
    {
        "research_only",
        "watchlist",
        "paper_candidate",
        "paper_active",
        "live_candidate",
        "live_locked",
        "tiny_live",
        "standard_live",
        "paused",
        "rejected",
        "retired",
    }
)

ACTIVE_STAGES = frozenset({"paper_active", "live_candidate", "live_locked", "tiny_live", "standard_live"})
PAPER_STAGES = frozenset({"paper_candidate", "paper_active"})
LIVE_STAGES = frozenset({"live_candidate", "live_locked", "tiny_live", "standard_live"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "research_only": frozenset({"watchlist", "rejected"}),
    "watchlist": frozenset({"paper_candidate", "rejected", "research_only"}),
    "paper_candidate": frozenset({"paper_active", "rejected", "watchlist"}),
    "paper_active": frozenset({"live_candidate", "paused", "retired", "rejected"}),
    "live_candidate": frozenset({"live_locked", "paper_active", "paused", "rejected"}),
    "live_locked": frozenset({"tiny_live", "paper_active", "paused"}),
    "tiny_live": frozenset({"standard_live", "paused", "paper_active"}),
    "standard_live": frozenset({"paused", "retired"}),
    "paused": frozenset({"paper_active", "watchlist", "paper_candidate", "research_only"}),
    "rejected": frozenset({"research_only", "watchlist"}),
    "retired": frozenset({"research_only"}),
}

FORBIDDEN_SKIP = frozenset(
    {
        ("research_only", "paper_active"),
        ("research_only", "live_candidate"),
        ("research_only", "tiny_live"),
        ("research_only", "standard_live"),
        ("watchlist", "live_candidate"),
        ("watchlist", "paper_active"),
        ("watchlist", "tiny_live"),
        ("paper_candidate", "live_candidate"),
        ("paper_candidate", "tiny_live"),
    }
)


def can_transition(from_stage: str, to_stage: str, *, live_trading_locked: bool = True) -> tuple[bool, str | None]:
    if from_stage not in STAGES or to_stage not in STAGES:
        return False, "unknown_stage"
    if (from_stage, to_stage) in FORBIDDEN_SKIP:
        return False, "forbidden_skip"
    if to_stage not in ALLOWED_TRANSITIONS.get(from_stage, frozenset()):
        return False, "transition_not_allowed"
    if live_trading_locked and to_stage in ("tiny_live", "standard_live"):
        return False, "LIVE_TRADING_LOCKED"
    if from_stage == "rejected" and to_stage in ACTIVE_STAGES:
        return False, "rejected_requires_code_hash_change"
    return True, None
