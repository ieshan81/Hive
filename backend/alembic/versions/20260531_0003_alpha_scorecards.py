"""Add autonomous alpha scorecards.

Revision ID: 20260531_0003
Revises: 20260529_0002
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260531_0003"
down_revision = "20260529_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alpha_scorecards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("normalized_symbol", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False, server_default="crypto"),
        sa.Column("strategy_family", sa.String(), nullable=False),
        sa.Column("strategy_id", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False, server_default="5Min"),
        sa.Column("current_stage", sa.String(), nullable=False, server_default="unproven"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backtest_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("walk_forward_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("expectancy", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("sharpe_if_available", sa.Float(), nullable=True),
        sa.Column("avg_trade_duration", sa.Float(), nullable=True),
        sa.Column("average_win", sa.Float(), nullable=True),
        sa.Column("average_loss", sa.Float(), nullable=True),
        sa.Column("payoff_ratio", sa.Float(), nullable=True),
        sa.Column("cost_bps", sa.Float(), nullable=True),
        sa.Column("spread_bps", sa.Float(), nullable=True),
        sa.Column("slippage_bps", sa.Float(), nullable=True),
        sa.Column("fee_bps", sa.Float(), nullable=True),
        sa.Column("edge_after_cost_bps", sa.Float(), nullable=True),
        sa.Column("recent_paper_trade_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_paper_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recent_churn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_loss_cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("data_freshness_status", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("bar_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quote_freshness", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("verdict", sa.String(), nullable=False, server_default="unproven"),
        sa.Column("blocker_reasons_json", sa.JSON(), nullable=True),
        sa.Column("promotion_reason", sa.String(), nullable=True),
        sa.Column("last_backtest_run_id", sa.String(), nullable=True),
        sa.Column("last_walk_forward_run_id", sa.String(), nullable=True),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=True),
        sa.Column("autonomous_generated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scorecard_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_alpha_scorecards_symbol", "alpha_scorecards", ["symbol"])
    op.create_index("ix_alpha_scorecards_normalized_symbol", "alpha_scorecards", ["normalized_symbol"])
    op.create_index("ix_alpha_scorecards_asset_class", "alpha_scorecards", ["asset_class"])
    op.create_index("ix_alpha_scorecards_strategy_family", "alpha_scorecards", ["strategy_family"])
    op.create_index("ix_alpha_scorecards_strategy_id", "alpha_scorecards", ["strategy_id"])
    op.create_index("ix_alpha_scorecards_current_stage", "alpha_scorecards", ["current_stage"])
    op.create_index("ix_alpha_scorecards_verdict", "alpha_scorecards", ["verdict"])
    op.create_index("ix_alpha_scorecards_last_backtest_run_id", "alpha_scorecards", ["last_backtest_run_id"])
    op.create_index("ix_alpha_scorecards_last_walk_forward_run_id", "alpha_scorecards", ["last_walk_forward_run_id"])


def downgrade() -> None:
    for index in (
        "ix_alpha_scorecards_last_walk_forward_run_id",
        "ix_alpha_scorecards_last_backtest_run_id",
        "ix_alpha_scorecards_verdict",
        "ix_alpha_scorecards_current_stage",
        "ix_alpha_scorecards_strategy_id",
        "ix_alpha_scorecards_strategy_family",
        "ix_alpha_scorecards_asset_class",
        "ix_alpha_scorecards_normalized_symbol",
        "ix_alpha_scorecards_symbol",
    ):
        op.drop_index(index, table_name="alpha_scorecards")
    op.drop_table("alpha_scorecards")
