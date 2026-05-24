"""Default risk/config values stored in database — not env vars."""

DEFAULT_CONFIG = {
    "max_risk_per_trade": 0.01,
    "max_position_size_pct": 0.25,
    "max_open_positions": 2,
    "daily_loss_limit_pct": 0.02,
    "weekly_loss_limit_pct": 0.05,
    "max_drawdown_limit_pct": 0.15,
    "max_spread_pct": 0.005,
    "min_liquidity_score": 40,
    "max_loss_streak": 5,
    "confidence_threshold": 0.6,
    "stop_loss_required": True,
    "take_profit_required": False,
    "kill_switch_active": False,
    "paper_trading_only": True,
    "live_trading_enabled": False,
    "opening_range_minutes": 30,
    "pairs_z_entry": 2.0,
    "pairs_z_exit": 0.5,
    "slippage_assumption_pct": 0.001,
    "spread_assumption_pct": 0.0005,
    "fee_assumption_pct": 0.0,
    "monte_carlo_target_capital": 500.0,
    "monte_carlo_simulations": 1000,
    "signal_weights": {
        "momentum": 0.4,
        "mean_reversion": 0.3,
        "volatility_filter": 0.3,
    },
    "memory_weights": {
        "confirmation_bonus": 0.1,
        "failure_penalty": 0.15,
    },
    "capital_allocation_rules": {
        "max_per_strategy_pct": 0.5,
    },
    "capital_buckets": {
        "stock_day_bucket_fraction": 0.50,
        "crypto_night_bucket_fraction": 0.30,
        "reserve_cash_bucket_fraction": 0.15,
        "emergency_cash_bucket_fraction": 0.05,
    },
    "crypto_momentum_lookback_bars": 12,
    "crypto_momentum_threshold": 0.008,
    "crypto_momentum_max_volatility": 0.08,
    "locked_safety_caps": {
        "max_risk_per_trade": 0.02,
        "daily_loss_limit_pct": 0.05,
        "live_trading_enabled": False,
    },
}

RISK_CAGE_RULES = [
    "Stop-loss required on all positions",
    "Max loss per trade ≤ configured risk cap",
    "Daily loss limit enforced",
    "Weekly loss limit enforced",
    "No leverage above configured limits",
    "Blocked assets cannot be traded",
    "AI decisions require risk cage approval",
]
