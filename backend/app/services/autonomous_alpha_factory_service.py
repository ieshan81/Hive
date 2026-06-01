"""Autonomous Alpha Factory.

This is the research-and-paper-governance brain. It researches, scores,
promotes, quarantines, and writes memory. It never submits broker orders.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import (
    AlphaScorecard,
    HistoricalBar,
    PaperExperimentOutcome,
    ResearchBacktestRun,
    ResearchJob,
    SettingsActionAudit,
    StrategyRegistry,
    SymbolCandidate,
    TradeRecord,
    WalkForwardResult,
)
from app.services.autonomous_alpha_promotion_service import PAPER_ALLOWED_VERDICTS, AutonomousAlphaPromotionService
from app.services.autonomous_strategy_generator import AutonomousStrategyGenerator
from app.services.config_manager import ConfigManager
from app.services.cost_model_service import CostModelService
from app.services.engine_config import cfg_get
from app.services.memory_evidence_consolidator_v2 import MemoryEvidenceConsolidatorV2
from app.services.market_session_service import MarketSessionService
from app.services.parameter_sweep_service import ParameterSweepService
from app.services.order_ledger_service import classify_asset
from app.services.research_cost_model import COST_MODEL_VERSION, round_trip_cost_pct
from app.services.research_lab_service import ResearchLabService
from app.services.walk_forward_validation_service import WalkForwardValidationService

PROMISING_VERDICTS = PAPER_ALLOWED_VERDICTS | {"promising"}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _norm(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").strip()


def _iso(value: Any) -> str | None:
    return value.isoformat() + "Z" if hasattr(value, "isoformat") else None


class AutonomousAlphaFactoryService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.generator = AutonomousStrategyGenerator(session, self.config)
        self.promotion = AutonomousAlphaPromotionService(session, self.config)
        self.memory = MemoryEvidenceConsolidatorV2(session, self.config)

    def run_autonomous_cycle(self, body: Optional[dict[str, Any]] = None, *, operator: str = "operator") -> dict[str, Any]:
        body = body or {}
        started = time.perf_counter()
        job = self._job("alpha_autonomous_cycle", body, operator)
        phases: list[dict[str, Any]] = []
        try:
            phases.append({"phase": "bootstrap", **self.bootstrap_scorecards_from_existing_evidence(operator=operator)})
            phases.append({"phase": "research", **self.run_research_cycle(body, operator=operator)})
            phases.append({"phase": "backtest", **self.run_backtest_cycle(body, operator=operator)})
            phases.append({"phase": "promotion", **self.run_candidate_promotion_cycle(operator=operator)})
            phases.append({"phase": "memory", **self.run_memory_consolidation_cycle(operator=operator)})
            paper = self.run_paper_selection_cycle(operator=operator)
            phases.append({"phase": "paper_selection", **paper})
            job.status = "complete"
            job.progress_pct = 100
            job.output_json = {"phases": phases, "paper_candidates": paper.get("paper_candidates", [])}
            job.completed_at = datetime.utcnow()
            status = "ok"
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:500]
            job.progress_pct = 100
            job.completed_at = datetime.utcnow()
            phases.append({"phase": "error", "status": "error", "message": job.error})
            status = "error"
        duration_ms = int((time.perf_counter() - started) * 1000)
        payload = {
            "status": status,
            "job_id": job.job_id,
            "duration_ms": duration_ms,
            "phases": phases,
            "orders_created": 0,
            "research_only": True,
            "plain_english": "Autonomous Alpha Factory researched candidates and wrote paper-governance evidence. No orders submitted.",
        }
        self._audit("autonomous_alpha_cycle", operator, payload)
        self.session.add(job)
        self.session.flush()
        return payload

    def run_research_cycle(self, body: Optional[dict[str, Any]] = None, *, operator: str = "operator") -> dict[str, Any]:
        body = body or {}
        candidates = self.generator.generate(symbols=body.get("symbols"), limit=int(body.get("symbol_limit") or 8))
        self._audit(
            "autonomous_alpha_research",
            operator,
            {"candidate_count": len(candidates), "symbols": sorted({c["symbol"] for c in candidates})[:20]},
        )
        return {
            "status": "ok",
            "symbols_tested": len({c["symbol"] for c in candidates}),
            "strategies_tested": len({c["strategy_family"] for c in candidates}),
            "candidates_generated": len(candidates),
            "candidates": candidates[:30],
            "orders_created": 0,
        }

    def run_backtest_cycle(self, body: Optional[dict[str, Any]] = None, *, operator: str = "operator") -> dict[str, Any]:
        body = body or {}
        candidates = self.generator.generate(symbols=body.get("symbols"), limit=int(body.get("symbol_limit") or 3))
        limit = int(body.get("candidate_limit") or cfg_get(self.config, "alpha_factory.backtest_candidate_limit", 5) or 5)
        lab = ResearchLabService(self.session)
        runs: list[dict[str, Any]] = []
        tested: set[tuple[str, str]] = set()
        for cand in candidates:
            key = (cand["strategy_id"], cand["symbol"])
            if key in tested:
                continue
            tested.add(key)
            if len(runs) >= limit:
                break
            try:
                runs.append(
                    lab.run_backtest(
                        {
                            "strategy_id": cand["strategy_id"],
                            "symbols": [cand["symbol"]],
                            "parameters": self._first_params(cand.get("parameter_ranges") or {}),
                            "timeframe": body.get("timeframe") or "5Min",
                            "lookback_days": int(body.get("lookback_days") or 30),
                        }
                    )
                )
            except Exception as exc:
                runs.append({"status": "error", "strategy_id": cand["strategy_id"], "symbol": cand["symbol"], "message": str(exc)[:200]})
        self._audit("autonomous_alpha_backtest", operator, {"backtests_run": len(runs), "runs": runs[:10]})
        return {
            "status": "ok",
            "backtests_run": len(runs),
            "runs": runs,
            "orders_created": 0,
        }

    def run_candidate_promotion_cycle(self, *, operator: str = "operator") -> dict[str, Any]:
        runs = list(
            self.session.exec(
                select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(100)
            ).all()
        )
        written = 0
        promoted = 0
        rejected = 0
        for run in runs:
            for symbol in run.symbols or ["UNKNOWN"]:
                sc = self._scorecard_from_backtest(run, str(symbol))
                sc = self.promotion.evaluate(sc)
                if sc.verdict in PAPER_ALLOWED_VERDICTS:
                    promoted += 1
                elif sc.verdict in ("rejected", "paper_quarantined"):
                    rejected += 1
                written += 1
        self._audit(
            "autonomous_alpha_promotion",
            operator,
            {"scorecards_written": written, "candidates_promoted": promoted, "candidates_rejected": rejected},
        )
        self.session.flush()
        return {
            "status": "ok",
            "scorecards_written": written,
            "candidates_promoted": promoted,
            "candidates_rejected": rejected,
            "orders_created": 0,
        }

    def bootstrap_scorecards_from_existing_evidence(self, *, limit: int = 2000, operator: str = "bootstrap") -> dict[str, Any]:
        """Idempotently convert EXISTING research evidence into AlphaScorecards.

        Root cause this fixes: scorecards stayed 0 in production because the promotion
        cycle (which converts ResearchBacktestRun -> AlphaScorecard) only runs when the
        scheduler/operator triggers it, and the prod scheduler is disabled. This scans ALL
        existing backtest evidence (including legacy autonomous_research_worker runs) and
        builds/updates one scorecard per (strategy_id, normalized_symbol) using the SAME
        deterministic promotion rules.

        Safety: reuses _scorecard_from_backtest (persists + dedupes via _find_scorecard) and
        promotion.evaluate (enforces zero-sample -> unproven, negative expectancy ->
        rejected, only sufficient+positive -> paper_candidate; also updates StrategyRegistry).
        Never fabricates profit, never promotes weak evidence, never places orders, idempotent.
        """
        runs = list(
            self.session.exec(
                select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.asc()).limit(limit)
            ).all()
        )
        before = int(self.session.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
        seen: set[tuple[str, str]] = set()
        written = promoted = rejected = unproven = 0
        for run in runs:
            for symbol in (run.symbols or []):
                sym = str(symbol or "").strip()
                if not sym:
                    continue
                sc = self._scorecard_from_backtest(run, sym)
                sc = self.promotion.evaluate(sc)
                seen.add((run.strategy_id, _norm(sym)))
                written += 1
                if sc.verdict in PAPER_ALLOWED_VERDICTS:
                    promoted += 1
                elif sc.verdict in ("rejected", "paper_quarantined"):
                    rejected += 1
                elif sc.verdict == "unproven":
                    unproven += 1
        self.session.flush()
        after = int(self.session.exec(select(func.count()).select_from(AlphaScorecard)).one() or 0)
        if not runs:
            plain = "No research evidence available to bootstrap scorecards yet."
        elif promoted:
            plain = f"Alpha Factory bootstrapped scorecards from existing research evidence; {promoted} paper candidate(s) qualify."
        else:
            plain = "Scorecards built, but no paper candidate is currently qualified."
        out = {
            "status": "ok",
            "evidence_runs_scanned": len(runs),
            "distinct_targets": len(seen),
            "scorecards_written": written,
            "scorecards_total": after,
            "scorecards_created": max(0, after - before),
            "paper_candidates": promoted,
            "rejected": rejected,
            "unproven": unproven,
            "orders_created": 0,
            "plain_english": plain,
        }
        self._audit("autonomous_alpha_bootstrap", operator, out)
        return out

    def run_memory_consolidation_cycle(self, *, operator: str = "operator") -> dict[str, Any]:
        out = self.memory.consolidate_scorecards()
        self._audit("autonomous_alpha_memory", operator, out)
        return {**out, "orders_created": 0}

    def run_paper_selection_cycle(self, *, operator: str = "operator") -> dict[str, Any]:
        candidates = self.get_best_candidates(limit=20)["candidates"]
        approved = [c for c in candidates if c.get("verdict") in PAPER_ALLOWED_VERDICTS]
        self._audit(
            "autonomous_alpha_paper_selection",
            operator,
            {"paper_candidate_count": len(approved), "best_candidate": approved[0] if approved else None},
        )
        return {
            "status": "ok",
            "paper_candidates": approved,
            "paper_candidate_count": len(approved),
            "orders_created": 0,
            "plain_english": self._plain_for_candidates(approved, candidates),
        }

    def get_status(self) -> dict[str, Any]:
        cards = list(self.session.exec(select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc()).limit(200)).all())
        counts = Counter(sc.verdict for sc in cards)
        latest_cycle = self._latest_audit("autonomous_alpha_cycle")
        latest_backtest = self.session.exec(
            select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(1)
        ).first()
        latest_wf = self.session.exec(
            select(WalkForwardResult).order_by(WalkForwardResult.created_at.desc()).limit(1)
        ).first()
        best = self.get_best_candidates(limit=1)["candidates"]
        can_trade = bool(best and best[0].get("verdict") in PAPER_ALLOWED_VERDICTS)
        reason = "alpha_candidate_ready" if can_trade else self._reason_no_trade(cards)
        min_sample = int(cfg_get(self.config, "alpha_factory.min_sample_size", 5) or 5)
        min_pf = float(cfg_get(self.config, "alpha_factory.min_profit_factor", 1.05) or 1.05)
        return {
            "status": "ok",
            "generated_at_utc": _now(),
            "can_trade_paper_now": can_trade,
            "reason": reason,
            "autonomous_enabled": bool(cfg_get(self.config, "alpha_factory.scheduler_enabled", False)),
            "autonomous_current_phase": (latest_cycle.details_json or {}).get("current_phase") if latest_cycle else "idle",
            "autonomous_last_run_at": _iso(latest_cycle.created_at if latest_cycle else None),
            "autonomous_next_run_due_at": self._next_due(latest_cycle),
            "autonomous_skip_reason": (latest_cycle.details_json or {}).get("skipped_reason") if latest_cycle else None,
            "best_candidate": best[0] if best else None,
            "active_strategy_count": counts.get("paper_active", 0),
            "rejected_strategy_count": counts.get("rejected", 0),
            "unproven_strategy_count": counts.get("unproven", 0),
            "paper_candidate_count": counts.get("paper_candidate", 0),
            "latest_research_cycle_at": _iso(latest_cycle.created_at if latest_cycle else None),
            "latest_backtest_at": _iso(latest_backtest.created_at if latest_backtest else None),
            "latest_walk_forward_at": _iso(latest_wf.created_at if latest_wf else None),
            "data_quality_summary": self._data_quality_summary(cards),
            "memory_summary": self.memory.summary(),
            "recent_loss_summary": self._recent_loss_summary(),
            "blocked_symbols": self._blocked_symbols(cards),
            "alpha_failure_breakdown": self._failure_breakdown(cards, min_sample, min_pf),
            "top_cost_blockers": self._top_cost_blockers(cards),
            "session_research": self._session_research_summary(cards),
            "cost_model_version": COST_MODEL_VERSION,
            "near_miss_count": sum(1 for sc in cards if self._classify_failure(sc, min_sample, min_pf) == "near_miss"),
            "next_research_action": self._next_action(cards, latest_backtest),
            "plain_english": self._plain_status(can_trade, reason, best),
            "orders_authority": "none",
        }

    def get_scorecards(self, *, limit: int = 100) -> dict[str, Any]:
        rows = list(
            self.session.exec(select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc()).limit(limit)).all()
        )
        return {"status": "ok", "scorecards": [self._scorecard_public(r) for r in rows], "count": len(rows)}

    def get_best_candidates(self, *, limit: int = 10) -> dict[str, Any]:
        rows = list(
            self.session.exec(select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc()).limit(200)).all()
        )
        ranked = sorted(rows, key=self._rank_score, reverse=True)
        return {"status": "ok", "candidates": [self._scorecard_public(r) for r in ranked[:limit]]}

    def get_near_misses(self, *, limit: int = 10) -> dict[str, Any]:
        """READ ONLY: scorecards closest to qualifying, with the single missing requirement.

        Diagnostic only — names the next research action per candidate. Never trades or promotes.
        """
        rows = list(
            self.session.exec(select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc()).limit(200)).all()
        )
        min_sample = int(cfg_get(self.config, "alpha_factory.min_sample_size", 5) or 5)
        min_pf = float(cfg_get(self.config, "alpha_factory.min_profit_factor", 1.05) or 1.05)
        out: list[dict[str, Any]] = []
        for sc in rows:
            if sc.verdict in PAPER_ALLOWED_VERDICTS:
                continue  # already qualified — not a near-miss
            missing, required, current, distance, action = self._near_miss_detail(sc, min_sample, min_pf)
            pub = self._scorecard_public(sc)
            pub.update({
                "missing_requirement": missing,
                "required_metric": required,
                "current_metric": current,
                "failure_category": self._classify_failure(sc, min_sample, min_pf),
                "distance_to_qualify": round(distance, 4),
                "next_research_action": action,
                "session_blocker": pub.get("session_blocker"),
                "session_edge_after_cost_bps": pub.get("session_edge_after_cost_bps"),
                "session_sample_size": pub.get("session_sample_size"),
                "session_next_action": pub.get("session_next_action")
                or self._session_next_action(sc, min_sample),
            })
            out.append(pub)
        out.sort(key=lambda c: c["distance_to_qualify"])
        return {
            "status": "ok",
            "near_misses": out[:limit],
            "count": min(len(out), limit),
            "total_unqualified": len(out),
            "min_sample_size": min_sample,
            "min_profit_factor": min_pf,
            "orders_authority": "none",
            "plain_english": (
                f"{out[0]['symbol']} {out[0]['best_session'] or out[0]['strategy_family']} is closest: "
                f"needs {out[0]['missing_requirement']} ({out[0]['required_metric']}, now {out[0]['current_metric']})."
                if out else "No scorecards yet; run autonomous research."
            ),
        }

    def explain_candidate(self, symbol: str, strategy_family: str) -> dict[str, Any]:
        row = self._find_scorecard(symbol, strategy_family=strategy_family)
        if not row:
            return {
                "status": "not_found",
                "symbol": symbol,
                "strategy_family": strategy_family,
                "plain_english": "No autonomous alpha scorecard exists for this symbol/setup yet.",
            }
        return {
            "status": "ok",
            "candidate": self._scorecard_public(row),
            "plain_english": row.promotion_reason or self._candidate_plain(row),
        }

    def can_trade_paper(self, symbol: str, strategy_family: Optional[str] = None, strategy_id: Optional[str] = None) -> dict[str, Any]:
        row = self._find_scorecard(symbol, strategy_family=strategy_family, strategy_id=strategy_id)
        if not row:
            return {
                "allowed": False,
                "reason": "ALPHA_NOT_READY:no_alpha_scorecard",
                "plain_english": "No paper trade: autonomous research has not produced an alpha scorecard for this symbol/setup.",
            }
        allow_promising = bool(cfg_get(self.config, "alpha_factory.allow_promising_paper", False))
        allowed_verdicts = PROMISING_VERDICTS if allow_promising else PAPER_ALLOWED_VERDICTS
        if row.verdict not in allowed_verdicts:
            return {
                "allowed": False,
                "reason": f"ALPHA_NOT_READY:{row.verdict}",
                "scorecard": self._scorecard_public(row),
                "plain_english": row.promotion_reason or self._candidate_plain(row),
            }
        if row.recent_loss_cooldown_until and row.recent_loss_cooldown_until > datetime.utcnow():
            return {
                "allowed": False,
                "reason": "ALPHA_NOT_READY:recent_loss_cooldown",
                "scorecard": self._scorecard_public(row),
                "plain_english": "No paper trade: candidate is in recent-loss cooldown.",
            }
        if row.edge_after_cost_bps is None or row.edge_after_cost_bps <= 0:
            return {
                "allowed": False,
                "reason": "ALPHA_NOT_READY:no_positive_edge_after_cost",
                "scorecard": self._scorecard_public(row),
                "plain_english": "No paper trade: scorecard does not prove positive after-cost edge.",
            }
        return {
            "allowed": True,
            "reason": "alpha_candidate_ready",
            "scorecard": self._scorecard_public(row),
            "plain_english": row.promotion_reason or self._candidate_plain(row),
        }

    def _scorecard_from_backtest(self, run: ResearchBacktestRun, symbol: str) -> AlphaScorecard:
        metrics = run.metrics_json or {}
        cost = run.cost_model_json or metrics.get("cost_model") or {}
        family = self._family_for(run.strategy_id)
        existing = self._find_scorecard(symbol, strategy_id=run.strategy_id)
        recent = self._recent_paper(symbol, run.strategy_id)
        latest_bar = self.session.exec(
            select(HistoricalBar)
            .where(HistoricalBar.symbol == symbol)
            .order_by(HistoricalBar.timestamp.desc())
            .limit(1)
        ).first()
        session_bars = list(
            self.session.exec(
                select(HistoricalBar)
                .where(HistoricalBar.symbol == symbol, HistoricalBar.timeframe == str(metrics.get("timeframe") or "5Min"))
                .order_by(HistoricalBar.timestamp.desc())
                .limit(600)
            ).all()
        )
        if not session_bars:
            session_bars = list(
                self.session.exec(
                    select(HistoricalBar)
                    .where(HistoricalBar.symbol == symbol)
                    .order_by(HistoricalBar.timestamp.desc())
                    .limit(600)
                ).all()
            )
        edge_after_cost_bps = self._edge_bps(metrics, cost)
        if edge_after_cost_bps is None:
            exp = self._float(metrics.get("expectancy"))
            edge_after_cost_bps = None if exp is None else exp * 10000.0
        row = existing or AlphaScorecard(
            symbol=symbol,
            normalized_symbol=_norm(symbol),
            asset_class=(classify_asset(symbol) if classify_asset(symbol) != "unknown" else ("crypto" if "/" in symbol else "stock")),
            strategy_family=family,
            strategy_id=run.strategy_id,
        )
        row.timeframe = str(metrics.get("timeframe") or row.timeframe or "5Min")
        row.sample_size = int(run.sample_size or run.num_trades or metrics.get("num_trades") or 0)
        row.backtest_count = int(
            self.session.exec(
                select(func.count()).select_from(ResearchBacktestRun).where(ResearchBacktestRun.strategy_id == run.strategy_id)
            ).one()
            or 0
        )
        row.walk_forward_count = int(
            self.session.exec(
                select(func.count()).select_from(WalkForwardResult).where(WalkForwardResult.strategy_id == run.strategy_id)
            ).one()
            or 0
        )
        row.win_rate = self._float(metrics.get("win_rate"))
        row.expectancy = self._float(metrics.get("expectancy"))
        row.profit_factor = self._float(metrics.get("profit_factor"))
        row.max_drawdown_pct = self._drawdown_pct(metrics)
        row.sharpe_if_available = self._float(metrics.get("sharpe"))
        row.average_win = self._float(metrics.get("avg_win"))
        row.average_loss = self._float(metrics.get("avg_loss"))
        if row.average_win is not None and row.average_loss not in (None, 0):
            row.payoff_ratio = abs(row.average_win / row.average_loss)
        # Surface the deterministic cost breakdown so negative-edge verdicts are explainable.
        cm = round_trip_cost_pct(symbol, self.config)
        row.cost_bps = self._cost_bps(cost, "round_trip_cost_pct")
        if row.cost_bps is None:
            row.cost_bps = cm["round_trip_bps"]
        row.spread_bps = self._cost_bps(cost, "spread_pct")
        if row.spread_bps is None:
            row.spread_bps = cm["spread_bps"]
        row.slippage_bps = self._cost_bps(cost, "slippage_pct")
        if row.slippage_bps is None:
            row.slippage_bps = cm["slippage_bps"]
        row.fee_bps = self._cost_bps(cost, "fee_pct")
        if row.fee_bps is None:
            row.fee_bps = cm["fee_bps"]
        row.edge_after_cost_bps = edge_after_cost_bps
        session_summary = MarketSessionService().summarize_candles(
            session_bars,
            asset_class=row.asset_class,
            cost_bps=row.cost_bps,
        )
        self._apply_session_summary(row, session_summary)
        row.recent_paper_trade_count = recent["count"]
        row.recent_paper_pnl = recent["pnl"]
        row.recent_churn_count = recent["churn"]
        row.recent_loss_cooldown_until = recent.get("cooldown_until")
        row.data_freshness_status = "fresh" if latest_bar and (datetime.utcnow() - latest_bar.timestamp).total_seconds() < 6 * 3600 else "unknown"
        row.bar_count = int(metrics.get("bars_count") or 0)
        row.quote_freshness = "unknown"
        row.last_backtest_run_id = run.run_id
        row.last_walk_forward_run_id = self._latest_walk_forward_id(run.strategy_id)
        row.evidence_ids_json = [run.run_id] + ([row.last_walk_forward_run_id] if row.last_walk_forward_run_id else [])
        row.autonomous_generated = True
        gross_exp_bps = round(row.expectancy * 10000 + cm["round_trip_bps"], 2) if row.expectancy is not None else None
        row.scorecard_json = {
            "cost_model": cost,
            "cost_breakdown": cm,
            "cost_model_version": COST_MODEL_VERSION,
            "gross_expectancy_bps": gross_exp_bps,
            "round_trip_cost_bps": cm["round_trip_bps"],
            "spread_cost_bps": cm["spread_bps"],
            "slippage_cost_bps": cm["slippage_bps"],
            "fee_cost_bps": cm["fee_bps"],
            "breakeven_move_bps": cm["round_trip_bps"],
            "edge_after_cost_bps": row.edge_after_cost_bps,
            "cost_to_edge_ratio": (
                round(cm["round_trip_bps"] / abs(row.edge_after_cost_bps), 3) if row.edge_after_cost_bps else None
            ),
            "metrics": metrics,
            "session_metrics": session_summary,
            "composite_score": self._rank_score(row),
            "source": "autonomous_alpha_factory",
            "recent_loss_evidence": {
                "recent_loss_sources": recent.get("recent_loss_sources") or [],
                "strategy_filter_applied": recent.get("strategy_filter_applied", False),
                "skipped_other_strategy_trade_count": recent.get("skipped_other_strategy_trade_count", 0),
                "strategy_unknown_fallback_count": recent.get("strategy_unknown_fallback_count", 0),
            },
        }
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        self.session.flush()
        return row

    def _find_scorecard(
        self,
        symbol: str,
        *,
        strategy_family: Optional[str] = None,
        strategy_id: Optional[str] = None,
    ) -> AlphaScorecard | None:
        q = select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == _norm(symbol))
        if strategy_id:
            q = q.where(AlphaScorecard.strategy_id == strategy_id)
        if strategy_family:
            q = q.where(AlphaScorecard.strategy_family == strategy_family)
        rows = list(self.session.exec(q.order_by(AlphaScorecard.updated_at.desc()).limit(20)).all())
        if not rows:
            return None
        return sorted(rows, key=self._rank_score, reverse=True)[0]

    def _apply_session_summary(self, row: AlphaScorecard, summary: dict[str, Any]) -> None:
        min_session_sample = int(cfg_get(self.config, "alpha_factory.session_min_sample_size", 5) or 5)
        sessions = summary.get("sessions") or {}
        best_session = summary.get("best_session")
        best_metrics = sessions.get(best_session) if best_session else {}
        sample = int(best_metrics.get("sample_size") or summary.get("session_sample_size") or 0)
        if sample < min_session_sample:
            summary["session_blocker"] = "session_sample_insufficient"
            summary["session_next_action"] = f"Collect {min_session_sample - sample} more valid session sample(s)."
        else:
            summary["session_blocker"] = None
            summary["session_next_action"] = "Session sample is large enough for comparison."
        row.best_session = best_session
        row.worst_session = summary.get("worst_session")
        row.session_sample_size = sample
        row.session_win_rate = self._float(best_metrics.get("win_rate"))
        row.session_expectancy = self._float(best_metrics.get("expectancy"))
        row.session_profit_factor = self._float(best_metrics.get("profit_factor"))
        row.session_edge_after_cost_bps = self._float(best_metrics.get("edge_after_cost_bps"))
        row.london_session_metrics_json = sessions.get("london_session") or {}
        row.new_york_session_metrics_json = sessions.get("new_york_session") or {}
        row.london_new_york_overlap_metrics_json = sessions.get("london_new_york_overlap") or {}
        row.low_liquidity_session_warning = summary.get("low_liquidity_session_warning")

    def _job(self, job_type: str, payload: dict[str, Any], operator: str) -> ResearchJob:
        job = ResearchJob(
            job_id=f"alpha_{int(time.time() * 1000)}",
            job_type=job_type,
            status="running",
            requested_by=operator,
            input_json=payload,
            progress_pct=5,
            started_at=datetime.utcnow(),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def _audit(self, action: str, operator: str, details: dict[str, Any]) -> None:
        self.session.add(
            SettingsActionAudit(
                action=action,
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json={**details, "orders_created": 0},
            )
        )

    def _latest_audit(self, action: str) -> SettingsActionAudit | None:
        return self.session.exec(
            select(SettingsActionAudit).where(SettingsActionAudit.action == action).order_by(SettingsActionAudit.created_at.desc())
        ).first()

    def _recent_paper(self, symbol: str, strategy_id: str) -> dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(hours=int(cfg_get(self.config, "alpha_factory.recent_window_hours", 24) or 24))
        outcomes = list(
            self.session.exec(
                select(PaperExperimentOutcome).where(PaperExperimentOutcome.created_at >= cutoff)
            ).all()
        )
        trades = list(
            self.session.exec(
                select(TradeRecord).where(
                    TradeRecord.status == "closed",
                    TradeRecord.closed_at != None,  # noqa: E711
                    TradeRecord.closed_at >= cutoff,
                )
            ).all()
        )
        pnl = 0.0
        count = 0
        churn = 0
        recent_loss_sources: list[dict[str, Any]] = []
        skipped_other_strategy_trade_count = 0
        strategy_unknown_fallback_count = 0
        strategy_filter_applied = bool(strategy_id)

        for row in outcomes:
            if _norm(row.symbol) != _norm(symbol) or row.strategy_id != strategy_id:
                continue
            count += 1
            pnl += float(row.realized_pnl or 0.0)
            recent_loss_sources.append(
                {
                    "source": "paper_experiment_outcome",
                    "strategy_id": row.strategy_id,
                    "pl": float(row.realized_pnl or 0.0),
                }
            )
            if str(row.exit_reason or "").lower() in ("time", "time_stop", "max_hold", "churn"):
                churn += 1

        for row in trades:
            if _norm(row.symbol) != _norm(symbol):
                continue
            row_strategy = (row.strategy or "").strip()
            if strategy_id and row_strategy:
                if row_strategy != strategy_id:
                    skipped_other_strategy_trade_count += 1
                    continue
                recent_loss_sources.append(
                    {
                        "source": "trade_record",
                        "strategy": row_strategy,
                        "strategy_filter_applied": True,
                        "pl": float(row.pl_dollars or 0.0),
                    }
                )
            elif strategy_id and not row_strategy:
                strategy_unknown_fallback_count += 1
                recent_loss_sources.append(
                    {
                        "source": "trade_record",
                        "strategy": None,
                        "strategy_filter_applied": False,
                        "strategy_unknown_fallback": True,
                        "pl": float(row.pl_dollars or 0.0),
                    }
                )
            else:
                recent_loss_sources.append(
                    {
                        "source": "trade_record",
                        "strategy": row_strategy or None,
                        "strategy_filter_applied": False,
                        "pl": float(row.pl_dollars or 0.0),
                    }
                )
            count += 1
            pnl += float(row.pl_dollars or 0.0)

        cooldown_until = None
        if count >= 2 and pnl < 0:
            cooldown_until = datetime.utcnow() + timedelta(minutes=int(cfg_get(self.config, "alpha_factory.quarantine_cooldown_minutes", 120) or 120))
        return {
            "count": count,
            "pnl": round(pnl, 6),
            "churn": churn,
            "cooldown_until": cooldown_until,
            "recent_loss_sources": recent_loss_sources,
            "strategy_filter_applied": strategy_filter_applied,
            "skipped_other_strategy_trade_count": skipped_other_strategy_trade_count,
            "strategy_unknown_fallback_count": strategy_unknown_fallback_count,
        }

    def _latest_walk_forward_id(self, strategy_id: str) -> str | None:
        row = self.session.exec(
            select(WalkForwardResult).where(WalkForwardResult.strategy_id == strategy_id).order_by(WalkForwardResult.created_at.desc()).limit(1)
        ).first()
        return row.run_id if row else None

    @staticmethod
    def _first_params(grid: dict[str, list[Any]]) -> dict[str, Any]:
        return {k: (v[0] if isinstance(v, list) and v else v) for k, v in grid.items()}

    @staticmethod
    def _family_for(strategy_id: str) -> str:
        sid = str(strategy_id or "")
        if "opening_range" in sid:
            return "new_york_opening_range_breakout"
        if "london_ny_overlap" in sid or "overlap_continuation" in sid:
            return "london_new_york_overlap_continuation"
        if "liquidity_sweep" in sid:
            return "liquidity_sweep_reversal"
        if "london_momentum" in sid:
            return "london_session_momentum"
        if "mean_reversion" in sid:
            return "mean_reversion_snapback"
        if "volatility_breakout" in sid:
            return "volatility_compression_breakout"
        if "breakout" in sid:
            return "breakout_retest"
        return "momentum_continuation"

    @staticmethod
    def _float(value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _drawdown_pct(cls, metrics: dict[str, Any]) -> float | None:
        val = cls._float(metrics.get("max_drawdown_pct"))
        if val is not None:
            return val
        val = cls._float(metrics.get("max_drawdown"))
        return None if val is None else val * 100.0

    @classmethod
    def _cost_bps(cls, cost: dict[str, Any], key: str) -> float | None:
        val = cls._float(cost.get(key))
        return None if val is None else round(val * 10000.0, 4)

    @classmethod
    def _edge_bps(cls, metrics: dict[str, Any], cost: dict[str, Any]) -> float | None:
        exp = cls._float(metrics.get("expectancy"))
        if exp is None:
            return None
        round_trip = cls._float(cost.get("round_trip_cost_pct")) or 0.0
        return round((exp - round_trip) * 10000.0, 4)

    @staticmethod
    def _rank_score(sc: AlphaScorecard) -> float:
        exp = float(sc.expectancy or 0.0)
        pf = float(sc.profit_factor or 0.0)
        sample = min(1.0, int(sc.sample_size or 0) / 50.0)
        edge = float(sc.edge_after_cost_bps or 0.0) / 100.0
        penalty = 1.0 if sc.verdict in ("rejected", "paper_quarantined") else 0.0
        return round(exp * 100.0 + pf + sample + edge - penalty, 6)

    def _scorecard_public(self, sc: AlphaScorecard) -> dict[str, Any]:
        return {
            "id": sc.id,
            "symbol": sc.symbol,
            "asset_class": sc.asset_class,
            "strategy_family": sc.strategy_family,
            "strategy_id": sc.strategy_id,
            "timeframe": sc.timeframe,
            "current_stage": sc.current_stage,
            "sample_size": sc.sample_size,
            "backtest_count": sc.backtest_count,
            "walk_forward_count": sc.walk_forward_count,
            "win_rate": sc.win_rate,
            "expectancy": sc.expectancy,
            "profit_factor": sc.profit_factor,
            "max_drawdown_pct": sc.max_drawdown_pct,
            "cost_bps": sc.cost_bps,
            "spread_bps": sc.spread_bps,
            "slippage_bps": sc.slippage_bps,
            "fee_bps": sc.fee_bps,
            "edge_after_cost_bps": sc.edge_after_cost_bps,
            "recent_paper_trade_count": sc.recent_paper_trade_count,
            "recent_paper_pnl": sc.recent_paper_pnl,
            "recent_churn_count": sc.recent_churn_count,
            "recent_loss_cooldown_until": _iso(sc.recent_loss_cooldown_until),
            "data_freshness_status": sc.data_freshness_status,
            "bar_count": sc.bar_count,
            "quote_freshness": sc.quote_freshness,
            "verdict": sc.verdict,
            "blocker_reasons": sc.blocker_reasons_json or [],
            "promotion_reason": sc.promotion_reason,
            "last_backtest_run_id": sc.last_backtest_run_id,
            "last_walk_forward_run_id": sc.last_walk_forward_run_id,
            "evidence_ids": sc.evidence_ids_json or [],
            "autonomous_generated": sc.autonomous_generated,
            "best_session": sc.best_session,
            "worst_session": sc.worst_session,
            "session_sample_size": sc.session_sample_size,
            "session_win_rate": sc.session_win_rate,
            "session_expectancy": sc.session_expectancy,
            "session_profit_factor": sc.session_profit_factor,
            "session_edge_after_cost_bps": sc.session_edge_after_cost_bps,
            "london_session_metrics": sc.london_session_metrics_json or {},
            "new_york_session_metrics": sc.new_york_session_metrics_json or {},
            "london_new_york_overlap_metrics": sc.london_new_york_overlap_metrics_json or {},
            "low_liquidity_session_warning": sc.low_liquidity_session_warning,
            "session_blocker": (sc.scorecard_json or {}).get("session_metrics", {}).get("session_blocker"),
            "session_next_action": (sc.scorecard_json or {}).get("session_metrics", {}).get("session_next_action"),
            "updated_at": _iso(sc.updated_at),
            "rank_score": self._rank_score(sc),
        }

    @staticmethod
    def _plain_for_candidates(approved: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str:
        if approved:
            c = approved[0]
            return (
                f"{c.get('symbol')} {c.get('strategy_family')} is paper candidate: "
                f"PF {c.get('profit_factor')}, expectancy {c.get('expectancy')}, "
                f"{c.get('sample_size')} trades, edge after cost {c.get('edge_after_cost_bps')} bps."
            )
        if not candidates:
            return "No paper trade. Autonomous research has not produced scorecards yet."
        c = candidates[0]
        return f"No paper trade. Best candidate is {c.get('symbol')} but verdict is {c.get('verdict')}."

    @staticmethod
    def _candidate_plain(sc: AlphaScorecard) -> str:
        return f"{sc.symbol} {sc.strategy_family}: {sc.verdict}. {sc.promotion_reason or ''}".strip()

    @staticmethod
    def _plain_status(can_trade: bool, reason: str, best: list[dict[str, Any]]) -> str:
        if can_trade and best:
            c = best[0]
            return (
                f"{c.get('symbol')} {c.get('strategy_family')} is paper candidate: "
                f"PF {c.get('profit_factor')}, expectancy positive, {c.get('sample_size')} trades."
            )
        if reason == "no_scorecards":
            return "No paper trade. Strategy is unproven. Autonomous research cycle queued."
        if "stale" in reason:
            return "No paper trade. Data stale on top candidates. Autonomous refresh needed."
        return f"No paper trade. {reason.replace('_', ' ')}."

    @staticmethod
    def _reason_no_trade(cards: list[AlphaScorecard]) -> str:
        if not cards:
            return "no_scorecards"
        blockers = Counter()
        for sc in cards:
            for b in sc.blocker_reasons_json or [sc.verdict]:
                blockers[str(b)] += 1
        return blockers.most_common(1)[0][0] if blockers else "no_paper_candidate"

    @staticmethod
    def _data_quality_summary(cards: list[AlphaScorecard]) -> dict[str, Any]:
        counts = Counter(sc.data_freshness_status for sc in cards)
        return {"by_status": dict(counts), "scorecard_count": len(cards)}

    @staticmethod
    def _blocked_symbols(cards: list[AlphaScorecard]) -> list[dict[str, Any]]:
        return [
            {"symbol": sc.symbol, "verdict": sc.verdict, "reasons": sc.blocker_reasons_json or []}
            for sc in cards
            if sc.verdict not in PAPER_ALLOWED_VERDICTS
        ][:30]

    @staticmethod
    def _classify_failure(sc: AlphaScorecard, min_sample: int, min_pf: float) -> str:
        """One reason a scorecard is not a paper candidate (closest unmet gate first)."""
        if sc.verdict in PAPER_ALLOWED_VERDICTS:
            return "qualified"
        sample = int(sc.sample_size or 0)
        exp = sc.expectancy
        pf = sc.profit_factor
        edge = sc.edge_after_cost_bps
        gross = (sc.scorecard_json or {}).get("gross_expectancy_bps")
        if sample == 0:
            return "data_insufficient"
        # Only "missing_cost_model" when there is genuinely no cost evidence at all — a null
        # round-trip on a row that still has spread/slippage/fee is not a missing model.
        has_cost = any(v is not None for v in (sc.cost_bps, sc.spread_bps, sc.slippage_bps, sc.fee_bps))
        if not has_cost:
            return "missing_cost_model"
        if exp is not None and exp <= 0:
            return "negative_expectancy"
        if pf is not None and pf < min_pf:
            return "poor_profit_factor"
        if edge is not None and edge <= 0 and (gross is None or gross > 0):
            return "costs_too_high"
        if sample < min_sample:
            if (exp or 0) > 0 and (pf or 0) >= min_pf and (edge is None or edge > 0):
                return "near_miss"
            return "not_enough_trades"
        if (sc.data_freshness_status or "") not in ("fresh",):
            return "stale_data"
        return "strategy_bad"

    @classmethod
    def _failure_breakdown(cls, cards: list[AlphaScorecard], min_sample: int, min_pf: float) -> dict[str, int]:
        counts: Counter = Counter()
        for sc in cards:
            cat = cls._classify_failure(sc, min_sample, min_pf)
            if cat != "qualified":
                counts[cat] += 1
        return dict(counts)

    @classmethod
    def _top_cost_blockers(cls, cards: list[AlphaScorecard], limit: int = 5) -> list[dict[str, Any]]:
        rows = []
        for sc in cards:
            j = sc.scorecard_json or {}
            edge = sc.edge_after_cost_bps
            gross = j.get("gross_expectancy_bps")
            # cost is the blocker when after-cost edge is non-positive but gross edge was positive
            if edge is not None and edge <= 0 and (gross or 0) > 0:
                rows.append({
                    "symbol": sc.symbol,
                    "strategy_family": sc.strategy_family,
                    "round_trip_cost_bps": sc.cost_bps,
                    "gross_expectancy_bps": gross,
                    "edge_after_cost_bps": edge,
                    "cost_to_edge_ratio": j.get("cost_to_edge_ratio"),
                })
        rows.sort(key=lambda r: (r["round_trip_cost_bps"] or 0), reverse=True)
        return rows[:limit]

    @staticmethod
    def _session_research_summary(cards: list[AlphaScorecard]) -> dict[str, Any]:
        with_session = [c for c in cards if c.best_session]
        best_counts = Counter(c.best_session for c in with_session if c.best_session)
        low_warnings = sum(1 for c in with_session if c.low_liquidity_session_warning)
        closest = sorted(
            with_session,
            key=lambda c: (
                0 if c.verdict not in PAPER_ALLOWED_VERDICTS else -1,
                -(c.session_edge_after_cost_bps or -999999.0),
            ),
        )
        return {
            "session_scorecard_count": len(with_session),
            "best_session_counts": dict(best_counts),
            "low_liquidity_warning_count": low_warnings,
            "closest_session_candidate": None
            if not closest
            else {
                "symbol": closest[0].symbol,
                "strategy_family": closest[0].strategy_family,
                "best_session": closest[0].best_session,
                "session_sample_size": closest[0].session_sample_size,
                "session_edge_after_cost_bps": closest[0].session_edge_after_cost_bps,
                "verdict": closest[0].verdict,
            },
            "plain_english": (
                "No session scorecards yet."
                if not with_session
                else f"{len(with_session)} scorecard(s) include session context; most common best session: {best_counts.most_common(1)[0][0]}."
            ),
        }

    @staticmethod
    def _near_miss_detail(sc: AlphaScorecard, min_sample: int, min_pf: float):
        """(missing_requirement, required_metric, current_metric, distance, next_action). Lower distance = closer."""
        sample = int(sc.sample_size or 0)
        exp = float(sc.expectancy) if sc.expectancy is not None else None
        pf = float(sc.profit_factor) if sc.profit_factor is not None else None
        edge = float(sc.edge_after_cost_bps) if sc.edge_after_cost_bps is not None else None
        dd = float(sc.max_drawdown_pct) if sc.max_drawdown_pct is not None else None
        if exp is not None and exp <= 0:
            return ("positive_expectancy", "expectancy > 0", exp, 3.0 + min(1.0, abs(exp) * 100.0),
                    "Strategy loses gross; redesign entry/exit before more sampling.")
        if edge is not None and edge <= 0:
            return ("positive_edge_after_cost", "edge_after_cost_bps > 0", edge, 2.0 + min(1.0, abs(edge) / 100.0),
                    "After-cost edge is negative; cut cost drag (tier/timeframe) or raise gross edge.")
        if pf is not None and pf < min_pf:
            return ("min_profit_factor", f"profit_factor >= {min_pf}", pf, 1.0 + (min_pf - pf),
                    f"Raise profit factor to {min_pf}+ (now {pf}).")
        if dd is not None and dd > 35.0:
            return ("max_drawdown", "max_drawdown_pct <= 35", dd, 1.5 + min(1.0, (dd - 35.0) / 35.0),
                    "Reduce max drawdown below 35%.")
        if sample < min_sample:
            return ("min_sample_size", f"sample_size >= {min_sample}", sample,
                    (min_sample - sample) / max(1, min_sample),
                    f"Collect {min_sample - sample} more qualified trades (have {sample}).")
        return ("none", "all gates", None, 5.0, "No single unmet gate; re-evaluate scorecard.")

    @staticmethod
    def _session_next_action(sc: AlphaScorecard, min_sample: int) -> str:
        if (sc.session_sample_size or 0) < min_sample:
            return f"{sc.symbol} {sc.best_session or 'session'} needs {min_sample - int(sc.session_sample_size or 0)} more valid session sample(s)."
        if sc.session_edge_after_cost_bps is not None and sc.session_edge_after_cost_bps <= 0:
            return f"{sc.symbol} {sc.best_session or 'session'} has no positive session edge after cost."
        if sc.low_liquidity_session_warning:
            return f"{sc.symbol} session evidence has low-liquidity warning: {sc.low_liquidity_session_warning}"
        return f"{sc.symbol} {sc.best_session or 'session'} session evidence is available for review."

    def _recent_loss_summary(self) -> dict[str, Any]:
        cards = list(
            self.session.exec(
                select(AlphaScorecard)
                .where(AlphaScorecard.recent_loss_cooldown_until != None)  # noqa: E711
                .order_by(AlphaScorecard.updated_at.desc())
                .limit(20)
            ).all()
        )
        return {
            "cooldown_count": len(cards),
            "symbols": [c.symbol for c in cards],
        }

    @staticmethod
    def _next_due(latest: SettingsActionAudit | None) -> str | None:
        if not latest:
            return None
        return (latest.created_at + timedelta(minutes=30)).isoformat() + "Z"

    @staticmethod
    def _next_action(cards: list[AlphaScorecard], latest_backtest: ResearchBacktestRun | None) -> str:
        if not latest_backtest:
            return "Run autonomous research/backtest cycle."
        if not cards:
            return "Build alpha scorecards from latest backtests."
        if not any(c.verdict in PAPER_ALLOWED_VERDICTS for c in cards):
            return "Continue research; current scorecards are unproven or rejected."
        return "Allow paper cycle to consider alpha-approved candidates through the cage."
