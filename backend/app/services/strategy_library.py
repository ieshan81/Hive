"""Configurable strategy research library — parameters from DB, not hard-coded thresholds."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import StrategyDefinition


STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "strategy_id": "crypto_push_pull",
        "strategy_name": "Crypto Push-Pull Momentum",
        "strategy_family": "momentum",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"],
        "timeframe": "1Hour",
        "description": "Multi-horizon momentum with edge-over-cost and ATR stop.",
        "parameters_json": {
            "momentum_lookbacks_hours": [1, 3, 6, 12],
            "atr_periods": [14, 21],
            "atr_multipliers": [1.5, 2.0, 2.5],
            "edge_multipliers": [1.2, 1.5, 2.0, 2.5],
            "spread_caps_pct": [0.002, 0.003, 0.005],
            "max_hold_hours": [6, 12, 24],
        },
    },
    {
        "strategy_id": "opening_range_breakout",
        "strategy_name": "Opening Range Breakout",
        "strategy_family": "breakout",
        "asset_class": "stock",
        "universe": ["SPY", "QQQ", "AAPL"],
        "timeframe": "5Min",
        "parameters_json": {
            "range_windows_minutes": [15, 30, 60],
            "breakout_thresholds_pct": [0.001, 0.002, 0.003],
            "volume_confirmation": [True, False],
            "stop_distance_pct": [0.005, 0.01],
        },
    },
    {
        "strategy_id": "mean_reversion",
        "strategy_name": "Mean Reversion",
        "strategy_family": "mean_reversion",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD"],
        "timeframe": "1Hour",
        "parameters_json": {
            "lookbacks": [12, 24, 48],
            "z_entry": [1.5, 2.0, 2.5],
            "z_exit": [0.25, 0.5],
            "rsi_oversold": [25, 30, 35],
            "rsi_overbought": [65, 70, 75],
        },
    },
    {
        "strategy_id": "pairs_spread_mr",
        "strategy_name": "Pairs Spread Mean Reversion",
        "strategy_family": "pairs",
        "asset_class": "crypto",
        "universe": [["BTC/USD", "ETH/USD"]],
        "timeframe": "1Hour",
        "parameters_json": {"z_entry": [2.0, 2.5], "z_exit": [0.5]},
        "status": "research_only",
    },
    {
        "strategy_id": "volatility_breakout",
        "strategy_name": "Volatility Breakout",
        "strategy_family": "breakout",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "timeframe": "1Hour",
        "parameters_json": {
            "atr_expansion_mult": [1.2, 1.5, 2.0],
            "range_lookback": [14, 21],
            "volume_mult": [1.2, 1.5],
        },
    },
    {
        "strategy_id": "trend_following",
        "strategy_name": "Trend Following",
        "strategy_family": "trend",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD"],
        "timeframe": "1Hour",
        "parameters_json": {
            "fast_ma": [8, 12, 20],
            "slow_ma": [26, 50],
            "momentum_confirm_pct": [0.002, 0.004],
        },
    },
    {
        "strategy_id": "meme_attention_watch",
        "strategy_name": "Meme Attention Watch",
        "strategy_family": "watch",
        "asset_class": "crypto",
        "universe": ["DOGE/USD", "SHIB/USD"],
        "timeframe": "1Hour",
        "parameters_json": {"watch_only": True, "extra_spread_gate_pct": [0.003, 0.004]},
        "status": "research_only",
    },
    {
        "strategy_id": "exit_strategy_tests",
        "strategy_name": "Exit Strategy Tests",
        "strategy_family": "exit",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "DOGE/USD"],
        "timeframe": "1Hour",
        "parameters_json": {
            "exit_modes": ["fixed_stop_tp", "atr_trail", "time_stop", "momentum_reversal", "spread_widen"],
            "stop_pct": [0.01, 0.02],
            "take_profit_pct": [0.02, 0.03],
        },
    },
]


def seed_strategy_library(session: Session) -> int:
    n = 0
    for spec in STRATEGY_CATALOG:
        existing = session.get(StrategyDefinition, spec["strategy_id"])
        if existing:
            continue
        session.add(
            StrategyDefinition(
                strategy_id=spec["strategy_id"],
                strategy_name=spec["strategy_name"],
                strategy_family=spec["strategy_family"],
                parameters_json=spec.get("parameters_json") or {},
                asset_class=spec.get("asset_class", "crypto"),
                universe=spec.get("universe") or [],
                timeframe=spec.get("timeframe", "1Hour"),
                status=spec.get("status", "research_only"),
                description=spec.get("description"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        n += 1
    return n


def list_strategies(session: Session) -> list[dict]:
    rows = session.exec(select(StrategyDefinition)).all()
    if not rows:
        seed_strategy_library(session)
        rows = session.exec(select(StrategyDefinition)).all()
    return [
        {
            "strategy_id": r.strategy_id,
            "strategy_name": r.strategy_name,
            "strategy_family": r.strategy_family,
            "parameters_json": r.parameters_json,
            "asset_class": r.asset_class,
            "universe": r.universe,
            "timeframe": r.timeframe,
            "status": r.status,
            "description": r.description,
        }
        for r in rows
    ]


def get_strategy(session: Session, strategy_id: str) -> StrategyDefinition | None:
    row = session.get(StrategyDefinition, strategy_id)
    if not row:
        seed_strategy_library(session)
        row = session.get(StrategyDefinition, strategy_id)
    return row
