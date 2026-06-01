"""Alpha Factory parameter sweep facade.

The repo already has a heavier ``ParameterSweepEngine``. This service gives the
autonomous loop a small, deterministic adapter that records best and rejected
sets without introducing optional hyperopt dependencies as boot requirements.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ParameterSetResult, ResearchBacktestRun
from app.services.research_backtest_engine import ResearchBacktestEngine


class ParameterSweepService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def run_sweep(
        self,
        *,
        strategy_id: str,
        symbols: list[str],
        parameter_grid: dict[str, list[Any]],
        timeframe: str = "5Min",
        max_trials: int = 8,
    ) -> dict[str, Any]:
        combos = self._grid(parameter_grid, max_trials=max_trials)
        engine = ResearchBacktestEngine(self.session, self.config)
        results: list[dict[str, Any]] = []
        for idx, params in enumerate(combos):
            psid = f"alpha_ps_{uuid.uuid4().hex[:10]}"
            out = engine.run(strategy_id, symbols, parameters=params, parameter_set_id=psid, timeframe=timeframe)
            metrics = dict(out.get("metrics") or (out.get("result") or {}).get("metrics") or {})
            score = self._objective(metrics)
            rejected, reject_reason = self._rejection(metrics)
            row = ParameterSetResult(
                parameter_set_id=psid,
                run_id=str(out.get("run_id") or ""),
                strategy_id=strategy_id,
                parameters_json=params,
                num_trades=int(metrics.get("num_trades") or 0),
                win_rate=self._float_or_none(metrics.get("win_rate")),
                avg_win=self._float_or_none(metrics.get("avg_win")),
                avg_loss=self._float_or_none(metrics.get("avg_loss")),
                expectancy=self._float_or_none(metrics.get("expectancy")),
                profit_factor=self._float_or_none(metrics.get("profit_factor")),
                max_drawdown_pct=self._drawdown_pct(metrics),
                sharpe=self._float_or_none(metrics.get("sharpe")),
                estimated_fees_pct=self._cost_pct(metrics, "fee_pct"),
                estimated_slippage_pct=self._cost_pct(metrics, "slippage_pct"),
                implementation_shortfall_pct=self._cost_pct(metrics, "round_trip_cost_pct"),
                reject_reason=reject_reason,
                status="rejected" if rejected else "completed",
                created_at=datetime.utcnow(),
            )
            self.session.add(row)
            results.append(
                {
                    "trial": idx + 1,
                    "parameter_set_id": psid,
                    "run_id": out.get("run_id"),
                    "parameters": params,
                    "metrics": metrics,
                    "objective": score,
                    "status": row.status,
                    "reject_reason": reject_reason,
                }
            )
        best = max([r for r in results if r["status"] != "rejected"] or results, key=lambda r: r["objective"], default=None)
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "symbols": symbols,
            "tested_combinations": len(results),
            "best_parameter_set": best,
            "rejected_sets": [r for r in results if r["status"] == "rejected"],
            "stability_score": self._stability(results),
            "overfit_warning": self._overfit_warning(results),
            "results": results,
        }

    def latest_summary(self) -> dict[str, Any]:
        rows = list(
            self.session.exec(select(ParameterSetResult).order_by(ParameterSetResult.created_at.desc()).limit(100)).all()
        )
        if not rows:
            return {"status": "empty", "tested_combinations": 0, "best_parameter_set": None, "rejected_sets": []}
        best = max(rows, key=lambda r: float(r.expectancy or -999))
        return {
            "status": "ok",
            "tested_combinations": len(rows),
            "best_parameter_set": {
                "parameter_set_id": best.parameter_set_id,
                "strategy_id": best.strategy_id,
                "expectancy": best.expectancy,
                "profit_factor": best.profit_factor,
                "num_trades": best.num_trades,
            },
            "rejected_sets": [
                {"parameter_set_id": r.parameter_set_id, "strategy_id": r.strategy_id, "reason": r.reject_reason}
                for r in rows
                if r.status == "rejected" or r.reject_reason
            ][:20],
        }

    @staticmethod
    def _grid(grid: dict[str, list[Any]], *, max_trials: int) -> list[dict[str, Any]]:
        if not grid:
            return [{}]
        keys = list(grid.keys())
        combos = itertools.product(*[grid[k] or [None] for k in keys])
        return [dict(zip(keys, combo)) for combo in itertools.islice(combos, max_trials)]

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _drawdown_pct(cls, metrics: dict[str, Any]) -> float | None:
        dd = cls._float_or_none(metrics.get("max_drawdown_pct"))
        if dd is not None:
            return dd
        dd = cls._float_or_none(metrics.get("max_drawdown"))
        return None if dd is None else dd * 100.0

    @staticmethod
    def _cost_pct(metrics: dict[str, Any], key: str) -> float | None:
        cost = metrics.get("cost_model") or {}
        try:
            return None if cost.get(key) is None else float(cost.get(key))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _objective(cls, metrics: dict[str, Any]) -> float:
        exp = cls._float_or_none(metrics.get("expectancy")) or 0.0
        pf = cls._float_or_none(metrics.get("profit_factor")) or 0.0
        trades = cls._float_or_none(metrics.get("num_trades")) or 0.0
        dd = cls._drawdown_pct(metrics) or 0.0
        return exp * 100.0 + pf + min(trades / 50.0, 1.0) - dd / 100.0

    @classmethod
    def _rejection(cls, metrics: dict[str, Any]) -> tuple[bool, str | None]:
        trades = int(metrics.get("num_trades") or 0)
        exp = cls._float_or_none(metrics.get("expectancy"))
        pf = cls._float_or_none(metrics.get("profit_factor"))
        if trades < 5:
            return True, "tiny_sample"
        if exp is not None and exp <= 0:
            return True, "negative_expectancy_after_cost"
        if pf is not None and pf < 1.0:
            return True, "profit_factor_below_one"
        return False, None

    @staticmethod
    def _stability(results: list[dict[str, Any]]) -> float:
        if not results:
            return 0.0
        accepted = [r for r in results if r["status"] != "rejected"]
        return round(len(accepted) / max(len(results), 1), 4)

    @staticmethod
    def _overfit_warning(results: list[dict[str, Any]]) -> str | None:
        if len(results) < 3:
            return "too_few_parameter_sets_for_stability"
        accepted = [r for r in results if r["status"] != "rejected"]
        if len(accepted) == 1:
            return "single_parameter_set_wins_only"
        return None
