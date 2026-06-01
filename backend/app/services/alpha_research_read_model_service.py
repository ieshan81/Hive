"""Canonical read model for Alpha Factory UI panels.

GET endpoints use this service. It reads stored scorecards/jobs/memories only
and does not fetch market data, run backtests, call Gemini, or submit orders.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ResearchJob, SettingsActionAudit
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.autonomous_alpha_scheduler import AutonomousAlphaScheduler
from app.services.memory_evidence_consolidator_v2 import MemoryEvidenceConsolidatorV2
from app.services.parameter_sweep_service import ParameterSweepService


class AlphaResearchReadModelService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}
        self.factory = AutonomousAlphaFactoryService(session, config)

    def status(self) -> dict[str, Any]:
        from app.services.kronos_market_model_service import KronosMarketModelService

        return {
            **self.factory.get_status(),
            "autonomous_scheduler": AutonomousAlphaScheduler(self.session, self.config).status(),
            # Optional market-model adapter (OFF by default; advisory-only, never promotes).
            **KronosMarketModelService(self.config).status_summary(),
        }

    def scorecards(self, *, limit: int = 100) -> dict[str, Any]:
        return self.factory.get_scorecards(limit=limit)

    def best_candidates(self, *, limit: int = 10) -> dict[str, Any]:
        return self.factory.get_best_candidates(limit=limit)

    def research_runs(self, *, limit: int = 50) -> dict[str, Any]:
        jobs = list(
            self.session.exec(
                select(ResearchJob)
                .where(ResearchJob.job_type.in_(["alpha_autonomous_cycle", "backtest", "optimization"]))
                .order_by(ResearchJob.created_at.desc())
                .limit(limit)
            ).all()
        )
        audits = list(
            self.session.exec(
                select(SettingsActionAudit)
                .where(SettingsActionAudit.action.in_(["autonomous_alpha_cycle", "autonomous_alpha_research", "autonomous_alpha_backtest", "autonomous_alpha_promotion"]))
                .order_by(SettingsActionAudit.created_at.desc())
                .limit(limit)
            ).all()
        )
        return {
            "status": "ok",
            "jobs": [
                {
                    "job_id": j.job_id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "progress_pct": j.progress_pct,
                    "created_at": j.created_at.isoformat() + "Z" if j.created_at else None,
                    "completed_at": j.completed_at.isoformat() + "Z" if j.completed_at else None,
                    "error": j.error,
                }
                for j in jobs
            ],
            "audit_runs": [
                {
                    "id": a.id,
                    "action": a.action,
                    "created_at": a.created_at.isoformat() + "Z" if a.created_at else None,
                    "details": a.details_json or {},
                }
                for a in audits
            ],
        }

    def memory_summary(self) -> dict[str, Any]:
        return MemoryEvidenceConsolidatorV2(self.session, self.config).summary()

    def autonomous_status(self) -> dict[str, Any]:
        return AutonomousAlphaScheduler(self.session, self.config).status()

    def parameter_sweep_summary(self) -> dict[str, Any]:
        return ParameterSweepService(self.session, self.config).latest_summary()
