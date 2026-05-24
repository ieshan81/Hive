"""Deterministic quant formulas — no mock values."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np


def return_pct(entry_price: float, exit_price: float) -> float:
    if entry_price == 0:
        return 0.0
    return (exit_price - entry_price) / entry_price


def pl_dollars(entry_price: float, exit_price: float, quantity: float, side: str = "long") -> float:
    if side == "short":
        return (entry_price - exit_price) * quantity
    return (exit_price - entry_price) * quantity


def drawdown(current_equity: float, equity_peak: float) -> float:
    if equity_peak <= 0:
        return 0.0
    return (equity_peak - current_equity) / equity_peak


def max_drawdown(equity_series: list[float]) -> float:
    if len(equity_series) < 2:
        return 0.0
    peak = equity_series[0]
    max_dd = 0.0
    for eq in equity_series:
        peak = max(peak, eq)
        dd = drawdown(eq, peak)
        max_dd = max(max_dd, dd)
    return max_dd


def win_rate(wins: int, total: int) -> Optional[float]:
    if total == 0:
        return None
    return wins / total


def average_win(returns: list[float]) -> Optional[float]:
    wins = [r for r in returns if r > 0]
    if not wins:
        return None
    return sum(wins) / len(wins)


def average_loss(returns: list[float]) -> Optional[float]:
    losses = [abs(r) for r in returns if r < 0]
    if not losses:
        return None
    return sum(losses) / len(losses)


def expectancy(wr: float, avg_win: float, avg_loss: float) -> float:
    return (wr * avg_win) - ((1 - wr) * avg_loss)


def profit_factor(gross_profit: float, gross_loss: float) -> Optional[float]:
    if gross_loss == 0:
        return None
    return gross_profit / abs(gross_loss)


def risk_reward(avg_win: float, avg_loss: float) -> Optional[float]:
    if avg_loss == 0:
        return None
    return avg_win / avg_loss


def position_risk_dollars(entry_price: float, stop_loss_price: float, quantity: float) -> float:
    return abs(entry_price - stop_loss_price) * quantity


def position_quantity(max_risk_dollars: float, entry_price: float, stop_loss_price: float) -> float:
    risk_per_share = abs(entry_price - stop_loss_price)
    if risk_per_share == 0:
        return 0.0
    return max_risk_dollars / risk_per_share


def max_risk_dollars(account_equity: float, max_risk_per_trade: float) -> float:
    return account_equity * max_risk_per_trade


def volatility(returns: list[float]) -> Optional[float]:
    if len(returns) < 2:
        return None
    return float(np.std(returns, ddof=1))


def rolling_volatility(returns: list[float], window: int) -> Optional[float]:
    if len(returns) < window:
        return None
    return volatility(returns[-window:])


def sharpe_ratio(returns: list[float], risk_free: float = 0.0) -> Optional[float]:
    if len(returns) < 30:
        return None
    excess = [r - risk_free for r in returns]
    vol = volatility(excess)
    if vol is None or vol == 0:
        return None
    return (sum(excess) / len(excess)) / vol * math.sqrt(252)


def sortino_ratio(returns: list[float], risk_free: float = 0.0) -> Optional[float]:
    if len(returns) < 30:
        return None
    excess = [r - risk_free for r in returns]
    downside = [r for r in excess if r < 0]
    if len(downside) < 2:
        return None
    downside_dev = float(np.std(downside, ddof=1))
    if downside_dev == 0:
        return None
    return (sum(excess) / len(excess)) / downside_dev * math.sqrt(252)


def correlation(series_a: list[float], series_b: list[float]) -> Optional[float]:
    if len(series_a) != len(series_b) or len(series_a) < 2:
        return None
    return float(np.corrcoef(series_a, series_b)[0, 1])


def rolling_correlation(series_a: list[float], series_b: list[float], window: int) -> Optional[float]:
    if len(series_a) < window or len(series_b) < window:
        return None
    return correlation(series_a[-window:], series_b[-window:])


def z_score(current_value: float, rolling_mean: float, rolling_std: float) -> Optional[float]:
    if rolling_std == 0:
        return None
    return (current_value - rolling_mean) / rolling_std


def pairs_spread(asset_a_price: float, asset_b_price: float, hedge_ratio: float) -> float:
    return asset_a_price - hedge_ratio * asset_b_price


def pairs_z_score(spread_series: list[float]) -> Optional[float]:
    if len(spread_series) < 2:
        return None
    mean = sum(spread_series) / len(spread_series)
    std = float(np.std(spread_series, ddof=1))
    return z_score(spread_series[-1], mean, std)


def slippage(expected_price: float, fill_price: float) -> float:
    if expected_price == 0:
        return 0.0
    return abs(fill_price - expected_price) / expected_price


def edge_to_cost(expected_edge: float, estimated_total_cost: float) -> Optional[float]:
    if estimated_total_cost == 0:
        return None
    return expected_edge / estimated_total_cost


def estimated_total_cost(spread_pct: float, slippage_pct: float, fee_pct: float) -> float:
    return spread_pct + slippage_pct + fee_pct


def compute_trade_stats(trade_returns: list[float]) -> dict:
    if not trade_returns:
        return {
            "num_trades": 0,
            "win_rate": None,
            "average_win": None,
            "average_loss": None,
            "expectancy": None,
            "profit_factor": None,
            "max_drawdown": None,
        }
    wins = sum(1 for r in trade_returns if r > 0)
    wr = win_rate(wins, len(trade_returns)) or 0.0
    aw = average_win(trade_returns) or 0.0
    al = average_loss(trade_returns) or 0.0
    gp = sum(r for r in trade_returns if r > 0)
    gl = sum(r for r in trade_returns if r < 0)
    equity = [1.0]
    for r in trade_returns:
        equity.append(equity[-1] * (1 + r))
    return {
        "num_trades": len(trade_returns),
        "win_rate": wr,
        "average_win": aw,
        "average_loss": al,
        "expectancy": expectancy(wr, aw, al),
        "profit_factor": profit_factor(gp, gl),
        "max_drawdown": max_drawdown(equity),
    }
