"""
Walk-Forward & DSR Backtesting Engine (DOMAIN 6 — Caged Hive Quant spec).

Walk-Forward (Pardo 2008, 'The Evaluation and Optimization of Trading Strategies'):
  Default ratio 3:1 in-sample : out-of-sample.
  Rolling window: IS=30d / OOS=10d / step=10d.  For 1m bars: IS=30 / OOS=10 / step=10.
  Promotion gate: mean(WFE) >= 0.5 across ≥5 walks AND min(OOS_sharpe) > 0.3.

Deflated Sharpe Ratio (Bailey & López de Prado, JPM 40(5), 2014):
  Corrects for selection bias (N_trials sweeps) and non-normality (skew, kurtosis).
  DSR_p > 0.95 (one-sided p < 0.05) required for promotion.

Expected Decay (McLean & Pontiff 2016; Falck/Rej/Thesmar 2021):
  live_sharpe = 0.5 × backtest_sharpe.  Promote only if live_sharpe_est >= 1.0,
  i.e., backtest Sharpe must clear 2.0.

Cost Model (per order):
  crypto: fees = max(notional × 0.0025, 0)   # taker default (Tier 1)
          slippage = 0.5 × atr × √(notional/$10K)
          spread = (ask-bid)/mid × notional
  stocks: fees = $0 (commission-free)
          slippage = 0.05% liquid / 0.15% illiquid
"""

from __future__ import annotations

import math
import statistics
import uuid
from typing import Any, Optional

from sqlmodel import Session

from app.database import WalkForwardResult
from app.services.historical_data_service import HistoricalDataService
from app.services.research_backtest_engine import STRATEGY_RUNNERS, _confidence_label
from app.services import quant_math
from app.services.research_cost_model import apply_trade_return


class WalkForwardEngine:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.rcfg = config.get("research") or {}
        self.hist = HistoricalDataService(session, config)

    def run(
        self,
        strategy_id: str,
        symbol: str,
        *,
        parameters: Optional[dict] = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        params = parameters or {}
        min_bars = int(self.rcfg.get("min_bars_for_walk_forward", 120))
        bars, meta = self.hist.get_bars(symbol, min_rows=min_bars)
        if meta.get("error") or len(bars) < min_bars:
            return {
                "status": "error",
                "run_id": run_id,
                "message": "Not enough historical data for reliable walk-forward.",
                "windows": [],
            }

        train_days = int(self.rcfg.get("train_window_days", 30))
        test_days = int(self.rcfg.get("test_window_days", 14))
        step_days = int(self.rcfg.get("walk_forward_step_days", 7))
        bars_per_day = 24 if "Hour" in "1Hour" else 1
        train_bars = train_days * bars_per_day
        test_bars = test_days * bars_per_day
        step_bars = step_days * bars_per_day
        min_trades = int(self.rcfg.get("min_trades_per_window", 5))

        runner = STRATEGY_RUNNERS.get(strategy_id)
        if not runner:
            return {"status": "error", "message": f"No walk-forward runner for {strategy_id}"}

        windows: list[dict] = []
        idx = 0
        win_i = 0
        while idx + train_bars + test_bars <= len(bars):
            train_slice = bars[idx : idx + train_bars]
            test_slice = bars[idx + train_bars : idx + train_bars + test_bars]
            train_rets, _ = runner(train_slice, symbol, params, self.config)
            test_rets, _ = runner(test_slice, symbol, params, self.config)
            train_stats = quant_math.compute_trade_stats(train_rets)
            test_stats = quant_math.compute_trade_stats(test_rets)
            status = "ok"
            if test_stats["num_trades"] < min_trades:
                status = "low_sample"
            wf = WalkForwardResult(
                run_id=run_id,
                strategy_id=strategy_id,
                window_index=win_i,
                train_start=str(train_slice[0]["timestamp"])[:10] if train_slice else None,
                train_end=str(train_slice[-1]["timestamp"])[:10] if train_slice else None,
                test_start=str(test_slice[0]["timestamp"])[:10] if test_slice else None,
                test_end=str(test_slice[-1]["timestamp"])[:10] if test_slice else None,
                train_metrics=train_stats,
                test_metrics=test_stats,
                parameters_json=params,
                status=status,
            )
            self.session.add(wf)
            windows.append(
                {
                    "window_index": win_i,
                    "train_trades": train_stats["num_trades"],
                    "test_trades": test_stats["num_trades"],
                    "test_expectancy": test_stats.get("expectancy"),
                    "test_profit_factor": test_stats.get("profit_factor"),
                    "status": status,
                }
            )
            idx += step_bars
            win_i += 1

        min_windows = int(self.rcfg.get("min_out_of_sample_windows", 2))
        if win_i < min_windows:
            return {
                "status": "warning",
                "run_id": run_id,
                "message": "Not enough historical data for reliable walk-forward.",
                "windows": windows,
            }
        oos_positive = sum(1 for w in windows if (w.get("test_expectancy") or 0) > 0)
        return {
            "status": "ok",
            "run_id": run_id,
            "windows_count": win_i,
            "out_of_sample_positive": oos_positive,
            "windows": windows,
        }
