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

    def near_misses(self, *, limit: int = 10) -> dict[str, Any]:
        return self.factory.get_near_misses(limit=limit)

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

    def get_unified_autonomous_alpha_status(self) -> dict[str, Any]:
        """Canonical autonomous status unifying the Alpha Factory scheduler with the legacy
        autonomous_research worker. Never reports 'never_run' when legacy research has run."""
        from sqlmodel import func

        from app.database import AlphaScorecard, ResearchBacktestRun, WalkForwardResult
        from app.services.engine_config import cfg_get

        def _ts(v: Any) -> Optional[str]:
            return v.isoformat() + "Z" if hasattr(v, "isoformat") else None

        sched = AutonomousAlphaScheduler(self.session, self.config).status()
        alpha_enabled = bool(cfg_get(self.config, "alpha_factory.scheduler_enabled", False))
        old_enabled = bool(
            cfg_get(self.config, "autonomous_paper_learning.autonomous_research.autonomous_backtest_worker_enabled", True)
        )
        latest_run = self.session.exec(
            select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(1)
        ).first()
        legacy_run = self.session.exec(
            select(ResearchBacktestRun)
            .where(ResearchBacktestRun.source == "autonomous_research_worker")
            .order_by(ResearchBacktestRun.created_at.desc())
            .limit(1)
        ).first()
        latest_wf = self.session.exec(
            select(WalkForwardResult).order_by(WalkForwardResult.created_at.desc()).limit(1)
        ).first()
        latest_cycle = self.session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action.in_(["autonomous_alpha_cycle", "autonomous_alpha_bootstrap", "autonomous_alpha_promotion"]))
            .order_by(SettingsActionAudit.created_at.desc())
            .limit(1)
        ).first()
        latest_sc = self.session.exec(
            select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc()).limit(1)
        ).first()
        sc_count = int(self.session.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
        legacy_detected = legacy_run is not None
        try:
            mem = MemoryEvidenceConsolidatorV2(self.session, self.config).summary()
            mem_written = int(mem.get("alpha_memory_count") or mem.get("count") or 0)
        except Exception:
            mem_written = 0

        if sc_count > 0 and legacy_detected:
            plain = "Legacy research has run; Alpha Factory has converted evidence into scorecards."
        elif sc_count > 0:
            plain = "Alpha Factory bootstrapped scorecards from existing research evidence."
        elif legacy_detected:
            plain = "Legacy research has run; Alpha Factory has not yet converted evidence."
        else:
            plain = "No autonomous research evidence yet."

        return {
            "status": "ok",
            "enabled": alpha_enabled or old_enabled,
            "alpha_factory_enabled": alpha_enabled,
            "old_research_enabled": old_enabled,
            "legacy_research_detected": legacy_detected,
            "source": "alpha_factory" if alpha_enabled else ("legacy_research" if legacy_detected else "idle"),
            "last_research_at": _ts(legacy_run.created_at) if legacy_run else (_ts(latest_run.created_at) if latest_run else None),
            "last_alpha_cycle_at": _ts(latest_cycle.created_at) if latest_cycle else None,
            "last_backtest_at": _ts(latest_run.created_at) if latest_run else None,
            "last_walk_forward_at": _ts(latest_wf.created_at) if latest_wf else None,
            "last_alpha_scorecard_write_at": _ts(latest_sc.updated_at) if latest_sc else None,
            "scorecards_written": sc_count,
            "memory_written": mem_written,
            "skipped_reason": sched.get("skipped_reason") or sched.get("skip_reason"),
            "scheduler": sched,
            "plain_english": plain,
            "orders_authority": "none",
        }

    def autonomous_status(self) -> dict[str, Any]:
        return self.get_unified_autonomous_alpha_status()

    def parameter_sweep_summary(self) -> dict[str, Any]:
        return ParameterSweepService(self.session, self.config).latest_summary()
