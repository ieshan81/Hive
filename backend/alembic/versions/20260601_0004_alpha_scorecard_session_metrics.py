"""Add session metrics to alpha scorecards.

Revision ID: 20260601_0004
Revises: 20260531_0003
Create Date: 2026-06-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260601_0004"
down_revision = "20260531_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alpha_scorecards", sa.Column("best_session", sa.String(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("worst_session", sa.String(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("session_sample_size", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("alpha_scorecards", sa.Column("session_win_rate", sa.Float(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("session_expectancy", sa.Float(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("session_profit_factor", sa.Float(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("session_edge_after_cost_bps", sa.Float(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("london_session_metrics_json", sa.JSON(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("new_york_session_metrics_json", sa.JSON(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("london_new_york_overlap_metrics_json", sa.JSON(), nullable=True))
    op.add_column("alpha_scorecards", sa.Column("low_liquidity_session_warning", sa.String(), nullable=True))
    op.create_index("ix_alpha_scorecards_best_session", "alpha_scorecards", ["best_session"])


def downgrade() -> None:
    op.drop_index("ix_alpha_scorecards_best_session", table_name="alpha_scorecards")
    op.drop_column("alpha_scorecards", "low_liquidity_session_warning")
    op.drop_column("alpha_scorecards", "london_new_york_overlap_metrics_json")
    op.drop_column("alpha_scorecards", "new_york_session_metrics_json")
    op.drop_column("alpha_scorecards", "london_session_metrics_json")
    op.drop_column("alpha_scorecards", "session_edge_after_cost_bps")
    op.drop_column("alpha_scorecards", "session_profit_factor")
    op.drop_column("alpha_scorecards", "session_expectancy")
    op.drop_column("alpha_scorecards", "session_win_rate")
    op.drop_column("alpha_scorecards", "session_sample_size")
    op.drop_column("alpha_scorecards", "worst_session")
    op.drop_column("alpha_scorecards", "best_session")
