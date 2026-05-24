"""Verify AI budget guard skips automatic review without crashing cycle."""

from __future__ import annotations

from app.database import engine, Session, init_db, AIUsageLog
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.config_manager import ConfigManager
from app.services.startup import bootstrap_database
from datetime import datetime


def main() -> None:
    init_db()
    bootstrap_database()
    session = Session(engine)
    config = ConfigManager(session).get_current()
    budget_usd = float(config.get("ai_monthly_budget_usd", 5))

    guard = AIBudgetGuard(session)
    for _ in range(20):
        guard.record_usage(
            cycle_run_id="budget-test",
            model="test",
            purpose="test",
            mode="quick",
            status="ok",
            estimated_cost_usd=budget_usd,
        )

    allow, reason = guard.allow_review()
    assert not allow, "Should block when budget exhausted"
    assert "budget" in reason or "limit" in reason

    st = guard.status()
    assert st["budget_guard_active"] is True
    print("OK ai budget guard:", reason, st)


if __name__ == "__main__":
    main()
