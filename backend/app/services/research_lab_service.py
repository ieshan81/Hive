"""Autonomous Research Lab — backtests, sweeps, walk-forward, strategy promotion (no trading)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    ParameterSetResult,
    PositionSnapshot,
    ResearchBacktestRun,
    StrategyCandidate,
    WalkForwardResult,
)
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService
from app.services.legacy_bundle_import import LegacyBundleImport
from app.services.monte_carlo_engine import MonteCarloEngine
from app.services.parameter_sweep_engine import ParameterSweepEngine
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.research_memory_service import ResearchMemoryService
from app.services.strategy_library import get_strategy, list_strategies, seed_strategy_library
from app.services.walk_forward_engine import WalkForwardEngine


class ResearchLabService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.rcfg = self.config.get("research") or {}

    def status(self) -> dict[str, Any]:
        guard = AIBudgetGuard(self.session)
        runs = len(self.session.exec(select(ResearchBacktestRun)).all())
        candidates = len(
            self.session.exec(
                select(StrategyCandidate).where(StrategyCandidate.status != "rejected")
            ).all()
        )
        cov = HistoricalDataService(self.session, self.config).list_coverage()
        return {
            "status": "ok",
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "research_submits_orders": False,
            "auto_backtest_enabled": bool(self.rcfg.get("auto_backtest_enabled", False)),
            "ai_budget": guard.status(),
            "backtest_run_count": runs,
            "strategy_candidate_count": candidates,
            "historical_coverage_symbols": len(cov),
            "monte_carlo": self._monte_carlo_status(),
        }

    def _monte_carlo_status(self) -> dict[str, Any]:
        mc = MonteCarloEngine(self.session, self.config).get_latest()
        if not mc:
            return {"status": "unavailable", "message": "Monte Carlo requires real closed trades (min 10)"}
        return {
            "status": mc.status,
            "simulation_count": mc.simulation_count,
            "probability_target": mc.probability_target,
            "warning": mc.warning,
        }

    def run_research_batch(self, body: dict) -> dict[str, Any]:
        """Run Research Lab Now — no broker orders."""
        if self.rcfg.get("auto_backtest_skip_if_paper_position_open"):
            open_pos = self.session.exec(
                select(PositionSnapshot).where(PositionSnapshot.qty > 0)
            ).all()
            if open_pos:
                return {
                    "status": "skipped",
                    "message": "Open paper position — research batch skipped per config",
                }

        families = body.get("strategy_families") or self.rcfg.get("auto_backtest_families") or [
            "crypto_push_pull"
        ]
        symbols = body.get("symbols") or self.rcfg.get("auto_backtest_symbols") or ["BTC/USD"]
        results = []
        for sid in families:
            out = self.run_backtest({"strategy_id": sid, "symbols": symbols})
            results.append(out)
            if out.get("run_id"):
                ResearchMemoryService(self.session, self.config).from_backtest_run(out["run_id"])
        return {"status": "ok", "runs": results, "message": "Research only — no orders submitted"}

    def run_backtest(self, body: dict) -> dict[str, Any]:
        strategy_id = body.get("strategy_id", "crypto_push_pull")
        symbols = body.get("symbols") or ["BTC/USD"]
        params = body.get("parameters") or {}
        engine = ResearchBacktestEngine(self.session, self.config)
        out = engine.run(strategy_id, symbols, parameters=params)
        if out.get("run_id"):
            ResearchMemoryService(self.session, self.config).from_backtest_run(out["run_id"])
        return out

    def batch_backtest(self, body: dict) -> dict[str, Any]:
        strategy_id = body.get("strategy_id", "crypto_push_pull")
        symbols = body.get("symbols") or ["BTC/USD"]
        strat = get_strategy(self.session, strategy_id)
        grid = body.get("parameter_grid") or (strat.parameters_json if strat else {})
        sweep = ParameterSweepEngine(self.session, self.config)
        return sweep.sweep(strategy_id, symbols, grid)

    def run_walk_forward(self, body: dict) -> dict[str, Any]:
        strategy_id = body.get("strategy_id", "crypto_push_pull")
        symbol = (body.get("symbols") or ["BTC/USD"])[0]
        wf = WalkForwardEngine(self.session, self.config).run(
            strategy_id, symbol, parameters=body.get("parameters")
        )
        wf["strategy_id"] = strategy_id
        if wf.get("run_id"):
            ResearchMemoryService(self.session, self.config).from_walk_forward(wf["run_id"], wf)
        return wf

    def get_backtest_result(self, run_id: str) -> Optional[dict]:
        return ResearchBacktestEngine(self.session, self.config).get_run(run_id)

    def list_experiments(self) -> dict[str, Any]:
        runs = ResearchBacktestEngine(self.session, self.config).list_runs(30)
        sweeps = self.session.exec(
            select(ParameterSetResult).order_by(ParameterSetResult.created_at.desc()).limit(30)
        ).all()
        wf = self.session.exec(
            select(WalkForwardResult).order_by(WalkForwardResult.created_at.desc()).limit(20)
        ).all()
        return {
            "backtest_runs": runs,
            "parameter_sweeps": [
                {
                    "parameter_set_id": r.parameter_set_id,
                    "strategy_id": r.strategy_id,
                    "expectancy": r.expectancy,
                    "num_trades": r.num_trades,
                }
                for r in sweeps
            ],
            "walk_forward_windows": len(wf),
        }

    def list_candidates(self, status: Optional[str] = None) -> list[dict]:
        q = select(StrategyCandidate)
        if status:
            q = q.where(StrategyCandidate.status == status)
        rows = self.session.exec(q.order_by(StrategyCandidate.updated_at.desc())).all()
        return [self._serialize_candidate(r) for r in rows]

    def promising_strategies(self) -> list[dict]:
        rows = self.session.exec(
            select(StrategyCandidate).where(
                StrategyCandidate.promotion_stage.in_(
                    ["walk_forward_passed", "paper_candidate", "backtested"]
                )
            )
        ).all()
        return [self._serialize_candidate(r) for r in rows]

    def rejected_strategies(self) -> list[dict]:
        rows = self.session.exec(
            select(StrategyCandidate).where(StrategyCandidate.status == "rejected")
        ).all()
        return [self._serialize_candidate(r) for r in rows]

    def research_memories(self, limit: int = 50) -> list[dict]:
        return ResearchMemoryService(self.session, self.config).list_research_memories(limit)

    def leaderboard(self) -> list[dict]:
        rows = self.session.exec(
            select(ParameterSetResult)
            .where(ParameterSetResult.num_trades >= 5)
            .order_by(ParameterSetResult.expectancy.desc())
            .limit(25)
        ).all()
        return [
            {
                "strategy_id": r.strategy_id,
                "parameter_set_id": r.parameter_set_id,
                "expectancy": r.expectancy,
                "profit_factor": r.profit_factor,
                "win_rate": r.win_rate,
                "num_trades": r.num_trades,
                "max_drawdown_pct": r.max_drawdown_pct,
            }
            for r in rows
        ]

    def promote_to_paper_candidate(self, strategy_id: str, body: dict) -> dict[str, Any]:
        """AI/operator propose only — human_approved required for paper_enabled."""
        run_id = body.get("run_id")
        existing = self.session.exec(
            select(StrategyCandidate).where(StrategyCandidate.strategy_id == strategy_id)
        ).first()
        if existing and existing.promotion_stage == "paper_enabled":
            return {"status": "error", "message": "Already paper_enabled — requires separate workflow"}

        cand = existing or StrategyCandidate(
            strategy_id=strategy_id,
            run_id=run_id,
            status="paper_candidate",
            promotion_stage="paper_candidate",
            proposed_by=body.get("proposed_by", "operator"),
            metrics_json=body.get("metrics"),
            evidence_json=body.get("evidence"),
        )
        cand.promotion_stage = "paper_candidate"
        cand.status = "paper_candidate"
        cand.updated_at = datetime.utcnow()
        cand.human_approved = False
        self.session.add(cand)
        ResearchMemoryService(self.session, self.config).from_promotion_candidate(cand)
        return {
            "status": "ok",
            "message": "Proposed as paper candidate — human approval required for paper_enabled",
            "candidate": self._serialize_candidate(cand),
        }

    def reject_strategy(self, strategy_id: str, body: dict) -> dict[str, Any]:
        reason = body.get("reason", "Rejected by operator")
        cand = self.session.exec(
            select(StrategyCandidate).where(StrategyCandidate.strategy_id == strategy_id)
        ).first()
        if not cand:
            cand = StrategyCandidate(strategy_id=strategy_id, status="rejected")
        cand.status = "rejected"
        cand.promotion_stage = "rejected"
        cand.rejection_reason = reason
        cand.updated_at = datetime.utcnow()
        self.session.add(cand)
        ResearchMemoryService(self.session, self.config).from_rejection(
            strategy_id, reason, body.get("evidence") or {}
        )
        return {"status": "ok", "strategy_id": strategy_id, "reason": reason}

    def import_legacy_bundle(self, payload: dict) -> dict:
        return LegacyBundleImport(self.session, self.config).import_bundle(payload)

    def ensure_library(self) -> int:
        return seed_strategy_library(self.session)

    def _serialize_candidate(self, r: StrategyCandidate) -> dict:
        return {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "parameter_set_id": r.parameter_set_id,
            "run_id": r.run_id,
            "status": r.status,
            "promotion_stage": r.promotion_stage,
            "metrics": r.metrics_json,
            "rejection_reason": r.rejection_reason,
            "human_approved": r.human_approved,
            "proposed_by": r.proposed_by,
        }
