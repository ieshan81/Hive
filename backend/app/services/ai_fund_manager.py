"""AI Fund Manager — Gemini structured JSON only."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import settings
from app.database import AIReview

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


class AIFundManager:
    def __init__(self, session: Session):
        self.session = session

    @property
    def configured(self) -> bool:
        return settings.gemini_configured

    def review(self, subject_type: str, context: dict, subject_id: Optional[str] = None) -> Optional[AIReview]:
        if not self.configured:
            return None
        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
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
                subject_id=subject_id,
                decision=parsed.decision,
                confidence=parsed.confidence,
                summary=parsed.summary,
                payload=parsed.model_dump(),
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            return row
        except Exception as exc:
            logger.error("Gemini review failed: %s", exc)
            return None

    def get_latest_review(self) -> Optional[AIReview]:
        from sqlmodel import select

        return self.session.exec(select(AIReview).order_by(AIReview.created_at.desc())).first()
