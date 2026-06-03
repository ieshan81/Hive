"""Strategy Reviewer — optional Gemini commentary on cycle activity (budget-guarded).

QUARANTINED / advisory only. Renamed from the former "AI Fund Manager". It CANNOT execute trades,
rank symbols, change scorecards, or override risk — it only writes an AIReview commentary row and may
propose (never auto-apply) a gated config change. Disabled by default in the decision loop (see
cycle_engine `legacy_strategy_reviewer.enabled`). No trade/score/rank/promotion/risk decision depends
on its output.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session

from app.config import settings
from app.database import AIReview
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class AIReviewOutput(BaseModel):
    decision: str = Field(description="hold, approve, block, pause, or review")
    confidence: float = Field(ge=0, le=1)
    summary: str
    what_happened: str
    suspected_issue: Optional[str] = None
    risk_assessment: str
    memory_to_create: Optional[dict] = None
    config_change_proposal: Optional[dict] = None
    backtest_required: bool = False
    strategy_status_recommendation: Optional[str] = None
    should_pause_strategy: bool = False
    should_blacklist_symbol: bool = False
    evidence_used: list[str] = Field(default_factory=list)


class StrategyReviewer:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.budget = AIBudgetGuard(session)

    @property
    def configured(self) -> bool:
        return settings.gemini_configured and bool(self.config.get("ai_enabled", True))

    def _model_for_mode(self, mode: str) -> str:
        return settings.gemini_model_for(mode)

    def review(
        self,
        subject_type: str,
        context: dict,
        subject_id: Optional[str] = None,
        cycle_run_id: Optional[str] = None,
        mode: str = "quick",
        force: bool = False,
    ) -> tuple[Optional[AIReview], dict[str, Any]]:
        model = self._model_for_mode(mode)
        est_cost = float(self.config.get("ai_estimated_cost_per_review_usd", 0.002))
        meta: dict[str, Any] = {
            "ai_review_status": "skipped",
            "ai_review_error_type": None,
            "ai_review_error_message": None,
            "model": model,
            "mode": mode,
            "schema_validation_error": None,
            "retry_count": 0,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "cycle_run_id": cycle_run_id,
        }

        if not settings.gemini_configured:
            meta["ai_review_error_message"] = "Gemini not configured"
            return None, meta

        if not self.config.get("ai_enabled", True):
            meta["ai_review_status"] = "skipped"
            meta["ai_review_error_message"] = "AI disabled in config"
            return None, meta

        allow, reason = self.budget.allow_review(force=force, mode=mode)
        if not allow:
            meta["ai_review_status"] = "skipped_budget_guard"
            meta["ai_review_error_message"] = reason
            return None, meta

        compact = json.dumps(context, default=str)
        if len(compact) > 12000:
            compact = compact[:12000] + "…[truncated]"

        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            gemini = genai.GenerativeModel(model)
            prompt = (
                "You are the Strategy Reviewer for Caged Hive Quant (paper trading, $5/mo AI budget). "
                "You CANNOT execute trades, rank symbols, change scorecards, or override risk. Your output "
                "is advisory commentary only and requires human approval. Be concise. "
                "Respond ONLY with valid JSON matching:\n"
                f"{AIReviewOutput.model_json_schema()}\n\n"
                f"Subject: {subject_type}\nContext:\n{compact}"
            )
            response = gemini.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=int(self.config.get("ai_max_tokens_per_review", 2048)),
                ),
            )
            parsed = AIReviewOutput.model_validate_json(response.text)
            proposal_meta = None
            if parsed.config_change_proposal:
                from app.trading_cage.gemini_proposal_gate import validate_gemini_proposal

                proposal_meta = validate_gemini_proposal(parsed.config_change_proposal)
            row = AIReview(
                subject_type=subject_type,
                subject_id=subject_id or cycle_run_id,
                decision=parsed.decision,
                review_status="success",
                confidence=parsed.confidence,
                summary=parsed.summary,
                payload={
                    **parsed.model_dump(),
                    "proposal_validation": proposal_meta,
                    "gemini_can_trade": False,
                    "requires_human_approval": True,
                    "ai_review_status": "success",
                    "model": model,
                    "mode": mode,
                    "cycle_run_id": cycle_run_id,
                },
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            self.budget.record_usage(
                cycle_run_id=cycle_run_id,
                model=model,
                purpose=subject_type,
                mode=mode,
                status="ok",
                estimated_cost_usd=est_cost,
            )
            meta["ai_review_status"] = "success"
            return row, meta
        except ValidationError as exc:
            meta.update(
                {
                    "ai_review_status": "failed",
                    "ai_review_error_type": "schema_validation_error",
                    "ai_review_error_message": str(exc)[:500],
                    "schema_validation_error": str(exc)[:500],
                }
            )
            self.budget.record_usage(
                cycle_run_id=cycle_run_id,
                model=model,
                purpose=subject_type,
                mode=mode,
                status="failed",
                estimated_cost_usd=0,
                error_type="schema_validation_error",
                error_message=str(exc)[:200],
            )
            row = self._record_failure(subject_type, meta, subject_id or cycle_run_id)
            return row, meta
        except Exception as exc:
            err_type = type(exc).__name__
            err_msg = str(exc)[:500]
            quota_exhausted = (
                err_type == "ResourceExhausted"
                or "429" in err_msg
                or "quota" in err_msg.lower()
                or "rate limit" in err_msg.lower()
            )
            meta.update(
                {
                    "ai_review_status": "failed",
                    "ai_review_error_type": err_type,
                    "ai_review_error_message": err_msg,
                    "retry_count": 0,
                    "quota_exhausted": quota_exhausted,
                }
            )
            if quota_exhausted:
                logger.warning("Gemini quota/billing limit — not retrying")
            else:
                logger.error("Gemini review failed (%s): %s", err_type, exc)
            self.budget.record_usage(
                cycle_run_id=cycle_run_id,
                model=model,
                purpose=subject_type,
                mode=mode,
                status="failed",
                error_type=err_type,
                error_message=err_msg,
            )
            row = self._record_failure(subject_type, meta, subject_id or cycle_run_id)
            return row, meta

    def _record_failure(
        self,
        subject_type: str,
        meta: dict[str, Any],
        subject_id: Optional[str],
    ) -> AIReview:
        row = AIReview(
            subject_type=subject_type,
            subject_id=subject_id,
            decision="failed",
            review_status="failed",
            confidence=0.0,
            summary=meta.get("ai_review_error_message") or "AI review failed",
            payload={**meta, "traceback": traceback.format_exc()[-1500:]},
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def get_latest_review(self) -> Optional[AIReview]:
        from sqlmodel import select

        return self.session.exec(select(AIReview).order_by(AIReview.created_at.desc())).first()
