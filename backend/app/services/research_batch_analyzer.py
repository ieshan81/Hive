"""Post-batch research analysis — memories, rejections, sweep variation."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ParameterSetResult, ResearchBacktestRun, StrategyCandidate
from app.services.research_memory_service import ResearchMemoryService
from app.services.research_performance import evaluate_metrics


def _metric_signature(row: dict) -> str:
    keys = ("expectancy", "profit_factor", "num_trades", "max_drawdown_pct", "win_rate")
    parts = [str(row.get(k)) for k in keys]
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


class ResearchBatchAnalyzer:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.mem = ResearchMemoryService(session, config)
        self.rcfg = config.get("research") or {}

    def analyze_sweep(
        self,
        batch_id: str,
        strategy_id: str,
        sweep_results: list[dict],
        *,
        date_warning: Optional[str] = None,
        coverage_summary: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Create memories + rejected strategy from full parameter sweep."""
        memories_created = 0
        prefix = batch_id[:8]
        rows = list(
            self.session.exec(
                select(ParameterSetResult).where(
                    ParameterSetResult.parameter_set_id.like(f"{prefix}%")
                )
            ).all()
        )
        if not rows:
            rows = self._rows_from_results(sweep_results)

        # Per-run memories from ResearchBacktestRun in batch
        runs = list(
            self.session.exec(
                select(ResearchBacktestRun).where(
                    ResearchBacktestRun.parameter_set_id.like(f"{prefix}%")
                )
            ).all()
        )
        for run in runs:
            memories_created += self.mem.from_backtest_run(run.run_id)

        # Aggregate batch metrics (median / worst of sweep)
        agg = self._aggregate_sweep_metrics(rows)
        batch_eval = evaluate_metrics(agg, self.config)

        # Parameter variation detection
        variation_warning = self._detect_no_variation(sweep_results, rows)
        neg_all = all(
            getattr(r, "expectancy", None) is not None and float(r.expectancy) < 0
            for r in rows
        ) if rows else False
        if neg_all and len(rows) >= 3:
            self.mem.create_typed(
                "repeated_losing_parameter_family",
                title=f"Repeated losing parameters: {strategy_id}",
                summary=f"All {len(rows)} parameter sets in batch showed negative expectancy.",
                strategy_id=strategy_id,
                evidence={"batch_id": batch_id, "combinations": len(rows)},
            )
            memories_created += 1

        if variation_warning:
            self.mem.create_typed(
                "parameter_sweep_no_variation",
                title=f"Parameter sweep may not affect {strategy_id}",
                summary=variation_warning,
                strategy_id=strategy_id,
                evidence={"batch_id": batch_id, "combinations": len(sweep_results), **agg},
            )
            memories_created += 1

        # Batch-level rejection memory (user example)
        if batch_eval["reject"]:
            reason = batch_eval["rejection_reason"] or "weak batch metrics"
            title = f"{strategy_id} rejected in current batch: {reason}"
            summary = (
                f"Batch aggregate expectancy {agg.get('expectancy')}, "
                f"PF {agg.get('profit_factor')}, trades {agg.get('num_trades')}, "
                f"max DD {agg.get('max_drawdown_pct')}%."
            )
            if "negative expectancy" in reason and "profit_factor" in reason:
                summary = (
                    f"{strategy_id} rejected in current batch: negative expectancy, "
                    f"low profit factor, extreme drawdown after costs."
                )
            self.mem.create_typed(
                "rejected_strategy_memory",
                title=title,
                summary=summary,
                strategy_id=strategy_id,
                evidence={"batch_id": batch_id, "aggregate": agg, "evaluation": batch_eval},
                action_status="rejected",
            )
            memories_created += 1
            self._upsert_rejected_candidate(strategy_id, batch_id, reason, agg, batch_eval)

        # Specific memory types from aggregate
        exp = agg.get("expectancy")
        pf = agg.get("profit_factor")
        mdd = agg.get("max_drawdown_pct", 0)
        if exp is not None and float(exp) < 0:
            self.mem.create_typed(
                "backtest_failure_pattern",
                title=f"Negative expectancy: {strategy_id}",
                summary=f"Batch expectancy {float(exp):.5f} after costs across {len(sweep_results)} parameter sets.",
                strategy_id=strategy_id,
                evidence={"batch_id": batch_id, **agg},
            )
            memories_created += 1
        if pf is not None and float(pf) < 1:
            self.mem.create_typed(
                "spread_kills_edge_pattern",
                title=f"Costs killed edge: {strategy_id}",
                summary=f"Profit factor {float(pf):.3f} — gross edge likely lost to spread/fees/slippage.",
                strategy_id=strategy_id,
                evidence={"batch_id": batch_id, **agg},
            )
            memories_created += 1
        if mdd and float(mdd) >= 50:
            self.mem.create_typed(
                "backtest_failure_pattern",
                title=f"High drawdown: {strategy_id}",
                summary=f"Max drawdown ~{float(mdd):.1f}% in batch research.",
                strategy_id=strategy_id,
                evidence={"batch_id": batch_id, **agg},
            )
            memories_created += 1

        if not batch_eval["promote_allowed"]:
            self.mem.create_typed(
                "do_not_promote_recommendation",
                title=f"Do not promote {strategy_id}",
                summary=batch_eval.get("rejection_reason") or "Metrics below research gates.",
                strategy_id=strategy_id,
                evidence={
                    "batch_id": batch_id,
                    "recommended_action": "do_not_promote",
                    "promote_allowed": False,
                    "date_warning": date_warning,
                    "coverage": coverage_summary,
                },
            )
            memories_created += 1

        if date_warning:
            self.mem.create_typed(
                "sample_size_warning",
                title="Historical data date warning",
                summary=date_warning,
                strategy_id=strategy_id,
                evidence={"coverage": coverage_summary or {}},
            )
            memories_created += 1

        return {
            "memories_created": memories_created,
            "batch_evaluation": batch_eval,
            "aggregate_metrics": agg,
            "parameter_variation_warning": variation_warning,
            "rejected": batch_eval["reject"],
        }

    def _rows_from_results(self, results: list[dict]) -> list:
        class R:
            pass

        out = []
        for r in results:
            o = R()
            for k, v in r.items():
                setattr(o, k, v)
            out.append(o)
        return out

    def _aggregate_sweep_metrics(self, rows: list) -> dict[str, Any]:
        if not rows:
            return {"num_trades": 0, "expectancy": None, "profit_factor": None, "max_drawdown_pct": None}
        exps = [float(r.expectancy) for r in rows if getattr(r, "expectancy", None) is not None]
        pfs = [float(r.profit_factor) for r in rows if getattr(r, "profit_factor", None) is not None]
        mdds = [float(r.max_drawdown_pct) for r in rows if getattr(r, "max_drawdown_pct", None) is not None]
        trades = [int(r.num_trades) for r in rows if getattr(r, "num_trades", None)]
        return {
            "num_trades": max(trades) if trades else 0,
            "expectancy": sum(exps) / len(exps) if exps else None,
            "profit_factor": sum(pfs) / len(pfs) if pfs else None,
            "max_drawdown_pct": max(mdds) if mdds else None,
            "win_rate": None,
            "confidence": "low" if (max(trades) if trades else 0) < 20 else "medium",
        }

    def _detect_no_variation(self, sweep_results: list[dict], rows: list) -> Optional[str]:
        sigs: dict[str, int] = {}
        source = sweep_results if sweep_results else []
        for r in source:
            sig = _metric_signature(r if isinstance(r, dict) else {
                "expectancy": getattr(r, "expectancy", None),
                "profit_factor": getattr(r, "profit_factor", None),
                "num_trades": getattr(r, "num_trades", None),
                "max_drawdown_pct": getattr(r, "max_drawdown_pct", None),
            })
            sigs[sig] = sigs.get(sig, 0) + 1
        for sig, count in sigs.items():
            if count >= 5:
                return (
                    "Parameter sweep may not be influencing strategy logic — "
                    f"{count} parameter sets produced identical metrics. "
                    "Inspect edge_multiplier, max_hold_bars, ATR multipliers, and spread caps in backtest runner."
                )
        return None

    def _upsert_rejected_candidate(
        self,
        strategy_id: str,
        batch_id: str,
        reason: str,
        metrics: dict,
        evaluation: dict,
    ) -> None:
        cand = self.session.exec(
            select(StrategyCandidate).where(StrategyCandidate.strategy_id == strategy_id)
        ).first()
        if not cand:
            cand = StrategyCandidate(strategy_id=strategy_id)
        cand.status = "rejected"
        cand.promotion_stage = "rejected"
        cand.rejection_reason = reason[:500]
        cand.run_id = batch_id
        cand.metrics_json = metrics
        cand.evidence_json = {"evaluation": evaluation, "batch_id": batch_id}
        cand.human_approved = False
        cand.updated_at = __import__("datetime").datetime.utcnow()
        self.session.add(cand)
