"""Add Research OS ledgers.

Revision ID: 20260529_0002
Revises: 20260528_0001
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260529_0002"
down_revision = "20260528_0001"
branch_labels = None
depends_on = None


def _json(nullable: bool = True):
    return sa.Column(sa.JSON(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "strategy_specs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False, server_default="1.0.0"),
        sa.Column("family", sa.String(), nullable=False),
        sa.Column("asset_classes", sa.JSON(), nullable=True),
        sa.Column("timeframes", sa.JSON(), nullable=True),
        sa.Column("entry_logic_json", sa.JSON(), nullable=True),
        sa.Column("exit_logic_json", sa.JSON(), nullable=True),
        sa.Column("risk_logic_json", sa.JSON(), nullable=True),
        sa.Column("sizing_logic_json", sa.JSON(), nullable=True),
        sa.Column("required_features_json", sa.JSON(), nullable=True),
        sa.Column("constraints_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="research_os"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(), nullable=False, server_default="operator"),
        sa.Column("fingerprint", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_strategy_specs_strategy_id", "strategy_specs", ["strategy_id"])
    op.create_index("ix_strategy_specs_family", "strategy_specs", ["family"])
    op.create_index("ix_strategy_specs_status", "strategy_specs", ["status"])
    op.create_index("ix_strategy_specs_fingerprint", "strategy_specs", ["fingerprint"])

    op.create_table(
        "research_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False, unique=True),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("requested_by", sa.String(), nullable=False, server_default="operator"),
        sa.Column("agent_name", sa.String(), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_research_jobs_job_id", "research_jobs", ["job_id"])
    op.create_index("ix_research_jobs_job_type", "research_jobs", ["job_type"])
    op.create_index("ix_research_jobs_status", "research_jobs", ["status"])
    op.create_index("ix_research_jobs_agent_name", "research_jobs", ["agent_name"])

    op.create_table(
        "optimization_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("optimization_id", sa.String(), nullable=False, unique=True),
        sa.Column("strategy_id", sa.String(), nullable=False),
        sa.Column("optimizer_type", sa.String(), nullable=False, server_default="grid"),
        sa.Column("objective", sa.String(), nullable=False, server_default="expectancy"),
        sa.Column("trials_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tried_params_json", sa.JSON(), nullable=True),
        sa.Column("best_params_json", sa.JSON(), nullable=True),
        sa.Column("best_metrics_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_optimization_runs_optimization_id", "optimization_runs", ["optimization_id"])
    op.create_index("ix_optimization_runs_strategy_id", "optimization_runs", ["strategy_id"])
    op.create_index("ix_optimization_runs_status", "optimization_runs", ["status"])

    op.create_table(
        "risk_audit_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.String(), nullable=False, unique=True),
        sa.Column("strategy_id", sa.String(), nullable=False),
        sa.Column("backtest_run_id", sa.String(), nullable=True),
        sa.Column("validation_report_id", sa.String(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("drawdown_metrics_json", sa.JSON(), nullable=True),
        sa.Column("tail_risk_json", sa.JSON(), nullable=True),
        sa.Column("liquidity_metrics_json", sa.JSON(), nullable=True),
        sa.Column("concentration_json", sa.JSON(), nullable=True),
        sa.Column("correlation_json", sa.JSON(), nullable=True),
        sa.Column("pass_fail", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("veto_reason", sa.String(), nullable=True),
        sa.Column("reasons_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_risk_audit_reports_report_id", "risk_audit_reports", ["report_id"])
    op.create_index("ix_risk_audit_reports_strategy_id", "risk_audit_reports", ["strategy_id"])
    op.create_index("ix_risk_audit_reports_backtest_run_id", "risk_audit_reports", ["backtest_run_id"])
    op.create_index("ix_risk_audit_reports_pass_fail", "risk_audit_reports", ["pass_fail"])

    op.create_table(
        "ai_agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("graph_run_id", sa.String(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("tool_calls_json", sa.JSON(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )
    op.create_index("ix_ai_agent_runs_graph_run_id", "ai_agent_runs", ["graph_run_id"])
    op.create_index("ix_ai_agent_runs_agent_name", "ai_agent_runs", ["agent_name"])
    op.create_index("ix_ai_agent_runs_node_name", "ai_agent_runs", ["node_name"])
    op.create_index("ix_ai_agent_runs_status", "ai_agent_runs", ["status"])

    op.create_table(
        "code_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.String(), nullable=False, unique=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("proposed_by_agent", sa.String(), nullable=False, server_default="research_os"),
        sa.Column("affected_files_json", sa.JSON(), nullable=True),
        sa.Column("diff_text", sa.Text(), nullable=True),
        sa.Column("patch_ref", sa.String(), nullable=True),
        sa.Column("tests_required_json", sa.JSON(), nullable=True),
        sa.Column("risk_assessment_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("branch_name", sa.String(), nullable=True),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_code_proposals_proposal_id", "code_proposals", ["proposal_id"])
    op.create_index("ix_code_proposals_status", "code_proposals", ["status"])

    op.create_table(
        "live_readiness_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="locked"),
        sa.Column("account_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("paper_performance_json", sa.JSON(), nullable=True),
        sa.Column("risk_evidence_json", sa.JSON(), nullable=True),
        sa.Column("reconciliation_status_json", sa.JSON(), nullable=True),
        sa.Column("kill_switch_status_json", sa.JSON(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_live_readiness_reviews_stage", "live_readiness_reviews", ["stage"])
    op.create_index("ix_live_readiness_reviews_status", "live_readiness_reviews", ["status"])

    op.create_table(
        "tradingview_integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="display_only"),
        sa.Column("webhook_secret_hash", sa.String(), nullable=True),
        sa.Column("allowed_actions", sa.JSON(), nullable=True),
        sa.Column("display_config_json", sa.JSON(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tradingview_integrations_name", "tradingview_integrations", ["name"])
    op.create_index("ix_tradingview_integrations_status", "tradingview_integrations", ["status"])

    op.create_table(
        "tradingview_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False, server_default="signal"),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("mapped_signal_json", sa.JSON(), nullable=True),
        sa.Column("accepted_for_display", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("execution_blocked_reason", sa.String(), nullable=False, server_default="display_only_execution_blocked"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tradingview_events_integration_id", "tradingview_events", ["integration_id"])
    op.create_index("ix_tradingview_events_event_type", "tradingview_events", ["event_type"])

    op.create_table(
        "live_flag_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requested_by", sa.String(), nullable=False, server_default="operator"),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="operator"),
        sa.Column("current_flags_json", sa.JSON(), nullable=True),
        sa.Column("requested_flags_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="requested"),
        sa.Column("confirmation_phrase_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_stage", sa.String(), nullable=False, server_default="dry_run_required"),
        sa.Column("dry_run_result_json", sa.JSON(), nullable=True),
        sa.Column("audit_log_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_live_flag_change_requests_actor_type", "live_flag_change_requests", ["actor_type"])
    op.create_index("ix_live_flag_change_requests_status", "live_flag_change_requests", ["status"])


def downgrade() -> None:
    for index, table in (
        ("ix_live_flag_change_requests_status", "live_flag_change_requests"),
        ("ix_live_flag_change_requests_actor_type", "live_flag_change_requests"),
        ("ix_tradingview_events_event_type", "tradingview_events"),
        ("ix_tradingview_events_integration_id", "tradingview_events"),
        ("ix_tradingview_integrations_status", "tradingview_integrations"),
        ("ix_tradingview_integrations_name", "tradingview_integrations"),
        ("ix_live_readiness_reviews_status", "live_readiness_reviews"),
        ("ix_live_readiness_reviews_stage", "live_readiness_reviews"),
        ("ix_code_proposals_status", "code_proposals"),
        ("ix_code_proposals_proposal_id", "code_proposals"),
        ("ix_ai_agent_runs_status", "ai_agent_runs"),
        ("ix_ai_agent_runs_node_name", "ai_agent_runs"),
        ("ix_ai_agent_runs_agent_name", "ai_agent_runs"),
        ("ix_ai_agent_runs_graph_run_id", "ai_agent_runs"),
        ("ix_risk_audit_reports_pass_fail", "risk_audit_reports"),
        ("ix_risk_audit_reports_backtest_run_id", "risk_audit_reports"),
        ("ix_risk_audit_reports_strategy_id", "risk_audit_reports"),
        ("ix_risk_audit_reports_report_id", "risk_audit_reports"),
        ("ix_optimization_runs_status", "optimization_runs"),
        ("ix_optimization_runs_strategy_id", "optimization_runs"),
        ("ix_optimization_runs_optimization_id", "optimization_runs"),
        ("ix_research_jobs_agent_name", "research_jobs"),
        ("ix_research_jobs_status", "research_jobs"),
        ("ix_research_jobs_job_type", "research_jobs"),
        ("ix_research_jobs_job_id", "research_jobs"),
        ("ix_strategy_specs_fingerprint", "strategy_specs"),
        ("ix_strategy_specs_status", "strategy_specs"),
        ("ix_strategy_specs_family", "strategy_specs"),
        ("ix_strategy_specs_strategy_id", "strategy_specs"),
    ):
        op.drop_index(index, table_name=table)
    for table in (
        "live_flag_change_requests",
        "tradingview_events",
        "tradingview_integrations",
        "live_readiness_reviews",
        "code_proposals",
        "ai_agent_runs",
        "risk_audit_reports",
        "optimization_runs",
        "research_jobs",
        "strategy_specs",
    ):
        op.drop_table(table)

