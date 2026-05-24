"""Parameter sweep — grid search over DB-configurable ranges."""

from __future__ import annotations

import itertools
import uuid
from typing import Any

from sqlmodel import Session

from app.database import ParameterSetResult
from app.services.engine_config import cfg_get
from app.services.research_backtest_engine import ResearchBacktestEngine


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
    ) -> dict[str, Any]:
        batch_id = str(uuid.uuid4())
        grid = _grid_from_spec(param_grid)[: self.max_combo]
        results: list[dict] = []
        for i, params in enumerate(grid):
            ps_id = f"{batch_id[:8]}-ps{i}"
            out = self.bt.run(strategy_id, symbols, parameters=params, parameter_set_id=ps_id)
            metrics = out.get("metrics") or {}
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
                max_drawdown_pct=(metrics.get("max_drawdown") or 0) * 100,
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
                }
            )
        return {"status": "ok", "batch_id": batch_id, "combinations": len(results), "results": results}
