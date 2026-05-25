"""Seed strategy_promotion_rules for micro_account_safe profile."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from app.database import StrategyPromotionRule

DEFAULT_RULES: list[dict] = [
    {
        "rule_key": "research_to_watchlist",
        "stage_from": "research_only",
        "stage_to": "watchlist",
        "threshold_value_json": {
            "min_backtest_trades": 100,
            "min_profit_factor": 1.3,
            "min_expectancy": 0.0,
            "max_drawdown_pct": 20.0,
            "max_cost_to_edge_ratio": 0.4,
            "require_data_freshness": True,
            "require_cost_model": True,
        },
    },
    {
        "rule_key": "watchlist_to_paper_candidate",
        "stage_from": "watchlist",
        "stage_to": "paper_candidate",
        "threshold_value_json": {
            "min_backtest_trades": 100,
            "min_profit_factor": 1.5,
            "min_expectancy": 0.0,
            "max_drawdown_pct": 15.0,
            "max_cost_to_edge_ratio": 0.3,
            "block_parameter_sweep_no_variation": True,
            "block_stale_data_hard": True,
            "block_validated_rejection_memory": True,
        },
    },
    {
        "rule_key": "paper_candidate_to_paper_active",
        "stage_from": "paper_candidate",
        "stage_to": "paper_active",
        "threshold_value_json": {
            "require_stop_loss": True,
            "require_time_stop": True,
            "require_duplicate_order_prevention": True,
            "require_daily_loss_rule": True,
            "require_broker_readiness": True,
            "require_reconciliation": True,
        },
    },
    {
        "rule_key": "paper_active_to_live_candidate",
        "stage_from": "paper_active",
        "stage_to": "live_candidate",
        "threshold_value_json": {
            "min_paper_days": 90,
            "min_paper_trades": 100,
            "min_psr": 0.5,
            "max_reconciliation_drift": 0,
            "max_broker_errors_24h": 0,
            "require_kill_switch_drill": True,
            "live_trading_must_remain_locked": True,
        },
    },
    {
        "rule_key": "eligibility_window",
        "stage_from": "paper_active",
        "stage_to": "live_candidate",
        "threshold_value_json": {
            "earliest_promote_days": 7,
            "latest_decision_days": 14,
            "min_valid_observations": 5,
        },
    },
    {
        "rule_key": "scorecard_composite",
        "stage_from": "*",
        "stage_to": "*",
        "threshold_value_json": {
            "weight_expectancy": 0.25,
            "weight_profit_factor": 0.2,
            "weight_drawdown": 0.2,
            "weight_sample": 0.15,
            "weight_memory": 0.1,
            "weight_walk_forward": 0.1,
        },
    },
]


def seed_promotion_rules(session: Session, profile: str = "micro_account_safe") -> int:
    existing = session.exec(
        select(StrategyPromotionRule).where(StrategyPromotionRule.profile == profile)
    ).first()
    if existing:
        return 0
    for r in DEFAULT_RULES:
        session.add(
            StrategyPromotionRule(
                profile=profile,
                rule_key=r["rule_key"],
                stage_from=r["stage_from"],
                stage_to=r["stage_to"],
                threshold_value_json=r["threshold_value_json"],
                weight=1.0,
                enabled=True,
                updated_at=datetime.utcnow(),
            )
        )
    return len(DEFAULT_RULES)
