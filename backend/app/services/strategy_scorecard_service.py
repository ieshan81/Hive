"""Strategy scorecard computation — config-driven, no fake metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    LessonNode,
    ParameterSetResult,
    ResearchBacktestRun,
    StrategyPromotionRule,
    StrategyRegistry,
    StrategyScorecard,
)
from app.services.memory_categories import RESEARCH_MEMORY_TYPES
from app.services.research_performance import evaluate_metrics


class StrategyScorecardService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.rcfg = config.get("research") or {}
        self.pcfg = config.get("strategy_promotion") or {}

    def compute(self, strategy_id: str) -> StrategyScorecard:
        reg = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
        ).first()
        metrics = self._gather_metrics(strategy_id)
        mem_score = self._memory_evidence_score(strategy_id)
        eval_res = evaluate_metrics(metrics, self.config)

        wf_rate = metrics.get("walk_forward_pass_rate")
        cost_edge = metrics.get("cost_to_edge_ratio")
        composite = self._composite(metrics, mem_score, wf_rate)

        confidence = eval_res.get("confidence", "low")
        if metrics.get("data_warning"):
            confidence = "low"
        if (metrics.get("expectancy") or 0) < 0:
            confidence = "low"

        row = StrategyScorecard(
            strategy_id=strategy_id,
            as_of=datetime.utcnow(),
            expectancy_net=metrics.get("expectancy"),
            profit_factor_net=metrics.get("profit_factor"),
            max_drawdown=metrics.get("max_drawdown_pct"),
            win_rate=metrics.get("win_rate"),
            sample_size=metrics.get("num_trades"),
            walk_forward_pass_rate=wf_rate,
            cost_to_edge_ratio=cost_edge,
            cost_drag_pct=metrics.get("cost_drag_pct"),
            memory_evidence_score=mem_score,
            composite_score=composite,
            confidence=confidence,
            recommended_action=eval_res.get("recommended_action", "hold"),
            promote_allowed=eval_res.get("promote_allowed", False),
            rejection_reason=eval_res.get("rejection_reason"),
            data_warning=metrics.get("data_warning"),
            parameter_variation_warning=metrics.get("parameter_variation_warning"),
        )
        self.session.add(row)
        if reg:
            reg.current_score = composite
            reg.confidence = confidence
            reg.updated_at = datetime.utcnow()
            self.session.add(reg)
        return row

    def latest(self, strategy_id: str) -> Optional[dict]:
        row = self.session.exec(
            select(StrategyScorecard)
            .where(StrategyScorecard.strategy_id == strategy_id)
            .order_by(StrategyScorecard.created_at.desc())
        ).first()
        return self._serialize(row) if row else None

    def _gather_metrics(self, strategy_id: str) -> dict[str, Any]:
        ps_rows = list(
            self.session.exec(
                select(ParameterSetResult)
                .where(ParameterSetResult.strategy_id == strategy_id)
                .order_by(ParameterSetResult.created_at.desc())
                .limit(30)
            ).all()
        )
        bt = self.session.exec(
            select(ResearchBacktestRun)
            .where(ResearchBacktestRun.strategy_id == strategy_id)
            .order_by(ResearchBacktestRun.created_at.desc())
        ).first()
        if ps_rows:
            exp = sum(float(r.expectancy or 0) for r in ps_rows) / len(ps_rows)
            pf = sum(float(r.profit_factor or 0) for r in ps_rows) / len(ps_rows)
            mdd = max(float(r.max_drawdown_pct or 0) for r in ps_rows)
            trades = max(int(r.num_trades or 0) for r in ps_rows)
            wr = sum(float(r.win_rate or 0) for r in ps_rows) / len(ps_rows)
        elif bt and bt.metrics_json:
            m = bt.metrics_json
            exp = m.get("expectancy")
            pf = m.get("profit_factor")
            mdd = (m.get("max_drawdown") or 0) * 100
            trades = bt.num_trades
            wr = m.get("win_rate")
        else:
            exp = pf = mdd = wr = None
            trades = 0

        cov = (bt.metrics_json or {}).get("date_coverage", {}) if bt else {}
        sigs: dict[str, int] = {}
        for r in ps_rows:
            sig = f"{r.expectancy}|{r.profit_factor}|{r.num_trades}|{r.max_drawdown_pct}"
            sigs[sig] = sigs.get(sig, 0) + 1
        param_warn = None
        if any(c >= 5 for c in sigs.values()):
            param_warn = "Parameter sweep may not be influencing strategy logic."

        cost_drag = None
        if pf is not None and float(pf) < 1.0:
            cost_drag = 1.0 - float(pf)
        cost_edge = 0.5 if pf and float(pf) > 0 else 1.0
        if exp and float(exp) > 0 and cost_drag:
            cost_edge = min(1.0, cost_drag / max(float(exp), 1e-6))

        return {
            "expectancy": exp,
            "profit_factor": pf,
            "max_drawdown_pct": mdd,
            "num_trades": trades,
            "win_rate": wr,
            "data_warning": cov.get("date_warning"),
            "parameter_variation_warning": param_warn,
            "cost_drag_pct": cost_drag,
            "cost_to_edge_ratio": cost_edge,
            "walk_forward_pass_rate": None,
        }

    def _memory_evidence_score(self, strategy_id: str) -> float:
        from app.database import StrategyMemoryLink

        links = list(
            self.session.exec(
                select(StrategyMemoryLink).where(
                    StrategyMemoryLink.strategy_id == strategy_id,
                    StrategyMemoryLink.memory_status == "validated",
                    StrategyMemoryLink.can_influence_ranking == True,  # noqa: E712
                )
            ).all()
        )
        if not links:
            return 0.0
        return min(1.0, len(links) * 0.1)

    def _composite(
        self,
        metrics: dict,
        mem_score: float,
        wf_rate: Optional[float],
    ) -> float:
        rules = self.session.exec(
            select(StrategyPromotionRule).where(
                StrategyPromotionRule.rule_key == "scorecard_composite",
                StrategyPromotionRule.enabled == True,
            )
        ).first()
        w = (rules.threshold_value_json if rules else {}) or {}
        exp = float(metrics.get("expectancy") or 0)
        pf = float(metrics.get("profit_factor") or 0)
        mdd = float(metrics.get("max_drawdown_pct") or 100)
        sample = min(1.0, int(metrics.get("num_trades") or 0) / 100)
        score = (
            w.get("weight_expectancy", 0.25) * max(-1, min(1, exp * 100))
            + w.get("weight_profit_factor", 0.2) * min(2, pf)
            + w.get("weight_drawdown", 0.2) * max(0, 1 - mdd / 100)
            + w.get("weight_sample", 0.15) * sample
            + w.get("weight_memory", 0.1) * mem_score
            + w.get("weight_walk_forward", 0.1) * (wf_rate or 0)
        )
        return round(score, 4)

    def _serialize(self, r: StrategyScorecard) -> dict:
        return {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "as_of": r.as_of.isoformat() + "Z" if r.as_of else None,
            "expectancy_net": r.expectancy_net,
            "profit_factor_net": r.profit_factor_net,
            "max_drawdown": r.max_drawdown,
            "win_rate": r.win_rate,
            "sample_size": r.sample_size,
            "composite_score": r.composite_score,
            "confidence": r.confidence,
            "recommended_action": r.recommended_action,
            "promote_allowed": r.promote_allowed,
            "rejection_reason": r.rejection_reason,
            "data_warning": r.data_warning,
            "parameter_variation_warning": r.parameter_variation_warning,
        }
