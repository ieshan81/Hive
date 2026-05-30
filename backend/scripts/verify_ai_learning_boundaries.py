"""AI/advisory boundaries — the AI may advise, never act (paper or live).

Proves:
- AI actor strings are recognized; humans/operators are not
- the capability matrix denies every acting power (orders / live / config / caps)
  and the /ai-advisor/capabilities route mirrors it
- config-proposal classification: safety/caps keys are FORBIDDEN, paper-safe
  tunables auto-apply, everything else needs an operator
- assert_actor_not_ai raises for an AI actor
- the autonomous-paper-learning and paper-learning routers reject an AI actor
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.services.ai_boundaries import (
    AI_CAPABILITIES,
    assert_actor_not_ai,
    classify_config_proposal,
    is_ai_actor,
    is_forbidden_config_key,
    is_paper_safe_config_key,
)


def test_actor_recognition() -> None:
    for actor in ("ai", "gemini", "claude", "ai_advisor", "autopilot", "agent", "llm", "AUTO", " AI_Advisory "):
        assert is_ai_actor(actor) is True, actor
    for actor in ("operator", "human", "owner", "", None):
        assert is_ai_actor(actor) is False, actor
    print("ai-boundaries: AI actors recognized, humans excluded — PASS")


def test_capability_matrix_denies_acting() -> None:
    for denied in (
        "can_submit_orders",
        "can_cancel_orders",
        "can_liquidate_positions",
        "can_change_live_lock",
        "can_enable_live_trading",
        "can_disable_kill_switch",
        "can_apply_config_directly",
        "can_change_risk_or_caps",
        "can_bypass_operator_token",
        "can_bypass_execution_cage",
        "can_deploy_or_merge",
    ):
        assert AI_CAPABILITIES[denied] is False, denied
    for allowed in ("can_write_pending_memories", "can_summarize_or_explain", "can_propose_param_changes"):
        assert AI_CAPABILITIES[allowed] is True, allowed
    assert AI_CAPABILITIES["validator_required_for_proposals"] is True
    assert AI_CAPABILITIES["operator_approval_required_for_apply"] is True
    print("ai-boundaries: capability matrix denies every acting power — PASS")


def test_capabilities_route_mirrors_matrix() -> None:
    from app.routers.ai_advisor import capabilities

    caps = capabilities()
    assert caps["status"] == "ok", caps
    for key, value in AI_CAPABILITIES.items():
        assert caps[key] == value, (key, caps.get(key), value)
    assert caps["can_submit_orders"] is False, caps
    print("ai-boundaries: /ai-advisor/capabilities mirrors the matrix — PASS")


def test_config_proposal_classification() -> None:
    changes = {
        "risk": {"max_position_pct": 0.5},
        "autonomous_paper_learning": {"refresh_lookback_hours": 48, "absolute_max_new_entries_per_day": 99},
        "exploration": {"min_volume": 5},
    }
    out = classify_config_proposal(changes)
    assert "risk.max_position_pct" in out["forbidden"], out
    assert "autonomous_paper_learning.absolute_max_new_entries_per_day" in out["forbidden"], out
    assert "autonomous_paper_learning.refresh_lookback_hours" in out["auto_applicable"], out
    assert "exploration.min_volume" in out["requires_operator"], out
    # Forbidden keys must never leak into the apply-able buckets.
    assert "risk.max_position_pct" not in out["auto_applicable"], out
    assert "risk.max_position_pct" not in out["requires_operator"], out
    assert is_forbidden_config_key("execution.live_orders_enabled") is True
    assert is_paper_safe_config_key("autonomous_paper_learning.refresh_lookback_hours") is True
    print("ai-boundaries: config-proposal classification splits forbidden/auto/operator — PASS")


def test_assert_actor_not_ai_raises() -> None:
    raised = False
    try:
        assert_actor_not_ai("ai", action="enable scheduler")
    except PermissionError:
        raised = True
    assert raised, "assert_actor_not_ai must raise for an AI actor"
    assert_actor_not_ai("operator")  # must NOT raise
    print("ai-boundaries: assert_actor_not_ai raises for AI, allows operator — PASS")


def test_routers_block_ai_actor() -> None:
    from app.routers.autonomous_paper_learning import _block_ai as apl_block_ai
    from app.routers.paper_learning import _block_ai as pl_block_ai

    for blocker in (apl_block_ai, pl_block_ai):
        blocked = False
        try:
            blocker({"actor": "ai"})
        except HTTPException as exc:
            blocked = exc.status_code == 403
        assert blocked, f"{blocker.__module__} must 403 an AI actor"
        # An operator (or unspecified) actor passes through untouched.
        blocker({"actor": "operator"})
        blocker({})
    print("ai-boundaries: APL + paper-learning routers 403 an AI actor — PASS")


if __name__ == "__main__":
    test_actor_recognition()
    test_capability_matrix_denies_acting()
    test_capabilities_route_mirrors_matrix()
    test_config_proposal_classification()
    test_assert_actor_not_ai_raises()
    test_routers_block_ai_actor()
    print("ALL PASS: verify_ai_learning_boundaries")
