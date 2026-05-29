"""Research OS services.

This module coordinates research ledgers and existing lab services. It does not
submit broker orders and is safe to call from operator POST handlers.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import uuid
from datetime import datetime
from typing import Any, Iterable

from sqlmodel import Session, select

from app.database import (
    AIAgentRun,
    CodeProposal,
    LiveFlagChangeRequest,
    LiveReadinessReview,
    OptimizationRun,
    ParameterSetResult,
    ResearchBacktestRun,
    ResearchJob,
    RiskAuditReport,
    StrategyChangeProposal,
    StrategyDefinition,
    StrategySpecRecord,
    TradingViewEvent,
    TradingViewIntegration,
)
from app.schemas.research_os import OptimizationRequest, StrategySpec
from app.services.config_manager import ConfigManager
from app.services.optional_dependency_service import optional_dependency_status
from app.services.research_lab_service import ResearchLabService


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _row_time(value) -> str | None:
    return value.isoformat() + "Z" if value else None


class ResearchOSReadService:
    """Read-only Research OS projection for dashboards."""

    def __init__(self, session: Session):
        self.session = session

    def status(self) -> dict[str, Any]:
        jobs = list(self.session.exec(select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(20)).all())
        backtest = self.session.exec(
            select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(1)
        ).first()
        risk = self.session.exec(
            select(RiskAuditReport).order_by(RiskAuditReport.created_at.desc()).limit(1)
        ).first()
        proposal = self.session.exec(
            select(StrategyChangeProposal).order_by(StrategyChangeProposal.created_at.desc()).limit(1)
        ).first()
        code_pending = list(
            self.session.exec(
                select(CodeProposal)
                .where(CodeProposal.status.in_(["draft", "pending_review", "approved"]))
                .order_by(CodeProposal.created_at.desc())
                .limit(50)
            ).all()
        )
        latest_agent = self.session.exec(
            select(AIAgentRun).order_by(AIAgentRun.id.desc()).limit(1)
        ).first()
        latest_tv = self.session.exec(
            select(TradingViewEvent).order_by(TradingViewEvent.created_at.desc()).limit(1)
        ).first()
        latest_live = self.session.exec(
            select(LiveReadinessReview).order_by(LiveReadinessReview.created_at.desc()).limit(1)
        ).first()
        flag_req = self.session.exec(
            select(LiveFlagChangeRequest).order_by(LiveFlagChangeRequest.created_at.desc()).limit(1)
        ).first()

        running = [j for j in jobs if j.status in ("queued", "running")]
        return {
            "status": "ok",
            "generated_at_utc": _now(),
            "read_model_only": True,
            "research_jobs_running": len(running),
            "latest_backtest": None if not backtest else {
                "run_id": backtest.run_id,
                "strategy_id": backtest.strategy_id,
                "status": backtest.status,
                "num_trades": backtest.num_trades,
                "confidence_label": backtest.confidence_label,
                "created_at": _row_time(backtest.created_at),
            },
            "latest_risk_audit": None if not risk else {
                "report_id": risk.report_id,
                "strategy_id": risk.strategy_id,
                "pass_fail": risk.pass_fail,
                "risk_score": risk.risk_score,
                "veto_reason": risk.veto_reason,
                "created_at": _row_time(risk.created_at),
            },
            "latest_promotion_proposal": None if not proposal else {
                "id": proposal.id,
                "strategy_id": proposal.strategy_id,
                "status": proposal.status,
                "proposal_type": proposal.proposal_type,
                "requires_operator_approval": proposal.requires_operator_approval,
            },
            "paper_exploration_status": self._paper_exploration_status(),
            "live_readiness_status": {
                "live_locked": True,
                "latest_stage": latest_live.stage if latest_live else "PAPER_LOCKED",
                "latest_status": latest_live.status if latest_live else "locked",
                "latest_flag_request_status": flag_req.status if flag_req else None,
            },
            "code_proposal_pending_count": len(code_pending),
            "tradingview_status": {
                "mode": "display_only",
                "latest_event_at": _row_time(latest_tv.created_at) if latest_tv else None,
                "execution_blocked_reason": latest_tv.execution_blocked_reason if latest_tv else "display_only_execution_blocked",
            },
            "agent_loop_status": {
                "latest_agent": latest_agent.agent_name if latest_agent else None,
                "latest_node": latest_agent.node_name if latest_agent else None,
                "latest_status": latest_agent.status if latest_agent else "not_run",
            },
            "optional_dependencies": optional_dependency_status(),
            "next_research_action": self._next_action(backtest, risk, running),
        }

    def _paper_exploration_status(self) -> dict[str, Any]:
        cfg = ConfigManager(self.session).get_current()
        return {
            "enabled": bool((cfg.get("exploration") or {}).get("enabled", True)),
            "paper_orders_enabled": bool((cfg.get("execution") or {}).get("paper_orders_enabled", False)),
            "live_trading_locked": True,
            "stage": (cfg.get("promotion") or {}).get("current_stage", "PAPER"),
        }

    @staticmethod
    def _next_action(backtest, risk, running: list[ResearchJob]) -> str:
        if running:
            return "Wait for running research job to complete."
        if not backtest:
            return "Run a research backtest with cached bars."
        if not risk:
            return "Run deterministic risk audit for latest backtest."
        if risk.pass_fail != "pass":
            return "Review risk audit blockers before promotion."
        return "Review promotion proposal or run walk-forward validation."


class ResearchOSService:
    def __init__(self, session: Session):
        self.session = session

    def list_strategy_specs(self) -> dict[str, Any]:
        specs = self.session.exec(
            select(StrategySpecRecord).order_by(StrategySpecRecord.created_at.desc()).limit(100)
        ).all()
        defs = self.session.exec(select(StrategyDefinition).limit(100)).all()
        return {
            "status": "ok",
            "strategy_specs": [self._spec_row(s) for s in specs],
            "existing_strategy_definitions": [
                {
                    "strategy_id": d.strategy_id,
                    "name": d.strategy_name,
                    "family": d.strategy_family,
                    "status": d.status,
                    "reused_by_research_os": True,
                }
                for d in defs
            ],
        }

    def get_strategy_spec(self, strategy_id: str) -> dict[str, Any]:
        spec = self.session.exec(
            select(StrategySpecRecord)
            .where(StrategySpecRecord.strategy_id == strategy_id)
            .order_by(StrategySpecRecord.created_at.desc())
            .limit(1)
        ).first()
        if not spec:
            return {"status": "not_found", "strategy_id": strategy_id}
        return {"status": "ok", "strategy_spec": self._spec_row(spec)}

    def create_strategy_spec(self, body: dict[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        spec = StrategySpec.model_validate(body)
        payload = spec.model_dump()
        row = StrategySpecRecord(
            strategy_id=spec.strategy_id,
            name=spec.name,
            version=spec.version,
            family=spec.family,
            asset_classes=spec.asset_classes,
            timeframes=spec.timeframes,
            entry_logic_json=spec.entry_logic.model_dump(),
            exit_logic_json=spec.exit_logic.model_dump(),
            risk_logic_json=spec.risk_logic.model_dump(),
            sizing_logic_json=spec.sizing_logic.model_dump(),
            required_features_json=[r.model_dump() for r in spec.required_features],
            constraints_json=spec.constraints,
            source=spec.source,
            status=spec.status,
            created_by=actor,
            fingerprint=_fingerprint(payload),
            notes=spec.notes,
        )
        self.session.add(row)
        self.session.flush()
        return {"status": "ok", "strategy_spec": self._spec_row(row)}

    def create_job(self, job_type: str, payload: dict[str, Any], *, requested_by: str = "operator") -> ResearchJob:
        job = ResearchJob(
            job_id=_new_id("job"),
            job_type=job_type,
            status="running",
            requested_by=requested_by,
            input_json=payload,
            progress_pct=5,
            started_at=datetime.utcnow(),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def list_jobs(self) -> dict[str, Any]:
        rows = self.session.exec(select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(100)).all()
        return {"status": "ok", "jobs": [self._job_row(r) for r in rows]}

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.session.exec(select(ResearchJob).where(ResearchJob.job_id == job_id)).first()
        return {"status": "ok", "job": self._job_row(row)} if row else {"status": "not_found", "job_id": job_id}

    def run_backtest(self, body: dict[str, Any], *, requested_by: str = "operator") -> dict[str, Any]:
        job = self.create_job("backtest", body, requested_by=requested_by)
        try:
            out = ResearchLabService(self.session).run_backtest(body)
            job.status = "complete" if out.get("status") == "ok" else "failed"
            job.output_json = out
            job.error = None if job.status == "complete" else str(out.get("message") or out.get("error") or "backtest_failed")
            job.progress_pct = 100
            job.completed_at = datetime.utcnow()
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:500]
            job.progress_pct = 100
            job.completed_at = datetime.utcnow()
            out = {"status": "error", "message": job.error}
        self.session.add(job)
        return {"status": job.status, "job": self._job_row(job), "result": out}

    def run_optimization(self, body: dict[str, Any], *, requested_by: str = "operator") -> dict[str, Any]:
        req = OptimizationRequest.model_validate(body)
        job = self.create_job("optimization", req.model_dump(), requested_by=requested_by)
        opt = OptimizationRun(
            optimization_id=_new_id("opt"),
            strategy_id=req.strategy_id,
            optimizer_type="grid" if req.optimizer_type == "optuna" else req.optimizer_type,
            objective=req.objective,
            status="running",
        )
        self.session.add(opt)
        self.session.flush()
        trials = self._grid_trials(req.parameter_grid, req.max_trials)
        tried = []
        best = None
        for idx, params in enumerate(trials):
            tried.append({"trial": idx + 1, "params": params, "status": "queued_for_backtest"})
            if best is None:
                best = {"params": params, "metrics": {"objective": None, "note": "Run backtests to score trial."}}
        opt.trials_count = len(tried)
        opt.tried_params_json = tried
        opt.best_params_json = (best or {}).get("params") or {}
        opt.best_metrics_json = (best or {}).get("metrics") or {}
        opt.status = "complete"
        opt.completed_at = datetime.utcnow()
        job.status = "complete"
        job.progress_pct = 100
        job.output_json = {"optimization_id": opt.optimization_id, "trials_count": opt.trials_count}
        job.completed_at = datetime.utcnow()
        self.session.add(opt)
        self.session.add(job)
        return {"status": "ok", "job": self._job_row(job), "optimization": self._optimization_row(opt)}

    def run_risk_audit(self, body: dict[str, Any], *, requested_by: str = "operator") -> dict[str, Any]:
        strategy_id = str(body.get("strategy_id") or "unknown")
        run_id = body.get("backtest_run_id")
        if not run_id:
            latest = self.session.exec(
                select(ResearchBacktestRun)
                .where(ResearchBacktestRun.strategy_id == strategy_id)
                .order_by(ResearchBacktestRun.created_at.desc())
                .limit(1)
            ).first()
            run_id = latest.run_id if latest else None
        run = self.session.exec(select(ResearchBacktestRun).where(ResearchBacktestRun.run_id == run_id)).first() if run_id else None
        metrics = (run.metrics_json or {}) if run else (body.get("metrics") or {})
        reasons = []
        num_trades = int(metrics.get("num_trades") or (run.num_trades if run else 0) or 0)
        max_dd = float(metrics.get("max_drawdown_pct") or metrics.get("max_drawdown") or 0.0)
        profit_factor = metrics.get("profit_factor")
        if num_trades < 20:
            reasons.append("weak_sample_size")
        if max_dd > 25:
            reasons.append("drawdown_too_high")
        if profit_factor is not None and float(profit_factor) < 1.0:
            reasons.append("profit_factor_below_one")
        pass_fail = "pass" if not reasons else "fail"
        risk_score = max(0.0, 100.0 - len(reasons) * 25.0 - min(max_dd, 50.0))
        row = RiskAuditReport(
            report_id=_new_id("risk"),
            strategy_id=strategy_id,
            backtest_run_id=run_id,
            risk_score=round(risk_score, 2),
            drawdown_metrics_json={"max_drawdown_pct": max_dd},
            tail_risk_json={"sample_size": num_trades},
            liquidity_metrics_json={"status": "not_evaluated_in_fallback"},
            concentration_json={"status": "not_evaluated_in_fallback"},
            correlation_json={"status": "not_evaluated_in_fallback"},
            pass_fail=pass_fail,
            veto_reason=", ".join(reasons) if reasons else None,
            reasons_json=reasons,
        )
        self.session.add(row)
        return {"status": "ok", "risk_audit": self._risk_row(row), "requested_by": requested_by}

    def propose_promotion(self, body: dict[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        if str(actor).lower() in ("ai", "gemini", "ai_advisor", "agent"):
            return {"status": "blocked", "reason": "AI cannot self-promote strategies"}
        row = StrategyChangeProposal(
            proposal_type="promotion",
            strategy_id=str(body.get("strategy_id") or ""),
            patch_json={"from_stage": body.get("from_stage"), "to_stage": body.get("to_stage")},
            reason=str(body.get("reason") or "Research OS promotion proposal"),
            memory_evidence_ids=body.get("memory_evidence_ids") or [],
            backtest_run_id=body.get("backtest_run_id"),
            risk_note=body.get("risk_note"),
            status="proposed",
            requires_operator_approval=True,
            expected_risk=body.get("expected_risk"),
            proposed_by=actor,
        )
        self.session.add(row)
        self.session.flush()
        return {"status": "ok", "proposal": self._promotion_row(row), "applied": False}

    @staticmethod
    def _grid_trials(grid: dict[str, list[Any]], max_trials: int) -> list[dict[str, Any]]:
        if not grid:
            return [{}]
        keys = list(grid.keys())
        combos: Iterable[tuple[Any, ...]] = itertools.product(*[grid[k] or [None] for k in keys])
        return [dict(zip(keys, combo)) for combo in itertools.islice(combos, max_trials)]

    @staticmethod
    def _spec_row(r: StrategySpecRecord) -> dict[str, Any]:
        return {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "name": r.name,
            "version": r.version,
            "family": r.family,
            "asset_classes": r.asset_classes,
            "timeframes": r.timeframes,
            "status": r.status,
            "source": r.source,
            "fingerprint": r.fingerprint,
            "created_at": _row_time(r.created_at),
        }

    @staticmethod
    def _job_row(r: ResearchJob | None) -> dict[str, Any] | None:
        if not r:
            return None
        return {
            "job_id": r.job_id,
            "job_type": r.job_type,
            "status": r.status,
            "progress_pct": r.progress_pct,
            "requested_by": r.requested_by,
            "agent_name": r.agent_name,
            "error": r.error,
            "created_at": _row_time(r.created_at),
            "completed_at": _row_time(r.completed_at),
        }

    @staticmethod
    def _optimization_row(r: OptimizationRun) -> dict[str, Any]:
        return {
            "optimization_id": r.optimization_id,
            "strategy_id": r.strategy_id,
            "optimizer_type": r.optimizer_type,
            "objective": r.objective,
            "trials_count": r.trials_count,
            "best_params": r.best_params_json,
            "status": r.status,
        }

    @staticmethod
    def _risk_row(r: RiskAuditReport) -> dict[str, Any]:
        return {
            "report_id": r.report_id,
            "strategy_id": r.strategy_id,
            "backtest_run_id": r.backtest_run_id,
            "risk_score": r.risk_score,
            "pass_fail": r.pass_fail,
            "veto_reason": r.veto_reason,
            "reasons": r.reasons_json or [],
        }

    @staticmethod
    def _promotion_row(r: StrategyChangeProposal) -> dict[str, Any]:
        return {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "proposal_type": r.proposal_type,
            "status": r.status,
            "requires_operator_approval": r.requires_operator_approval,
            "proposed_by": r.proposed_by,
        }

