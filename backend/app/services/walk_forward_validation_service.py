"""Walk-forward validation facade for Alpha Factory.

Uses existing cached-bar backtest infrastructure where possible. This service is
research-only and records validation rows; it does not submit orders.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ResearchBacktestRun, WalkForwardResult
from app.services.research_backtest_engine import ResearchBacktestEngine


class WalkForwardValidationService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def run_validation(
        self,
        *,
        strategy_id: str,
        symbol: str,
        parameters: Optional[dict[str, Any]] = None,
        timeframe: str = "5Min",
        windows: int = 3,
    ) -> dict[str, Any]:
        engine = ResearchBacktestEngine(self.session, self.config)
        run_id = f"wf_{uuid.uuid4().hex[:12]}"
        rows: list[WalkForwardResult] = []
        test_expectancies: list[float] = []
        for idx in range(max(1, windows)):
            lookback = max(10, 30 + idx * 15)
            train = engine.run(strategy_id, [symbol], parameters=parameters or {}, lookback_days=lookback, timeframe=timeframe)
            test = engine.run(strategy_id, [symbol], parameters=parameters or {}, lookback_days=max(10, lookback // 2), timeframe=timeframe)
            train_metrics = dict(train.get("metrics") or (train.get("result") or {}).get("metrics") or {})
            test_metrics = dict(test.get("metrics") or (test.get("result") or {}).get("metrics") or {})
            if test_metrics.get("expectancy") is not None:
                test_expectancies.append(float(test_metrics.get("expectancy") or 0.0))
            row = WalkForwardResult(
                run_id=run_id,
                strategy_id=strategy_id,
                window_index=idx,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                parameters_json=parameters or {},
                status="completed",
                created_at=datetime.utcnow(),
            )
            self.session.add(row)
            rows.append(row)
        degradation = self._degradation(rows)
        verdict = self._verdict(rows, degradation)
        return {
            "status": "ok",
            "run_id": run_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "windows": len(rows),
            "train_metrics": rows[-1].train_metrics if rows else {},
            "test_metrics": rows[-1].test_metrics if rows else {},
            "degradation_ratio": degradation,
            "stability_score": round(sum(1 for x in test_expectancies if x > 0) / max(len(test_expectancies), 1), 4),
            "verdict": verdict,
        }

    def latest_for(self, strategy_id: str, symbol: Optional[str] = None) -> dict[str, Any] | None:
        del symbol
        row = self.session.exec(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == strategy_id)
            .order_by(WalkForwardResult.created_at.desc())
            .limit(1)
        ).first()
        if not row:
            return None
        return {
            "run_id": row.run_id,
            "strategy_id": row.strategy_id,
            "window_index": row.window_index,
            "status": row.status,
            "train_metrics": row.train_metrics,
            "test_metrics": row.test_metrics,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }

    @staticmethod
    def _metric(metrics: dict[str, Any], key: str) -> float | None:
        try:
            value = metrics.get(key)
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _degradation(cls, rows: list[WalkForwardResult]) -> float:
        ratios: list[float] = []
        for row in rows:
            train = cls._metric(row.train_metrics or {}, "expectancy")
            test = cls._metric(row.test_metrics or {}, "expectancy")
            if train is not None and train > 0 and test is not None:
                ratios.append(test / train)
        if not ratios:
            return 1.0
        return round(sum(ratios) / len(ratios), 4)

    @classmethod
    def _verdict(cls, rows: list[WalkForwardResult], degradation: float) -> str:
        if not rows:
            return "insufficient_sample"
        latest = rows[-1].test_metrics or {}
        exp = cls._metric(latest, "expectancy")
        pf = cls._metric(latest, "profit_factor")
        trades = int(latest.get("num_trades") or 0)
        if trades < 5:
            return "insufficient_sample"
        if exp is not None and exp <= 0:
            return "reject_negative_test_expectancy"
        if pf is not None and pf < 1.0:
            return "reject_profit_factor_collapse"
        if degradation < 0.5:
            return "reject_overfit_degradation"
        return "pass"
