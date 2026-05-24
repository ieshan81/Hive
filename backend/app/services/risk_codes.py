"""Standard risk block reason codes."""

from __future__ import annotations

CHECK_TO_CODE: dict[str, str] = {
    "market_session": "MARKET_CLOSED",
    "kill_switch": "KILL_SWITCH_ACTIVE",
    "live_trading": "LIVE_TRADING_DISABLED",
    "stop_loss": "MISSING_STOP_LOSS",
    "exit_logic": "MISSING_TAKE_PROFIT",
    "no_quote": "DATA_MISSING",
    "spread": "SPREAD_TOO_WIDE",
    "liquidity": "LIQUIDITY_BELOW_MINIMUM",
    "volatility": "VOLATILITY_TOO_HIGH",
    "alpaca_connection": "DATA_MISSING",
    "buying_power": "INSUFFICIENT_BUYING_POWER",
    "position_size": "MAX_POSITION_SIZE_EXCEEDED",
    "max_open_positions": "MAX_OPEN_POSITIONS_REACHED",
    "daily_loss_limit": "DAILY_LOSS_LIMIT_REACHED",
    "weekly_loss_limit": "WEEKLY_LOSS_LIMIT_REACHED",
    "drawdown_limit": "MAX_DRAWDOWN_REACHED",
    "strategy_inactive": "STRATEGY_INACTIVE",
    "strategy_cooling": "STRATEGY_COOLDOWN_ACTIVE",
    "symbol_cooling": "SYMBOL_COOLDOWN_ACTIVE",
    "loss_streak": "LOSS_STREAK_TOO_HIGH",
    "tradable": "SYMBOL_NOT_TRADABLE",
    "fractionable": "NOT_FRACTIONABLE",
    "confidence": "CONFIDENCE_BELOW_THRESHOLD",
    "edge": "EDGE_BELOW_COST",
    "notional": "NOTIONAL_TOO_SMALL",
    "stop_distance": "INVALID_STOP_DISTANCE",
    "sell_no_position": "SELL_BLOCKED_NO_BROKER_POSITION",
    "broker_qty": "BROKER_POSITION_QTY_TOO_LOW",
    "paper_only": "PAPER_ONLY_APPROVED_NO_ORDER",
    "edge_cost": "EDGE_BELOW_COST",
    "atr_missing": "ATR_DATA_MISSING",
    "symbol_tier": "ENGINE_BOUNDARY_BLOCKED",
    "account_cooldown": "ACCOUNT_COOLDOWN_ACTIVE",
}

CHECK_TO_RULE: dict[str, str] = {
    "market_session": "Market session closed for asset class",
    "kill_switch": "Kill switch is active",
    "live_trading": "Live trading disabled in MVP",
    "stop_loss": "Stop-loss required on all positions",
    "exit_logic": "Take-profit required when configured",
    "no_quote": "Quote or price data missing",
    "spread": "Spread exceeds max_spread_pct",
    "liquidity": "Liquidity below minimum score",
    "volatility": "Volatility exceeds strategy maximum",
    "alpaca_connection": "Broker connection unavailable",
    "buying_power": "Insufficient buying power after reserve cash",
    "position_size": "Max position size exceeded",
    "max_open_positions": "Max open positions reached",
    "daily_loss_limit": "Daily loss limit reached",
    "weekly_loss_limit": "Weekly loss limit reached",
    "drawdown_limit": "Max drawdown reached",
    "strategy_inactive": "Strategy inactive",
    "strategy_cooling": "Strategy cooling down",
    "symbol_cooling": "Symbol cooldown active",
    "loss_streak": "Loss streak too high",
    "tradable": "Symbol not tradable",
    "fractionable": "Symbol not fractionable",
    "confidence": "Signal confidence below threshold",
    "edge": "Expected edge below estimated cost",
    "notional": "Order notional below broker minimum",
    "stop_distance": "Stop distance invalid or zero",
    "sell_no_position": "No broker position — MVP blocks naked sells",
    "broker_qty": "Exit quantity exceeds broker position",
    "paper_only": "Paper trading only — approved without order",
}


def primary_block_code(failed_checks: list[str]) -> str:
    for check in failed_checks:
        if check in CHECK_TO_CODE:
            return CHECK_TO_CODE[check]
    return "RISK_BLOCKED"
