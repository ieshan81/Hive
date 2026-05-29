"""V2 aggressive paper profile — research rebuild defaults (dynamic, not hard-capped)."""

from __future__ import annotations

from typing import Any


def aggressive_config_patch() -> dict[str, Any]:
    return {
        "v2": {
            "aggressive_mode": True,
            "skip_entry_safety_snapshot_gates": True,
            "scheduler_interval_seconds": 45,
        },
        "ranking": {
            "ai_managed": True,
            "min_rank_score": 0.18,
        },
        "universe_ranking": {
            "min_rank_score": 0.18,
            "max_spread_bps": 120.0,
            "max_bar_age_seconds": 1800.0,
        },
        "universe": {
            "mode": "hybrid_radar",
            "speculative_paper_exploration": True,
            "allow_zero_volume_cached_bars_for_paper": True,
            "max_bar_staleness_hours": 96,
            "skip_live_quote_for_ranking": True,
            "require_1m_fresh_for_shortlist": False,
            "max_scanned_symbols_per_cycle": 0,
            "max_execution_shortlist": 0,
            "max_ranked_symbols_per_cycle": 0,
            "trade_all_eligible": True,
        },
        "portfolio": {
            "max_concurrent_positions": 0,
            "reserve_cash_pct": 10.0,
            "execute_top_n_signals": 0,
        },
        "allocator": {
            "paper_trade_notional_min_usd": 12.0,
            "paper_trade_notional_max_usd": 22.0,
        },
        "cost": {
            "edge_multiplier_paper": 1.1,
            "min_expected_move_pct": 0.08,
        },
        "push_pull": {
            "max_spread_bps": 80.0,
            "max_quote_age_seconds": 90.0,
            "max_bar_age_minutes": 180.0,
            "push_strength_min": 0.002,
            "long_structure": {"enabled": False},
        },
        "paper_ratchet": {
            "enabled": True,
            "relax_entry_stale_bar": True,
            "relax_entry_min_bars": 8,
            "arm_trailing_after_profit_bps": 25.0,
            "giveback_bps": 40.0,
            "initial_stop_pct": 0.02,
            "buy_low_pullback_bps": 80.0,
        },
        "exploration": {
            "enabled": True,
            "dynamic_formula_mode": True,
            "require_stronger_edge": False,
        },
        "autonomous_paper_learning": {
            "mode_enabled": True,
            "scheduler_enabled": True,
            "scheduler_interval_seconds": 45,
            "refresh_market_data_before_tick": True,
            "refresh_lookback_hours": 36,
            "max_paper_trades_per_day": 0,
            "max_open_paper_positions": 0,
            "use_capital_allocator": True,
            "max_unrealized_loss_usd": 4.0,
            "max_unrealized_loss_pct": 1.5,
            "run_scanners_each_tick": True,
            "run_backtest_lab_every_n_ticks": 12,
            "backtest_lab_limit": 2,
        },
        "execution": {
            "paper_orders_enabled": True,
            "live_orders_enabled": False,
            "max_orders_per_cycle": 0,
            "max_orders_per_hour": 0,
            "max_orders_per_day": 0,
        },
        "fast_training": {
            "fast_training_loop_enabled": True,
            "fast_training_execute_orders": True,
            "fast_training_cycle_seconds": 15,
            "fast_training_max_scan_symbols": 48,
            "fast_training_max_trades_per_day": 0,
            "fast_training_max_open_positions": 0,
            "exit_only_enabled": False,
        },
        "aggressive_paper_learning": {
            "mode_enabled": True,
            "use_capital_allocator": True,
            "max_experiment_notional_per_trade_usd": 0,
            "max_experiment_positions_total": 0,
            "max_experiment_trades_per_day": 0,
        },
        "live_trading_enabled": False,
        "paper_trading_only": True,
    }
