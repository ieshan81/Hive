"""Add shadow_trades table for Shadow Trading League.

Revision ID: 20260603_0005
Revises: 20260601_0004
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260603_0005"
down_revision = "20260601_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shadow_trade_id", sa.String(), nullable=False),
        sa.Column("validation_run_id", sa.String(), nullable=False, server_default="paper_validation_run_001"),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False, server_default="crypto"),
        sa.Column("strategy_id", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=False, server_default="buy"),
        sa.Column("promotion_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("data_quality", sa.String(), nullable=False, server_default="execution_grade"),
        sa.Column("data_quality_note", sa.String(), nullable=True),
        sa.Column("entry_reference_price", sa.Float(), nullable=True),
        sa.Column("exit_reference_price", sa.Float(), nullable=True),
        sa.Column("simulated_pnl_bps", sa.Float(), nullable=True),
        sa.Column("outcome_verdict", sa.String(), nullable=True),
        sa.Column("paper_blocked_reason", sa.String(), nullable=True),
        sa.Column("paper_would_be_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("counts_as_broker_evidence", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("setup_fingerprint", sa.String(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("outcome_json", sa.JSON(), nullable=True),
        sa.Column("cycle_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_shadow_trades_shadow_trade_id", "shadow_trades", ["shadow_trade_id"], unique=True)
    op.create_index("ix_shadow_trades_validation_run_id", "shadow_trades", ["validation_run_id"])
    op.create_index("ix_shadow_trades_symbol", "shadow_trades", ["symbol"])
    op.create_index("ix_shadow_trades_asset_class", "shadow_trades", ["asset_class"])
    op.create_index("ix_shadow_trades_strategy_id", "shadow_trades", ["strategy_id"])
    op.create_index("ix_shadow_trades_promotion_level", "shadow_trades", ["promotion_level"])
    op.create_index("ix_shadow_trades_status", "shadow_trades", ["status"])
    op.create_index("ix_shadow_trades_data_quality", "shadow_trades", ["data_quality"])
    op.create_index("ix_shadow_trades_outcome_verdict", "shadow_trades", ["outcome_verdict"])
    op.create_index("ix_shadow_trades_setup_fingerprint", "shadow_trades", ["setup_fingerprint"])
    op.create_index("ix_shadow_trades_cycle_run_id", "shadow_trades", ["cycle_run_id"])


def downgrade() -> None:
    for index in (
        "ix_shadow_trades_cycle_run_id",
        "ix_shadow_trades_setup_fingerprint",
        "ix_shadow_trades_outcome_verdict",
        "ix_shadow_trades_data_quality",
        "ix_shadow_trades_status",
        "ix_shadow_trades_promotion_level",
        "ix_shadow_trades_strategy_id",
        "ix_shadow_trades_asset_class",
        "ix_shadow_trades_symbol",
        "ix_shadow_trades_validation_run_id",
        "ix_shadow_trades_shadow_trade_id",
    ):
        op.drop_index(index, table_name="shadow_trades")
    op.drop_table("shadow_trades")
