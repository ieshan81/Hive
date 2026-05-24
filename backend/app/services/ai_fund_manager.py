"""AI Fund Manager — Gemini structured JSON only."""

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

logger = logging.getLogger(__name__)
GEMINI_MODEL = "gemini-2.0-flash"


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


class AIFundManager:
    def __init__(self, session: Session):
        self.session = session

    @property
    def configured(self) -> bool:
        return settings.gemini_configured

    def review(
        self,
        subject_type: str,
        context: dict,
        subject_id: Optional[str] = None,
        cycle_run_id: Optional[str] = None,
    ) -> tuple[Optional[AIReview], dict[str, Any]]:
        meta: dict[str, Any] = {
            "ai_review_status": "skipped",
            "ai_review_error_type": None,
            "ai_review_error_message": None,
            "model": GEMINI_MODEL,
            "schema_validation_error": None,
            "retry_count": 0,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "cycle_run_id": cycle_run_id,
        }
        if not self.configured:
            meta["ai_review_status"] = "skipped"
            meta["ai_review_error_message"] = "Gemini not configured"
            return None, meta

        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(GEMINI_MODEL)
            prompt = (
                "You are the AI Fund Manager for Caged Hive Quant. "
                "You review trading activity but CANNOT execute trades or bypass risk controls. "
                "Respond ONLY with valid JSON matching this schema:\n"
                f"{AIReviewOutput.model_json_schema()}\n\n"
                f"Subject: {subject_type}\nContext:\n{json.dumps(context, default=str)}"
            )
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            parsed = AIReviewOutput.model_validate_json(response.text)
            row = AIReview(
                subject_type=subject_type,
                subject_id=subject_id or cycle_run_id,
                decision=parsed.decision,
                review_status="success",
                confidence=parsed.confidence,
                summary=parsed.summary,
                payload={
                    **parsed.model_dump(),
                    "ai_review_status": "success",
                    "model": GEMINI_MODEL,
                    "cycle_run_id": cycle_run_id,
                },
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
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
                logger.warning("Gemini quota exhausted — not retrying: %s", err_msg[:200])
            else:
                logger.error("Gemini review failed (%s): %s", err_type, exc)
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
            payload={
                **meta,
                "traceback": traceback.format_exc()[-1500:],
            },
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def get_latest_review(self) -> Optional[AIReview]:
        from sqlmodel import select

        return self.session.exec(select(AIReview).order_by(AIReview.created_at.desc())).first()
