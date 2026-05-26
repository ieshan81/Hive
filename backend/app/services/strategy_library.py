"""DB-backed strategy research library — all thresholds in parameters_json."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import StrategyDefinition

# Map API family names → engine strategy_id
FAMILY_TO_STRATEGY_ID: dict[str, str] = {
    "crypto_push_pull_baseline": "crypto_push_pull_momentum",
    "crypto_push_pull_momentum": "crypto_push_pull_momentum",
    "crypto_push_pull": "crypto_push_pull_momentum",
    "momentum": "crypto_push_pull_momentum",
    "crypto_mean_reversion": "crypto_mean_reversion",
    "mean_reversion": "crypto_mean_reversion",
    "crypto_volatility_breakout": "crypto_volatility_breakout",
    "volatility_breakout": "crypto_volatility_breakout",
    "crypto_trend_following": "crypto_trend_following",
    "trend_following": "crypto_trend_following",
    "crypto_atr_trailing_exit": "crypto_atr_trailing_exit",
    "exit": "crypto_atr_trailing_exit",
}


def resolve_strategy_id(family_or_id: str) -> str:
    return FAMILY_TO_STRATEGY_ID.get(family_or_id, family_or_id)


STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "strategy_id": "crypto_push_pull_momentum",
        "strategy_name": "Crypto Push-Pull Momentum",
        "strategy_family": "crypto_push_pull_momentum",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"],
        "timeframe": "1h",
        "description": "Multi-horizon momentum with edge-over-cost and ATR stop.",
        "parameter_schema_json": {
            "momentum_lookback_hours": "list[int]",
            "atr_period": "list[int]",
            "atr_multiplier": "list[float]",
            "edge_multiplier": "list[float]",
            "max_hold_bars": "list[int]",
        },
        "default_parameters_json": {
            "momentum_lookback_hours": [1, 3, 6, 12],
            "atr_period": [14, 21],
            "atr_multiplier": [1.5, 2.0, 2.5],
            "edge_multiplier": [1.2, 1.5, 2.0, 2.5],
            "max_hold_bars": [6, 12, 24],
        },
        "parameters_json": {
            "momentum_lookback_hours": [1, 3, 6, 12],
            "atr_period": [14, 21],
            "atr_multiplier": [1.5, 2.0, 2.5],
            "edge_multiplier": [1.2, 1.5, 2.0, 2.5],
            "max_hold_bars": [6, 12, 24],
        },
    },
    {
        "strategy_id": "crypto_mean_reversion",
        "strategy_name": "Crypto Mean Reversion",
        "strategy_family": "crypto_mean_reversion",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD", "DOGE/USD"],
        "timeframe": "1h",
        "parameter_schema_json": {"lookback": "list[int]", "z_entry": "list[float]", "z_exit": "list[float]"},
        "default_parameters_json": {"lookback": [12, 24, 48], "z_entry": [1.5, 2.0, 2.5], "z_exit": [0.25, 0.5]},
        "parameters_json": {"lookback": [12, 24, 48], "z_entry": [1.5, 2.0, 2.5], "z_exit": [0.25, 0.5]},
    },
    {
        "strategy_id": "crypto_volatility_breakout",
        "strategy_name": "Crypto Volatility Breakout",
        "strategy_family": "crypto_volatility_breakout",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "timeframe": "1h",
        "parameters_json": {
            "atr_expansion_mult": [1.2, 1.5, 2.0],
            "range_lookback": [14, 21],
            "volume_mult": [1.2, 1.5],
        },
        "default_parameters_json": {"atr_expansion_mult": [1.5], "range_lookback": [14]},
    },
    {
        "strategy_id": "crypto_trend_following",
        "strategy_name": "Crypto Trend Following",
        "strategy_family": "crypto_trend_following",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD"],
        "timeframe": "1h",
        "parameters_json": {"fast_ma": [8, 12, 20], "slow_ma": [26, 50]},
        "default_parameters_json": {"fast_ma": [12], "slow_ma": [26]},
    },
    {
        "strategy_id": "crypto_atr_trailing_exit",
        "strategy_name": "Crypto ATR Trailing Exit Tests",
        "strategy_family": "crypto_atr_trailing_exit",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "DOGE/USD"],
        "timeframe": "1h",
        "status": "research_only",
        "parameters_json": {"exit_modes": ["atr_trail", "time_stop"]},
    },
    {
        "strategy_id": "stock_opening_range_breakout",
        "strategy_name": "Stock Opening Range Breakout",
        "strategy_family": "stock_opening_range_breakout",
        "asset_class": "stock",
        "universe": ["SPY", "QQQ"],
        "timeframe": "5Min",
        "status": "research_only",
        "parameters_json": {"range_windows_minutes": [15, 30, 60]},
    },
    {
        "strategy_id": "stock_mean_reversion",
        "strategy_name": "Stock Mean Reversion",
        "strategy_family": "stock_mean_reversion",
        "asset_class": "stock",
        "universe": ["SPY"],
        "timeframe": "1h",
        "status": "research_only",
        "parameters_json": {"lookback": [20, 40]},
    },
    {
        "strategy_id": "stock_trend_following",
        "strategy_name": "Stock Trend Following",
        "strategy_family": "stock_trend_following",
        "asset_class": "stock",
        "universe": ["SPY"],
        "timeframe": "1h",
        "status": "research_only",
        "parameters_json": {"fast_ma": [10], "slow_ma": [30]},
    },
    {
        "strategy_id": "pairs_mean_reversion",
        "strategy_name": "Pairs Mean Reversion",
        "strategy_family": "pairs_mean_reversion",
        "asset_class": "crypto",
        "universe": ["BTC/USD", "ETH/USD"],
        "timeframe": "1h",
        "status": "research_only",
        "parameters_json": {"z_entry": [2.0, 2.5]},
    },
    {
        "strategy_id": "meme_attention_watch_only",
        "strategy_name": "Meme Attention Watch",
        "strategy_family": "meme_attention_watch_only",
        "asset_class": "crypto",
        "universe": ["DOGE/USD", "SHIB/USD"],
        "timeframe": "1h",
        "status": "research_only",
        "parameters_json": {"watch_only": True},
    },
]


def seed_strategy_library(session: Session, *, force_update: bool = False) -> int:
    n = 0
    for spec in STRATEGY_CATALOG:
        existing = session.get(StrategyDefinition, spec["strategy_id"])
        if existing and not force_update:
            continue
        row = existing or StrategyDefinition(
            strategy_id=spec["strategy_id"],
            strategy_name=spec["strategy_name"],
            strategy_family=spec["strategy_family"],
            created_at=datetime.utcnow(),
        )
        row.strategy_name = spec["strategy_name"]
        row.strategy_family = spec["strategy_family"]
        row.parameters_json = spec.get("parameters_json") or {}
        row.asset_class = spec.get("asset_class", "crypto")
        row.universe = spec.get("universe") or []
        row.timeframe = spec.get("timeframe", "1h")
        row.status = spec.get("status", "research_only")
        row.description = spec.get("description")
        row.updated_at = datetime.utcnow()
        session.add(row)
        n += 1
    # Legacy alias row for old runs
    if not session.get(StrategyDefinition, "crypto_push_pull"):
        session.add(
            StrategyDefinition(
                strategy_id="crypto_push_pull",
                strategy_name="Crypto Push-Pull (legacy id)",
                strategy_family="crypto_push_pull_momentum",
                parameters_json=STRATEGY_CATALOG[0]["parameters_json"],
                asset_class="crypto",
                universe=STRATEGY_CATALOG[0]["universe"],
                timeframe="1h",
                status="research_only",
            )
        )
        n += 1
    return n


def list_strategies(session: Session) -> list[dict]:
    rows = session.exec(select(StrategyDefinition)).all()
    if len(rows) < len(STRATEGY_CATALOG):
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
    sid = resolve_strategy_id(strategy_id)
    row = session.get(StrategyDefinition, sid)
    if not row:
        seed_strategy_library(session)
        row = session.get(StrategyDefinition, sid)
    return row
