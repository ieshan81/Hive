"""Parameter sweep — grid search over DB-configurable ranges."""

from __future__ import annotations

import itertools
import uuid
from typing import Any, Optional

from sqlmodel import Session

from app.database import ParameterSetResult
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.research_batch_analyzer import ResearchBatchAnalyzer
from app.services.research_memory_service import ResearchMemoryService


def _grid_from_spec(spec: dict) -> list[dict]:
    keys = []
    values = []
    for k, v in spec.items():
        if isinstance(v, list) and v and not isinstance(v[0], list):
            keys.append(k)
            values.append(v)
    if not keys:
        return [{}]
    combos = []
    for prod in itertools.product(*values):
        combos.append(dict(zip(keys, prod)))
    return combos


class ParameterSweepEngine:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.bt = ResearchBacktestEngine(session, config)
        self.max_combo = int((config.get("research") or {}).get("sweep_max_combinations", 24))

    def sweep(
        self,
        strategy_id: str,
        symbols: list[str],
        param_grid: dict[str, list],
        *,
        lookback_days: Optional[int] = None,
        date_warning: Optional[str] = None,
        coverage_summary: Optional[dict] = None,
    ) -> dict[str, Any]:
        batch_id = str(uuid.uuid4())
        prefix = batch_id[:8]
        grid = _grid_from_spec(param_grid)[: self.max_combo]
        mem = ResearchMemoryService(self.session, self.config)
        results: list[dict] = []
        for i, params in enumerate(grid):
            ps_id = f"{prefix}-ps{i}"
            out = self.bt.run(
                strategy_id,
                symbols,
                parameters=params,
                parameter_set_id=ps_id,
                lookback_days=lookback_days,
            )
            if out.get("run_id"):
                mem.from_backtest_run(out["run_id"])
            metrics = out.get("metrics") or {}
            mdd_pct = (metrics.get("max_drawdown") or 0) * 100
            row = ParameterSetResult(
                parameter_set_id=ps_id,
                run_id=out.get("run_id", batch_id),
                strategy_id=strategy_id,
                parameters_json=params,
                num_trades=metrics.get("num_trades", 0),
                win_rate=metrics.get("win_rate"),
                avg_win=metrics.get("avg_win"),
                avg_loss=metrics.get("avg_loss"),
                expectancy=metrics.get("expectancy"),
                profit_factor=metrics.get("profit_factor"),
                max_drawdown_pct=mdd_pct,
                estimated_fees_pct=(metrics.get("cost_model") or {}).get("fee_pct"),
                estimated_slippage_pct=(metrics.get("cost_model") or {}).get("slippage_pct"),
                status=out.get("status", "completed"),
                reject_reason="; ".join(out.get("result", {}).get("warnings") or [])[:200] or None,
            )
            self.session.add(row)
            results.append(
                {
                    "parameter_set_id": ps_id,
                    "parameters": params,
                    "status": out.get("status"),
                    "num_trades": metrics.get("num_trades", 0),
                    "expectancy": metrics.get("expectancy"),
                    "profit_factor": metrics.get("profit_factor"),
                    "max_drawdown_pct": mdd_pct,
                    "win_rate": metrics.get("win_rate"),
                }
            )
        self.session.flush()
        analysis = ResearchBatchAnalyzer(self.session, self.config).analyze_sweep(
            batch_id,
            strategy_id,
            results,
            date_warning=date_warning,
            coverage_summary=coverage_summary,
        )
        return {
            "status": "ok",
            "batch_id": batch_id,
            "combinations": len(results),
            "results": results,
            "batch_analysis": analysis,
        }
