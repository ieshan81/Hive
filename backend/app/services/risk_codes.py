"""Standard risk block reason codes."""

from __future__ import annotations

CHECK_TO_CODE: dict[str, str] = {
    "market_session": "MARKET_CLOSED",
    "kill_switch": "KILL_SWITCH_ACTIVE",
    "live_trading": "LIVE_TRADING_DISABLED",
    "stop_loss": "MISSING_STOP_LOSS",
    "exit_logic": "MISSING_EXIT_LOGIC",
    "no_quote": "NO_QUOTE",
    "spread": "SPREAD_TOO_WIDE",
    "liquidity": "LIQUIDITY_BELOW_MINIMUM",
    "alpaca_connection": "DATA_UNAVAILABLE",
    "buying_power": "INSUFFICIENT_BUYING_POWER",
    "position_size": "POSITION_SIZE_EXCEEDED",
    "max_open_positions": "MAX_OPEN_POSITIONS_REACHED",
    "daily_loss_limit": "DAILY_LOSS_LIMIT",
    "weekly_loss_limit": "WEEKLY_LOSS_LIMIT",
    "drawdown_limit": "DRAWDOWN_LIMIT",
    "strategy_inactive": "STRATEGY_INACTIVE",
    "strategy_cooling": "STRATEGY_COOLDOWN",
    "loss_streak": "LOSS_STREAK_TOO_HIGH",
    "tradable": "SYMBOL_NOT_TRADABLE",
    "fractionable": "NOT_FRACTIONABLE",
    "confidence": "CONFIDENCE_BELOW_THRESHOLD",
}

CHECK_TO_RULE: dict[str, str] = {
    "market_session": "Market session closed for asset class",
    "kill_switch": "Kill switch is active",
    "live_trading": "Live trading disabled",
    "stop_loss": "Stop-loss required on all positions",
    "exit_logic": "Exit logic required",
    "no_quote": "No quote available",
    "spread": "Spread exceeds max_spread_pct",
    "liquidity": "Liquidity below minimum score",
    "alpaca_connection": "Alpaca connection unstable",
    "buying_power": "Insufficient buying power",
    "position_size": "Max position size exceeded",
    "max_open_positions": "Max open positions reached",
    "daily_loss_limit": "Daily loss limit exceeded",
    "weekly_loss_limit": "Weekly loss limit exceeded",
    "drawdown_limit": "Drawdown limit exceeded",
    "strategy_inactive": "Strategy inactive",
    "strategy_cooling": "Strategy cooling down",
    "loss_streak": "Loss streak too high",
    "tradable": "Symbol not tradable",
    "fractionable": "Symbol not fractionable",
    "confidence": "Signal confidence below threshold",
}


def primary_block_code(failed_checks: list[str]) -> str:
    for check in failed_checks:
        if check in CHECK_TO_CODE:
            return CHECK_TO_CODE[check]
    return "RISK_BLOCKED"
