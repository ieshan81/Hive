"""Gemini budget guard — $5/month cap, no runaway reviews."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select, func

from app.database import AIUsageLog
from app.services.config_manager import ConfigManager


class AIBudgetGuard:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()

    def status(self) -> dict[str, Any]:
        budget = float(self.config.get("ai_monthly_budget_usd", 5.0))
        spent = self._month_spend()
        remaining = max(0.0, budget - spent)
        today_count = self._today_review_count()
        max_day = int(self.config.get("ai_max_reviews_per_day", 8))
        last_at = self._last_review_at()
        min_gap = int(self.config.get("ai_min_seconds_between_reviews", 120))

        guard_active = spent >= budget or today_count >= max_day
        can_auto = (
            self.config.get("ai_enabled", True)
            and not guard_active
            and self._gap_ok(last_at, min_gap)
        )

        return {
            "ai_enabled": bool(self.config.get("ai_enabled", True)),
            "ai_monthly_budget_usd": budget,
            "ai_monthly_spent_usd": round(spent, 4),
            "ai_monthly_remaining_usd": round(remaining, 4),
            "ai_reviews_today": today_count,
            "ai_max_reviews_per_day": max_day,
            "budget_guard_active": guard_active,
            "can_run_automatic_review": can_auto,
            "ai_min_seconds_between_reviews": min_gap,
        }

    def allow_review(self, *, force: bool = False, mode: str = "quick") -> tuple[bool, str]:
        st = self.status()
        if not st["ai_enabled"]:
            return False, "ai_disabled"
        if force and mode == "deep":
            if st["budget_guard_active"] and st["ai_monthly_remaining_usd"] <= 0:
                return False, "budget_exhausted"
            return True, "forced_deep"
        if st["budget_guard_active"]:
            return False, "skipped_budget_guard"
        if not st["can_run_automatic_review"]:
            return False, "rate_or_daily_limit"
        return True, "ok"

    def record_usage(
        self,
        *,
        cycle_run_id: str | None,
        model: str,
        purpose: str,
        mode: str,
        status: str,
        estimated_cost_usd: float | None = None,
        prompt_tokens: int | None = None,
        output_tokens: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        total = None
        if prompt_tokens is not None and output_tokens is not None:
            total = prompt_tokens + output_tokens
        row = AIUsageLog(
            cycle_run_id=cycle_run_id,
            model=model,
            purpose=purpose,
            mode=mode,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            estimated_cost_usd=estimated_cost_usd,
            status=status,
            error_type=error_type,
            error_message=error_message,
        )
        self.session.add(row)
        self.session.commit()

    def _month_spend(self) -> float:
        start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = self.session.exec(
            select(AIUsageLog).where(
                AIUsageLog.created_at >= start,
                AIUsageLog.status == "ok",
            )
        ).all()
        return sum(r.estimated_cost_usd or 0 for r in rows)

    def _today_review_count(self) -> int:
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.session.exec(
            select(func.count())
            .select_from(AIUsageLog)
            .where(AIUsageLog.created_at >= start, AIUsageLog.status == "ok")
        ).one()

    def _last_review_at(self) -> datetime | None:
        row = self.session.exec(
            select(AIUsageLog).order_by(AIUsageLog.created_at.desc())
        ).first()
        return row.created_at if row else None

    def _gap_ok(self, last_at: datetime | None, min_seconds: int) -> bool:
        if last_at is None:
            return True
        return (datetime.utcnow() - last_at).total_seconds() >= min_seconds
