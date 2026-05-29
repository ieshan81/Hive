"""Add durable diagnostic export jobs.

Revision ID: 20260528_0001
Revises:
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260528_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_export_jobs",
        sa.Column("job_id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_sections", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=True),
        sa.Column("zip_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zip_bytes", sa.LargeBinary(), nullable=True),
    )
    op.create_index("ix_diagnostic_export_jobs_job_id", "diagnostic_export_jobs", ["job_id"])
    op.create_index("ix_diagnostic_export_jobs_status", "diagnostic_export_jobs", ["status"])
    op.create_index("ix_diagnostic_export_jobs_started_at", "diagnostic_export_jobs", ["started_at"])
    op.create_index("ix_diagnostic_export_jobs_completed_at", "diagnostic_export_jobs", ["completed_at"])


def downgrade() -> None:
    op.drop_index("ix_diagnostic_export_jobs_completed_at", table_name="diagnostic_export_jobs")
    op.drop_index("ix_diagnostic_export_jobs_started_at", table_name="diagnostic_export_jobs")
    op.drop_index("ix_diagnostic_export_jobs_status", table_name="diagnostic_export_jobs")
    op.drop_index("ix_diagnostic_export_jobs_job_id", table_name="diagnostic_export_jobs")
    op.drop_table("diagnostic_export_jobs")
