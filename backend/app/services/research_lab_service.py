"""Autonomous Research Lab — backtests, sweeps, walk-forward, strategy promotion (no trading)."""

from __future__ import annotations

from datetime import datetime, timedelta
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
from app.services.research_performance import evaluate_metrics
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
        if (
            self.rcfg.get("auto_backtest_skip_if_paper_position_open")
            and not body.get("force")
        ):
            open_pos = self.session.exec(
                select(PositionSnapshot).where(PositionSnapshot.qty > 0)
            ).all()
            if open_pos:
                return {
                    "status": "skipped",
                    "message": "Open paper position — pass force=true to run anyway",
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
        from app.services.strategy_library import resolve_strategy_id

        strategy_id = resolve_strategy_id(body.get("strategy_id", "crypto_push_pull_baseline"))
        symbols = body.get("symbols") or ["BTC/USD"]
        params = body.get("parameters") or {}
        timeframe = body.get("timeframe", "5Min")
        lookback_days = int(body.get("lookback_days") or self.rcfg.get("default_lookback_days", 90))
        engine = ResearchBacktestEngine(self.session, self.config)
        out = engine.run(
            strategy_id,
            symbols,
            parameters=params,
            lookback_days=lookback_days,
            timeframe=timeframe,
        )
        if out.get("run_id"):
            ResearchMemoryService(self.session, self.config).from_backtest_run(out["run_id"])
        return out

    def batch_backtest(self, body: dict) -> dict[str, Any]:
        from app.services.strategy_library import resolve_strategy_id

        family = body.get("strategy_family") or body.get("strategy_id", "crypto_push_pull_momentum")
        strategy_id = resolve_strategy_id(family)
        symbols = body.get("symbols") or ["DOGE/USD", "BTC/USD", "ETH/USD"]
        timeframe = body.get("timeframe", "1h")
        lookback_days = int(body.get("lookback_days", 90))
        alpaca_tf = "1Hour" if timeframe in ("1h", "1H") else timeframe

        hist = HistoricalDataService(self.session, self.config)
        fetch_errors = []
        coverage_warnings: list[str] = []
        coverage_summary: dict[str, Any] = {}
        for sym in symbols:
            fr = hist.fetch_and_store(
                sym,
                timeframe=alpaca_tf,
                limit=min(500, lookback_days * 24),
                lookback_days=lookback_days,
            )
            if fr.get("status") != "ok":
                fetch_errors.append(f"{sym}: {fr.get('message')}")
            elif fr.get("date_warning"):
                coverage_warnings.append(f"{sym}: {fr['date_warning']}")
            coverage_summary[sym] = {
                k: fr.get(k)
                for k in (
                    "requested_start_date",
                    "requested_end_date",
                    "actual_start_date",
                    "actual_end_date",
                    "data_is_recent",
                    "data_staleness_days",
                    "date_warning",
                )
            }

        strat = get_strategy(self.session, strategy_id)
        grid = body.get("parameter_grid") or (strat.parameters_json if strat else {})
        date_warning = "; ".join(coverage_warnings) if coverage_warnings else None
        sweep = ParameterSweepEngine(self.session, self.config)
        out = sweep.sweep(
            strategy_id,
            symbols,
            grid,
            lookback_days=lookback_days,
            date_warning=date_warning,
            coverage_summary=coverage_summary,
        )
        out["fetch_errors"] = fetch_errors
        out["strategy_id"] = strategy_id
        out["lookback_days"] = lookback_days
        out["date_warning"] = date_warning
        out["coverage"] = coverage_summary
        analysis = out.get("batch_analysis") or {}
        out["recommended_action"] = (analysis.get("batch_evaluation") or {}).get("recommended_action", "do_not_promote")
        out["promote_allowed"] = (analysis.get("batch_evaluation") or {}).get("promote_allowed", False)
        out["batch_failed_after_costs"] = analysis.get("rejected", False)
        return out

    def fetch_historical_data(self, body: dict) -> dict[str, Any]:
        symbols = body.get("symbols") or ["DOGE/USD", "BTC/USD", "ETH/USD"]
        timeframes = body.get("timeframes") or ["1h"]
        lookback_days = int(body.get("lookback_days", 90))
        limit = min(1000, max(50, lookback_days * 24))
        hist = HistoricalDataService(self.session, self.config)
        results = []
        errors = []
        tf_map = {"1h": "1Hour", "4h": "4Hour", "1d": "1Day"}
        for sym in symbols:
            for tf in timeframes:
                alpaca_tf = tf_map.get(tf, tf)
                r = hist.fetch_and_store(
                    sym, timeframe=alpaca_tf, limit=limit, lookback_days=lookback_days
                )
                results.append(r)
                if r.get("status") != "ok":
                    errors.append({"symbol": sym, "timeframe": tf, "message": r.get("message")})
        return {"status": "ok", "results": results, "errors": errors, "coverage": hist.list_coverage()}

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
        sig_counts: dict[str, int] = {}
        for r in rows:
            sig = "|".join(
                str(x)
                for x in (
                    r.expectancy,
                    r.profit_factor,
                    r.num_trades,
                    r.max_drawdown_pct,
                    r.win_rate,
                )
            )
            sig_counts[sig] = sig_counts.get(sig, 0) + 1
        sweep_warning = any(c >= 5 for c in sig_counts.values())

        hist = HistoricalDataService(self.session, self.config)
        cov_list = hist.list_coverage()
        date_warning = next((c.get("date_warning") for c in cov_list if c.get("date_warning")), None)

        out = []
        for r in rows:
            metrics = {
                "expectancy": r.expectancy,
                "profit_factor": r.profit_factor,
                "max_drawdown_pct": r.max_drawdown_pct,
                "num_trades": r.num_trades,
            }
            ev = evaluate_metrics(metrics, self.config)
            out.append(
                {
                    "strategy_id": r.strategy_id,
                    "parameter_set_id": r.parameter_set_id,
                    "expectancy": r.expectancy,
                    "profit_factor": r.profit_factor,
                    "win_rate": r.win_rate,
                    "num_trades": r.num_trades,
                    "max_drawdown_pct": r.max_drawdown_pct,
                    "recommended_action": ev["recommended_action"],
                    "promote_allowed": ev["promote_allowed"],
                    "rejection_reason": ev["rejection_reason"],
                    "confidence": metrics.get("confidence") or (
                        "low" if (r.num_trades or 0) < 20 else "medium"
                    ),
                    "data_warning": date_warning,
                    "parameter_variation_warning": (
                        "Parameter sweep may not be influencing strategy logic."
                        if sweep_warning
                        else None
                    ),
                }
            )
        return out

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

    def propose_backtests_from_memory(self, limit: int = 5) -> dict[str, Any]:
        """Rank backtest ideas from recent lessons and execution failures — research only."""
        from app.database import ExecutionLog, LessonNode

        since = datetime.utcnow() - timedelta(days=7)
        lessons = list(
            self.session.exec(select(LessonNode).where(LessonNode.created_at >= since)).all()
        )
        rejects = list(
            self.session.exec(
                select(ExecutionLog).where(
                    ExecutionLog.created_at >= since,
                    ExecutionLog.status.in_(("paper_order_rejected", "preflight_blocked")),
                )
            ).all()
        )
        proposals: list[dict[str, Any]] = []
        seen: set[str] = set()
        for log in rejects:
            key = f"{log.symbol}|reject"
            if key in seen or not log.symbol:
                continue
            seen.add(key)
            proposals.append(
                {
                    "strategy_id": "crypto_push_pull",
                    "symbols": [log.symbol],
                    "reason": f"Broker/preflight reject on {log.symbol} — validate gates in backtest.",
                    "source": "memory_proposal",
                    "memory_evidence": log.reject_reason,
                }
            )
        for lesson in lessons:
            sym = lesson.symbol or "BTC/USD"
            key = f"{sym}|{lesson.memory_type}"
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "strategy_id": lesson.strategy_name or "crypto_push_pull",
                    "symbols": [sym],
                    "reason": (lesson.title or lesson.summary or "Lesson-driven backtest")[:200],
                    "source": "memory_proposal",
                    "memory_evidence": lesson.summary,
                }
            )
        return {"status": "ok", "proposals": proposals[:limit], "research_submits_orders": False}
