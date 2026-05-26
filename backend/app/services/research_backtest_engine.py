"""Research backtest engine — cost-aware, no broker orders, honest empty states."""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.database import BacktestResult, ResearchBacktestRun
from app.services import quant_math
from app.services.engine_config import cfg_get
from app.services.historical_data_service import HistoricalDataService
from app.services.research_cost_model import apply_trade_return, round_trip_cost_pct


from app.services.research_performance import evaluate_metrics


def _backtest_result_label(metrics: dict, config: dict) -> str:
    ev = evaluate_metrics(metrics, config)
    if ev.get("reject"):
        trades = int(metrics.get("num_trades") or 0)
        if trades == 0:
            return "reject"
        pf = metrics.get("profit_factor")
        exp = metrics.get("expectancy")
        if exp is not None and float(exp) < 0:
            return "weak"
        if pf is not None and float(pf) < 1.0:
            return "weak"
        return "reject"
    trades = int(metrics.get("num_trades") or 0)
    low = int((config.get("research") or {}).get("low_sample_trade_threshold", 10))
    if trades < low:
        return "keep_testing"
    pf = metrics.get("profit_factor")
    if pf is not None and float(pf) >= 1.1:
        return "promising"
    return "keep_testing"


def _confidence_label(num_trades: int, research_cfg: dict) -> str:
    low = int(research_cfg.get("low_sample_trade_threshold", 10))
    min_total = int(research_cfg.get("min_total_trades", 20))
    if num_trades < low:
        return "very_low"
    if num_trades < min_total:
        return "low"
    return "medium"


def _run_crypto_push_pull(
    bars: list[dict],
    symbol: str,
    params: dict,
    config: dict,
) -> tuple[list[float], list[str]]:
    warnings: list[str] = []
    cpp = config.get("crypto_push_pull") or {}
    base_thresh = float(params.get("momentum_threshold_1h", cpp.get("momentum_threshold_1h", 0.004)))
    edge_mult = float(params.get("edge_multiplier", 1.0))
    thresh = base_thresh * edge_mult
    lookback = int(params.get("lookback_bars", 1))
    max_hold = int(params.get("max_hold_bars", 0))
    if max_hold <= 0 and params.get("max_hold_hours") is not None:
        max_hold = max(1, int(params.get("max_hold_hours", 24)))
    if max_hold <= 0:
        max_hold = 999
    spread_cap = float(
        params.get("spread_cap_pct", params.get("max_spread_pct", params.get("spread_cap", 999)))
    )
    atr_mult = float(params.get("atr_multiplier", params.get("atr_stop_multiplier", 1.0)))
    returns: list[float] = []
    for i in range(max(lookback + 1, 14), len(bars) - 1):
        c0 = bars[i]["close"]
        c_prev = bars[i - lookback]["close"]
        if c_prev <= 0:
            continue
        m = (c0 - c_prev) / c_prev
        if m <= thresh:
            continue
        bar_range_pct = (bars[i]["high"] - bars[i]["low"]) / c0 * 100 if c0 else 0
        if bar_range_pct > spread_cap:
            continue
        entry = c0
        exit_idx = min(i + max_hold, len(bars) - 1)
        atr_window = bars[max(0, i - 14) : i]
        atr = sum(b["high"] - b["low"] for b in atr_window) / max(len(atr_window), 1)
        stop = entry - atr_mult * atr if atr_mult > 0 else 0
        exit_price = bars[exit_idx]["close"]
        for j in range(i + 1, exit_idx + 1):
            if stop > 0 and bars[j]["low"] < stop:
                exit_price = stop
                break
        gross = (exit_price - entry) / entry
        returns.append(apply_trade_return(gross, symbol, config))
    if not returns:
        warnings.append("No trades triggered with current parameters on available bars")
    return returns, warnings


def _run_mean_reversion(
    bars: list[dict],
    symbol: str,
    params: dict,
    config: dict,
) -> tuple[list[float], list[str]]:
    lookback = int(params.get("lookback", 24))
    z_entry = float(params.get("z_entry", 2.0))
    warnings: list[str] = []
    returns: list[float] = []
    closes = [b["close"] for b in bars]
    for i in range(lookback, len(bars) - 1):
        window = closes[i - lookback : i]
        mu = sum(window) / len(window)
        std = math.sqrt(sum((x - mu) ** 2 for x in window) / max(len(window), 1)) or 1e-9
        z = (closes[i] - mu) / std
        if z < -z_entry:
            gross = (closes[i + 1] - closes[i]) / closes[i]
            returns.append(apply_trade_return(gross, symbol, config))
        elif z > z_entry:
            gross = (closes[i] - closes[i + 1]) / closes[i]
            returns.append(apply_trade_return(gross, symbol, config))
    if not returns:
        warnings.append("Mean reversion: no z-score entries")
    return returns, warnings


def _run_volatility_breakout(
    bars: list[dict],
    symbol: str,
    params: dict,
    config: dict,
) -> tuple[list[float], list[str]]:
    lb = int(params.get("range_lookback", 14))
    mult = float(params.get("atr_expansion_mult", 1.5))
    warnings: list[str] = []
    returns: list[float] = []
    for i in range(lb + 1, len(bars) - 1):
        window = bars[i - lb : i]
        ranges = [b["high"] - b["low"] for b in window]
        avg_r = sum(ranges) / len(ranges) if ranges else 0
        cur_r = bars[i]["high"] - bars[i]["low"]
        if avg_r > 0 and cur_r > avg_r * mult and bars[i]["close"] > bars[i - 1]["close"]:
            gross = (bars[i + 1]["close"] - bars[i]["close"]) / bars[i]["close"]
            returns.append(apply_trade_return(gross, symbol, config))
    if not returns:
        warnings.append("Volatility breakout: no expansion entries")
    return returns, warnings


def _run_trend_following(
    bars: list[dict],
    symbol: str,
    params: dict,
    config: dict,
) -> tuple[list[float], list[str]]:
    fast = int(params.get("fast_ma", 12))
    slow = int(params.get("slow_ma", 26))
    warnings: list[str] = []
    returns: list[float] = []
    closes = [b["close"] for b in bars]
    for i in range(slow, len(bars) - 1):
        f = sum(closes[i - fast : i]) / fast
        s = sum(closes[i - slow : i]) / slow
        prev_f = sum(closes[i - fast - 1 : i - 1]) / fast
        prev_s = sum(closes[i - slow - 1 : i - 1]) / slow
        if prev_f <= prev_s and f > s:
            gross = (closes[i + 1] - closes[i]) / closes[i]
            returns.append(apply_trade_return(gross, symbol, config))
    if not returns:
        warnings.append("Trend: no MA cross signals")
    return returns, warnings


def _run_crypto_push_pull_momentum(bars, symbol, params, config):
    p = dict(params)
    if "momentum_lookback_hours" in p and "lookback_bars" not in p:
        hours = p["momentum_lookback_hours"]
        if isinstance(hours, list):
            hours = hours[0] if hours else 1
        p["lookback_bars"] = max(1, int(hours))
    if "momentum_threshold_1h" not in p:
        cpp = config.get("crypto_push_pull") or {}
        p["momentum_threshold_1h"] = cpp.get("momentum_threshold_1h", 0.004)
    return _run_crypto_push_pull(bars, symbol, p, config)


STRATEGY_RUNNERS = {
    "crypto_push_pull": _run_crypto_push_pull,
    "crypto_push_pull_baseline": _run_crypto_push_pull_momentum,
    "crypto_push_pull_momentum": _run_crypto_push_pull_momentum,
    "mean_reversion": _run_mean_reversion,
    "crypto_mean_reversion": _run_mean_reversion,
    "volatility_breakout": _run_volatility_breakout,
    "crypto_volatility_breakout": _run_volatility_breakout,
    "trend_following": _run_trend_following,
    "crypto_trend_following": _run_trend_following,
}


class ResearchBacktestEngine:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.research_cfg = config.get("research") or {}
        self.hist = HistoricalDataService(session, config)

    def run(
        self,
        strategy_id: str,
        symbols: list[str],
        *,
        parameters: Optional[dict] = None,
        parameter_set_id: Optional[str] = None,
        lookback_days: Optional[int] = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        params = parameters or {}
        ps_id = parameter_set_id or f"ps-{run_id[:8]}"
        all_returns: list[float] = []
        all_warnings: list[str] = []
        date_start = None
        date_end = None
        date_meta: dict[str, Any] = {}
        estimated_spread = True
        lb = lookback_days or int(self.research_cfg.get("default_lookback_days", 90))

        runner = STRATEGY_RUNNERS.get(strategy_id)
        if strategy_id == "meme_attention_watch":
            row = self._save_run(
                run_id,
                strategy_id,
                ps_id,
                symbols,
                status="skipped",
                warnings=["Watch-only strategy — no simulated trades"],
                metrics={},
            )
            return {"status": "skipped", "run_id": run_id, "result": self._serialize_run(row)}

        if strategy_id in ("opening_range_breakout", "pairs_spread_mr"):
            row = self._save_run(
                run_id,
                strategy_id,
                ps_id,
                symbols,
                status="error",
                warnings=[f"{strategy_id} requires stock/pair data pipeline — not enough data in current deploy"],
                metrics={},
            )
            return {"status": "error", "message": row.warnings[0], "run_id": run_id}

        if not runner:
            row = self._save_run(
                run_id,
                strategy_id,
                ps_id,
                symbols,
                status="error",
                warnings=[f"Unknown strategy_id: {strategy_id}"],
                metrics={},
            )
            return {"status": "error", "run_id": run_id}

        min_bars = int(self.research_cfg.get("min_bars_for_backtest", 50))
        alpaca_tf = timeframe if timeframe in ("1Hour", "5Min", "15Min", "1Day") else "1Hour"
        for sym in symbols:
            bars, meta = self.hist.get_bars(
                sym, timeframe=alpaca_tf, min_rows=min_bars, lookback_days=lb
            )
            if meta.get("error"):
                all_warnings.append(f"{sym}: {meta['error']}")
                continue
            if meta.get("date_warning"):
                all_warnings.append(f"{sym}: {meta['date_warning']}")
            date_meta = {**date_meta, **{k: meta[k] for k in meta if k.startswith(("requested_", "actual_", "data_", "date_"))}}
            if bars:
                date_start = date_start or str(bars[0]["timestamp"])[:10]
                date_end = str(bars[-1]["timestamp"])[:10]
            rets, warns = runner(bars, sym, params, self.config)
            all_warnings.extend(warns)
            all_returns.extend(rets)

        if not all_returns:
            row = self._save_run(
                run_id,
                strategy_id,
                ps_id,
                symbols,
                date_start=date_start,
                date_end=date_end,
                status="empty",
                warnings=all_warnings or ["No trades across symbols"],
                metrics={},
            )
            return {"status": "empty", "run_id": run_id, "result": self._serialize_run(row)}

        stats = quant_math.compute_trade_stats(all_returns)
        cost = round_trip_cost_pct(symbols[0] if symbols else "BTC/USD", self.config)
        metrics = {
            **stats,
            "total_return_pct": sum(all_returns) * 100,
            "cost_model": cost,
            "parameters": params,
            "date_coverage": date_meta,
            "timeframe": alpaca_tf,
            "bars_count": sum(len(self.hist.get_bars(s, timeframe=alpaca_tf, min_rows=1)[0]) for s in symbols),
            "result_label": _backtest_result_label(stats, self.config),
        }
        conf = _confidence_label(stats["num_trades"], self.research_cfg)
        row = self._save_run(
            run_id,
            strategy_id,
            ps_id,
            symbols,
            date_start=date_start,
            date_end=date_end,
            status="ok",
            num_trades=stats["num_trades"],
            metrics=metrics,
            warnings=all_warnings,
            confidence=conf,
            estimated_spread=estimated_spread,
        )
        legacy = BacktestResult(
            strategy=strategy_id,
            symbols=symbols,
            date_start=date_start,
            date_end=date_end,
            num_trades=stats["num_trades"],
            total_return_pct=metrics.get("total_return_pct"),
            max_drawdown_pct=(stats.get("max_drawdown") or 0) * 100,
            win_rate=stats.get("win_rate"),
            expectancy=stats.get("expectancy"),
            profit_factor=stats.get("profit_factor"),
            slippage_assumption=cost.get("slippage_pct", 0),
            spread_assumption=cost.get("spread_pct", 0),
            fee_assumption=cost.get("fee_pct", 0),
            status="ok",
            warnings=all_warnings,
        )
        self.session.add(legacy)
        return {"status": "ok", "run_id": run_id, "result": self._serialize_run(row), "metrics": metrics}

    def _save_run(
        self,
        run_id: str,
        strategy_id: str,
        parameter_set_id: str,
        symbols: list[str],
        *,
        date_start=None,
        date_end=None,
        status: str,
        num_trades: int = 0,
        metrics: Optional[dict] = None,
        warnings: Optional[list] = None,
        confidence: str = "low",
        estimated_spread: bool = True,
    ) -> ResearchBacktestRun:
        cost = (metrics or {}).get("cost_model") or round_trip_cost_pct(
            symbols[0] if symbols else "BTC/USD", self.config
        )
        row = ResearchBacktestRun(
            run_id=run_id,
            strategy_id=strategy_id,
            parameter_set_id=parameter_set_id,
            symbols=symbols,
            date_start=date_start,
            date_end=date_end,
            status=status,
            num_trades=num_trades,
            metrics_json=metrics or {},
            cost_model_json=cost,
            sample_size=num_trades,
            confidence_label=confidence,
            warnings=warnings or [],
            estimated_spread=estimated_spread,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_run(self, run_id: str) -> Optional[dict]:
        from sqlmodel import select

        row = self.session.exec(
            select(ResearchBacktestRun).where(ResearchBacktestRun.run_id == run_id)
        ).first()
        return self._serialize_run(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict]:
        from sqlmodel import select

        rows = self.session.exec(
            select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(limit)
        ).all()
        return [self._serialize_run(r) for r in rows]

    def _serialize_run(self, row: ResearchBacktestRun) -> dict:
        return {
            "run_id": row.run_id,
            "id": row.id,
            "strategy_id": row.strategy_id,
            "parameter_set_id": row.parameter_set_id,
            "symbols": row.symbols,
            "date_start": row.date_start,
            "date_end": row.date_end,
            "status": row.status,
            "num_trades": row.num_trades,
            "metrics": row.metrics_json,
            "cost_model": row.cost_model_json,
            "confidence_label": row.confidence_label,
            "result_label": (row.metrics_json or {}).get("result_label"),
            "win_rate": (row.metrics_json or {}).get("win_rate"),
            "expectancy": (row.metrics_json or {}).get("expectancy"),
            "profit_factor": (row.metrics_json or {}).get("profit_factor"),
            "max_drawdown": (row.metrics_json or {}).get("max_drawdown"),
            "timeframe": (row.metrics_json or {}).get("timeframe"),
            "bars_count": (row.metrics_json or {}).get("bars_count"),
            "warnings": row.warnings,
            "estimated_spread": row.estimated_spread,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }
