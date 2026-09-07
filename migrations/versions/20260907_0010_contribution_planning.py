"""contribution planning

Revision ID: 20260907_0010
Revises: 20260907_0009
Create Date: 2026-09-07 18:38:36.170527
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0010"
down_revision: str | Sequence[str] | None = "20260907_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_runs",
        sa.Column("broker_account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False),
        sa.Column("valuation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_input", sa.LargeBinary(), nullable=False),
        sa.Column("canonical_result", sa.LargeBinary(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('actual_vs_target','drift')", name=op.f("ck_analytics_runs_kind_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_analytics_runs_broker_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_analytics_runs_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_runs")),
        sa.UniqueConstraint(
            "owner_id",
            "broker_account_id",
            "kind",
            "input_digest",
            name="uq_analytics_runs_semantic_input",
        ),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_analytics_runs_owner_id")),
    )
    op.create_table(
        "contribution_plans",
        sa.Column("broker_account_id", sa.Uuid(), nullable=False),
        sa.Column("virtual_portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_contribution_plans_revision_positive")),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_contribution_plans_broker_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            name=op.f("fk_contribution_plans_owner_id_virtual_portfolios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plans_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plans")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plans_owner_id")),
    )
    op.create_index(
        "ix_contribution_plans_owner_account_created",
        "contribution_plans",
        ["owner_id", "broker_account_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "analytics_run_sources",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("target_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_record_id", sa.Uuid(), nullable=True),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(snapshot_id,target_version_id,source_record_id) = 1",
            name=op.f("ck_analytics_run_sources_one_source"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["analytics_runs.owner_id", "analytics_runs.id"],
            name=op.f("fk_analytics_run_sources_owner_id_analytics_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_analytics_run_sources_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_analytics_run_sources_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["portfolio_snapshots.id"],
            name=op.f("fk_analytics_run_sources_snapshot_id_portfolio_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_analytics_run_sources_source_record_id_source_records"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_run_sources")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_analytics_run_sources_owner_id")),
    )
    op.create_table(
        "contribution_plan_requests",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("calculation_run_id", sa.Uuid(), nullable=False),
        sa.Column("contribution", sa.Numeric(38, 18), nullable=False),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("coverage_policy", sa.String(length=30), nullable=False),
        sa.Column("monetary_quantum", sa.Numeric(38, 18), nullable=True),
        sa.Column("currency_policy_version", sa.String(length=100), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("target_content_digest", sa.String(length=64), nullable=False),
        sa.Column("valuation_content_digest", sa.String(length=64), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("command_digest", sa.String(length=64), nullable=False),
        sa.Column("valuation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("portfolio_total", sa.Numeric(38, 18), nullable=True),
        sa.Column("quality_state", sa.String(length=30), nullable=False),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False),
        sa.Column("reconciled", sa.Boolean(), nullable=False),
        sa.Column("missing_inputs", sa.ARRAY(sa.String(length=120)), nullable=False),
        sa.Column("cash_reserve", sa.Numeric(38, 18), nullable=True),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("canonical_input", sa.LargeBinary(), nullable=False),
        sa.Column("normalized_digest", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "coverage_policy IN ('require_complete','allow_degraded')",
            name=op.f("ck_contribution_plan_requests_coverage_policy_allowed"),
        ),
        sa.CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$' AND command_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_contribution_plan_requests_digest_format"),
        ),
        sa.CheckConstraint(
            "mode IN ('global','hierarchical','restricted','cash_only')",
            name=op.f("ck_contribution_plan_requests_mode_allowed"),
        ),
        sa.CheckConstraint(
            "contribution >= 0 AND (monetary_quantum IS NULL OR monetary_quantum > 0)",
            name=op.f("ck_contribution_plan_requests_amount_bounds"),
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name=op.f("ck_contribution_plan_requests_revision_positive")
        ),
        sa.CheckConstraint(
            "source_cutoff_at <= valuation_at",
            name=op.f("ck_contribution_plan_requests_cutoff_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["calculation_run_id"],
            ["calculation_runs.id"],
            name=op.f("fk_contribution_plan_requests_calculation_run_id_calculation_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "plan_id"],
            ["contribution_plans.owner_id", "contribution_plans.id"],
            name=op.f("fk_contribution_plan_requests_owner_id_contribution_plans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_contribution_plan_requests_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_requests_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["portfolio_snapshots.id"],
            name=op.f("fk_contribution_plan_requests_snapshot_id_portfolio_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_requests")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_requests_owner_id")),
        sa.UniqueConstraint(
            "plan_id", "revision_number", name=op.f("uq_contribution_plan_requests_plan_id")
        ),
    )
    op.create_table(
        "contribution_plan_catalog",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_contribution_plan_catalog_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_contribution_plan_catalog_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_contribution_plan_catalog_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_catalog_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_catalog")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_catalog_owner_id")),
        sa.UniqueConstraint(
            "request_id", "listing_id", name=op.f("uq_contribution_plan_catalog_request_id")
        ),
    )
    op.create_table(
        "contribution_plan_inputs",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("quality_state", sa.String(length=30), nullable=False),
        sa.Column("fx_source_id", sa.Uuid(), nullable=True),
        sa.Column("fx_digest", sa.String(length=64), nullable=True),
        sa.Column("fx_base_currency", sa.String(length=3), nullable=True),
        sa.Column("fx_quote_currency", sa.String(length=3), nullable=True),
        sa.Column("fx_rate", sa.Numeric(38, 18), nullable=True),
        sa.Column("fx_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fx_first_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind='position' AND listing_id IS NOT NULL AND instrument_id IS NOT NULL) OR (kind='cash' AND listing_id IS NULL AND instrument_id IS NULL)",
            name=op.f("ck_contribution_plan_inputs_kind_identity"),
        ),
        sa.CheckConstraint(
            "kind IN ('position','cash')", name=op.f("ck_contribution_plan_inputs_kind_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["fx_source_id"],
            ["source_records.id"],
            name=op.f("fk_contribution_plan_inputs_fx_source_id_source_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_contribution_plan_inputs_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_contribution_plan_inputs_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_contribution_plan_inputs_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_inputs_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_inputs")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_inputs_owner_id")),
        sa.UniqueConstraint(
            "request_id", "ordinal", name=op.f("uq_contribution_plan_inputs_request_id")
        ),
    )
    op.create_table(
        "contribution_plan_jobs",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("consumer_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumer_id", sa.String(length=120), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','succeeded','failed','expired','cancelled')",
            name=op.f("ck_contribution_plan_jobs_state_allowed"),
        ),
        sa.CheckConstraint(
            "consumer_attempts >= 0 AND consumer_attempts <= 4",
            name=op.f("ck_contribution_plan_jobs_attempts_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_contribution_plan_jobs_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_jobs_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_jobs")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_jobs_owner_id")),
        sa.UniqueConstraint("request_id", name=op.f("uq_contribution_plan_jobs_request_id")),
    )
    op.create_index(
        "ix_plan_jobs_state_lease",
        "contribution_plan_jobs",
        ["state", "lease_expires_at", "id"],
        unique=False,
    )
    op.create_table(
        "contribution_plan_request_constraints",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("node_key", sa.String(length=80), nullable=True),
        sa.Column("amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("weight", sa.Numeric(38, 18), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("line_count", sa.Integer(), nullable=True),
        sa.Column("coefficient", sa.Numeric(38, 18), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f(
                "fk_contribution_plan_request_constraints_owner_id_contribution_plan_requests"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_request_constraints_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_request_constraints")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_contribution_plan_request_constraints_owner_id")
        ),
        sa.UniqueConstraint(
            "request_id", "key", name=op.f("uq_contribution_plan_request_constraints_request_id")
        ),
    )
    op.create_table(
        "contribution_plan_revisions",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("residual_cash", sa.Numeric(38, 18), nullable=True),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False),
        sa.Column("objective_before", sa.ARRAY(sa.Numeric(38, 18)), nullable=False),
        sa.Column("objective_after", sa.ARRAY(sa.Numeric(38, 18)), nullable=False),
        sa.Column("lower_bound", sa.ARRAY(sa.Numeric(38, 18)), nullable=False),
        sa.Column("objective_gap", sa.ARRAY(sa.Numeric(38, 18)), nullable=False),
        sa.Column("search_nodes", sa.Integer(), nullable=False),
        sa.Column("canonical_result", sa.LargeBinary(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_contribution_plan_revisions_digest_format"),
        ),
        sa.CheckConstraint(
            "outcome IN ('optimal','feasible_nonoptimal','infeasible','unavailable','failed')",
            name=op.f("ck_contribution_plan_revisions_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "residual_cash IS NULL OR residual_cash >= 0",
            name=op.f("ck_contribution_plan_revisions_residual_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_contribution_plan_revisions_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_revisions_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_revisions")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_revisions_owner_id")),
        sa.UniqueConstraint("request_id", name=op.f("uq_contribution_plan_revisions_request_id")),
    )
    op.create_table(
        "planning_audit_events",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('requested','completed','failed')",
            name=op.f("ck_planning_audit_events_kind_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_planning_audit_events_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_planning_audit_events_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planning_audit_events")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_planning_audit_events_owner_id")),
        sa.UniqueConstraint("request_id", "kind", name=op.f("uq_planning_audit_events_request_id")),
    )
    op.create_table(
        "planning_command_identities",
        sa.Column("broker_account_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("command_kind", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "command_kind IN ('create_plan','revise_plan')",
            name=op.f("ck_planning_command_identities_command_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_planning_command_identities_broker_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_planning_command_identities_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_planning_command_identities_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planning_command_identities")),
        sa.UniqueConstraint(
            "owner_id",
            "broker_account_id",
            "command_kind",
            "idempotency_key",
            name="uq_planning_command_identity",
        ),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_planning_command_identities_owner_id")),
    )
    op.create_table(
        "analytics_drift_rows",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("holding_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("parent_key", sa.String(length=80), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("target_weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("actual_value", sa.Numeric(38, 18), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("actual_direct_weight", sa.Numeric(38, 18), nullable=True),
        sa.Column("effective_weight", sa.Numeric(38, 18), nullable=True),
        sa.Column("effective_weight_reason", sa.String(length=80), nullable=False),
        sa.Column("signed_drift", sa.Numeric(38, 18), nullable=True),
        sa.Column("absolute_drift", sa.Numeric(38, 18), nullable=True),
        sa.Column("relative_drift", sa.Numeric(38, 18), nullable=True),
        sa.Column("relative_drift_reason", sa.String(length=80), nullable=True),
        sa.Column("classification", sa.String(length=30), nullable=True),
        sa.Column("monetary_gap", sa.Numeric(38, 18), nullable=True),
        sa.Column("quality_state", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["target_holdings.id"],
            name=op.f("fk_analytics_drift_rows_holding_id_target_holdings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_analytics_drift_rows_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_analytics_drift_rows_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["target_nodes.id"],
            name=op.f("fk_analytics_drift_rows_node_id_target_nodes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["analytics_runs.owner_id", "analytics_runs.id"],
            name=op.f("fk_analytics_drift_rows_owner_id_analytics_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_analytics_drift_rows_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_drift_rows")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_analytics_drift_rows_owner_id")),
        sa.UniqueConstraint("run_id", "key", name="uq_analytics_rows_run_key"),
        sa.UniqueConstraint("run_id", "ordinal", name=op.f("uq_analytics_drift_rows_run_id")),
    )
    op.create_table(
        "contribution_plan_attempts",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("event", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event IN ('claimed','published','heartbeat','succeeded','failed','expired')",
            name=op.f("ck_contribution_plan_attempts_event_allowed"),
        ),
        sa.CheckConstraint(
            "kind IN ('publication','consumer')",
            name=op.f("ck_contribution_plan_attempts_kind_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["contribution_plan_jobs.owner_id", "contribution_plan_jobs.id"],
            name=op.f("fk_contribution_plan_attempts_owner_id_contribution_plan_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_attempts_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_attempts")),
        sa.UniqueConstraint(
            "job_id", "sequence", name=op.f("uq_contribution_plan_attempts_job_id")
        ),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_attempts_owner_id")),
    )
    op.create_table(
        "contribution_plan_dispatch_outbox",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("publication_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatcher_id", sa.String(length=120), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending','claimed','published','completed','dead_letter')",
            name=op.f("ck_contribution_plan_dispatch_outbox_state_allowed"),
        ),
        sa.CheckConstraint(
            "task_name = 'plans.calculate.v1'",
            name=op.f("ck_contribution_plan_dispatch_outbox_fixed_task"),
        ),
        sa.CheckConstraint(
            "publication_attempts >= 0 AND publication_attempts <= 8",
            name=op.f("ck_contribution_plan_dispatch_outbox_attempts_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["contribution_plan_jobs.owner_id", "contribution_plan_jobs.id"],
            name=op.f("fk_contribution_plan_dispatch_outbox_owner_id_contribution_plan_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_dispatch_outbox_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_dispatch_outbox")),
        sa.UniqueConstraint("job_id", name=op.f("uq_contribution_plan_dispatch_outbox_job_id")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_contribution_plan_dispatch_outbox_owner_id")
        ),
    )
    op.create_index(
        "ix_plan_outbox_available",
        "contribution_plan_dispatch_outbox",
        ["state", "available_at", "id"],
        unique=False,
    )
    op.create_table(
        "contribution_plan_explanations",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("constraint_keys", sa.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("node_keys", sa.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "result_id"],
            ["contribution_plan_revisions.owner_id", "contribution_plan_revisions.id"],
            name=op.f("fk_contribution_plan_explanations_owner_id_contribution_plan_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_explanations_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_explanations")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_contribution_plan_explanations_owner_id")
        ),
        sa.UniqueConstraint(
            "result_id", "ordinal", name=op.f("uq_contribution_plan_explanations_result_id")
        ),
    )
    op.create_table(
        "contribution_plan_holding_constraints",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=False),
        sa.Column("minimum_amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("value_increment", sa.Numeric(38, 18), nullable=False),
        sa.Column("maximum_post_weight", sa.Numeric(38, 18), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "minimum_amount >= 0 AND value_increment > 0 AND (maximum_post_weight IS NULL OR maximum_post_weight BETWEEN 0 AND 1)",
            name=op.f("ck_contribution_plan_holding_constraints_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["target_holdings.id"],
            name=op.f("fk_contribution_plan_holding_constraints_holding_id_target_holdings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f(
                "fk_contribution_plan_holding_constraints_owner_id_contribution_plan_requests"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_holding_constraints_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_holding_constraints")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_contribution_plan_holding_constraints_owner_id")
        ),
        sa.UniqueConstraint(
            "request_id",
            "holding_id",
            name=op.f("uq_contribution_plan_holding_constraints_request_id"),
        ),
    )
    op.create_table(
        "contribution_plan_lines",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("node_key", sa.String(length=80), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=True),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("holding_id", sa.Uuid(), nullable=True),
        sa.Column("current_value", sa.Numeric(38, 18), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("current_weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("target_weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("post_value", sa.Numeric(38, 18), nullable=False),
        sa.Column("post_weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("recommended_amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("minimum_funded_amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("value_increment", sa.Numeric(38, 18), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("binding_constraint_keys", sa.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recommended_amount >= 0", name=op.f("ck_contribution_plan_lines_no_sales")
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["target_holdings.id"],
            name=op.f("fk_contribution_plan_lines_holding_id_target_holdings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_contribution_plan_lines_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_contribution_plan_lines_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "result_id"],
            ["contribution_plan_revisions.owner_id", "contribution_plan_revisions.id"],
            name=op.f("fk_contribution_plan_lines_owner_id_contribution_plan_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_lines_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["target_nodes.id"],
            name=op.f("fk_contribution_plan_lines_target_node_id_target_nodes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_lines")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_lines_owner_id")),
        sa.UniqueConstraint("result_id", "node_key", name="uq_plan_lines_result_key"),
        sa.UniqueConstraint(
            "result_id", "ordinal", name=op.f("uq_contribution_plan_lines_result_id")
        ),
    )
    op.create_table(
        "contribution_plan_selections",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=True),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('eligible','excluded','restricted','preference')",
            name=op.f("ck_contribution_plan_selections_kind_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["target_holdings.id"],
            name=op.f("fk_contribution_plan_selections_holding_id_target_holdings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_contribution_plan_selections_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_contribution_plan_selections_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_selections_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["target_nodes.id"],
            name=op.f("fk_contribution_plan_selections_target_node_id_target_nodes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_selections")),
        sa.UniqueConstraint(
            "owner_id", "id", name=op.f("uq_contribution_plan_selections_owner_id")
        ),
        sa.UniqueConstraint(
            "request_id",
            "kind",
            "target_node_id",
            name=op.f("uq_contribution_plan_selections_request_id"),
        ),
    )
    op.create_table(
        "contribution_plan_sources",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("calculation_run_id", sa.Uuid(), nullable=True),
        sa.Column("target_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_record_id", sa.Uuid(), nullable=True),
        sa.Column("target_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_contribution_plan_sources_digest_format")
        ),
        sa.CheckConstraint(
            "kind IN ('snapshot','calculation','target','source_record','target_mapping')",
            name=op.f("ck_contribution_plan_sources_kind_allowed"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(snapshot_id,calculation_run_id,target_version_id,source_record_id,target_mapping_id)=1",
            name=op.f("ck_contribution_plan_sources_one_source"),
        ),
        sa.ForeignKeyConstraint(
            ["calculation_run_id"],
            ["calculation_runs.id"],
            name=op.f("fk_contribution_plan_sources_calculation_run_id_calculation_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
            name=op.f("fk_contribution_plan_sources_owner_id_contribution_plan_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_mapping_id"],
            ["target_mapping_decisions.owner_id", "target_mapping_decisions.id"],
            name=op.f("fk_contribution_plan_sources_owner_id_target_mapping_decisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            name=op.f("fk_contribution_plan_sources_owner_id_target_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_contribution_plan_sources_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["portfolio_snapshots.id"],
            name=op.f("fk_contribution_plan_sources_snapshot_id_portfolio_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_contribution_plan_sources_source_record_id_source_records"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contribution_plan_sources")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_contribution_plan_sources_owner_id")),
        sa.UniqueConstraint(
            "request_id", "kind", "source_id", name=op.f("uq_contribution_plan_sources_request_id")
        ),
    )

    op.execute(
        "\nCREATE TABLE planning_collection_bindings (\n\tcollection_snapshot_id UUID NOT NULL, \n\tcache_key VARCHAR(64) NOT NULL, \n\trequest_id UUID, \n\tresult_id UUID, \n\trun_id UUID, \n\towner_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_planning_collection_bindings PRIMARY KEY (id), \n\tCONSTRAINT uq_planning_collection_bindings_owner_id UNIQUE (owner_id, id), \n\tCONSTRAINT uq_planning_collection_bindings_collection_snapshot_id UNIQUE (collection_snapshot_id), \n\tCONSTRAINT fk_planning_collection_bindings_owner_id_collection_que_c3c6 FOREIGN KEY(owner_id, collection_snapshot_id) REFERENCES collection_query_snapshots (owner_id, id) ON DELETE CASCADE, \n\tCONSTRAINT fk_planning_collection_bindings_owner_id_contribution_p_56bb FOREIGN KEY(owner_id, request_id) REFERENCES contribution_plan_requests (owner_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_planning_collection_bindings_owner_id_contribution_p_156a FOREIGN KEY(owner_id, result_id) REFERENCES contribution_plan_revisions (owner_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_planning_collection_bindings_owner_id_analytics_runs FOREIGN KEY(owner_id, run_id) REFERENCES analytics_runs (owner_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_planning_collection_bindings_one_source CHECK (num_nonnulls(request_id,result_id,run_id)=1), \n\tCONSTRAINT ck_planning_collection_bindings_digest_format CHECK (cache_key ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT fk_planning_collection_bindings_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_planning_collection_cache ON planning_collection_bindings (owner_id, cache_key)"
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_requests_f_cash_reserve"),
        "contribution_plan_requests",
        "cash_reserve IS NULL OR cash_reserve NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_requests_f_contribution"),
        "contribution_plan_requests",
        "contribution IS NULL OR contribution NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_requests_f_monetary_quantum"),
        "contribution_plan_requests",
        "monetary_quantum IS NULL OR monetary_quantum NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_requests_f_portfolio_total"),
        "contribution_plan_requests",
        "portfolio_total IS NULL OR portfolio_total NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_requests_format_reporting_currency"),
        "contribution_plan_requests",
        "reporting_currency IS NULL OR reporting_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_inputs_f_amount"),
        "contribution_plan_inputs",
        "amount IS NULL OR amount NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_inputs_f_fx_rate"),
        "contribution_plan_inputs",
        "fx_rate IS NULL OR fx_rate NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_inputs_format_currency"),
        "contribution_plan_inputs",
        "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_inputs_format_fx_base_currency"),
        "contribution_plan_inputs",
        "fx_base_currency IS NULL OR fx_base_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_inputs_format_fx_quote_currency"),
        "contribution_plan_inputs",
        "fx_quote_currency IS NULL OR fx_quote_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_amount_nonnegative"),
        "contribution_plan_request_constraints",
        "amount IS NULL OR (amount >= 0 AND amount <> 'NaN'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_coefficient_bounds"),
        "contribution_plan_request_constraints",
        "coefficient IS NULL OR (coefficient >= 0.000001 AND coefficient <= 1000)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_count_bounds"),
        "contribution_plan_request_constraints",
        "line_count IS NULL OR (line_count >= 0 AND line_count <= 256)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_f_amount"),
        "contribution_plan_request_constraints",
        "amount IS NULL OR amount NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_f_coefficient"),
        "contribution_plan_request_constraints",
        "coefficient IS NULL OR coefficient NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_f_weight"),
        "contribution_plan_request_constraints",
        "weight IS NULL OR weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_format_currency"),
        "contribution_plan_request_constraints",
        "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_increment_positive"),
        "contribution_plan_request_constraints",
        "kind <> 'amount_increment' OR amount > 0",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_kind_allowed"),
        "contribution_plan_request_constraints",
        "kind IN ('minimum_funded_amount','amount_increment','minimum_post_weight','maximum_post_weight','minimum_group_funding','maximum_group_funding','cash_reserve','eligible','maximum_funded_lines','priority')",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_kind_fields"),
        "contribution_plan_request_constraints",
        "(kind IN ('minimum_funded_amount','amount_increment','minimum_group_funding','maximum_group_funding') AND amount IS NOT NULL AND currency IS NOT NULL AND num_nonnulls(weight,enabled,line_count,coefficient)=0) OR (kind IN ('minimum_post_weight','maximum_post_weight') AND weight IS NOT NULL AND num_nonnulls(amount,currency,enabled,line_count,coefficient)=0) OR (kind='cash_reserve' AND num_nonnulls(enabled,line_count,coefficient)=0 AND ((amount IS NOT NULL AND currency IS NOT NULL) OR (amount IS NULL AND currency IS NULL AND weight IS NOT NULL))) OR (kind='eligible' AND enabled IS NOT NULL AND num_nonnulls(amount,currency,weight,line_count,coefficient)=0) OR (kind='maximum_funded_lines' AND line_count IS NOT NULL AND num_nonnulls(amount,currency,weight,enabled,coefficient)=0) OR (kind='priority' AND coefficient IS NOT NULL AND num_nonnulls(amount,currency,weight,enabled,line_count)=0)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_request_constraints_weight_bounds"),
        "contribution_plan_request_constraints",
        "weight IS NULL OR (weight >= 0 AND weight <= 1)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_holding_constraints_f_maximum_post_weight"),
        "contribution_plan_holding_constraints",
        "maximum_post_weight IS NULL OR maximum_post_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_holding_constraints_f_minimum_amount"),
        "contribution_plan_holding_constraints",
        "minimum_amount IS NULL OR minimum_amount NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_holding_constraints_f_value_increment"),
        "contribution_plan_holding_constraints",
        "value_increment IS NULL OR value_increment NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_revisions_f_residual_cash"),
        "contribution_plan_revisions",
        "residual_cash IS NULL OR residual_cash NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_revisions_format_reporting_currency"),
        "contribution_plan_revisions",
        "reporting_currency IS NULL OR reporting_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_current_value"),
        "contribution_plan_lines",
        "current_value IS NULL OR current_value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_current_weight"),
        "contribution_plan_lines",
        "current_weight IS NULL OR current_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_minimum_funded_amount"),
        "contribution_plan_lines",
        "minimum_funded_amount IS NULL OR minimum_funded_amount NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_post_value"),
        "contribution_plan_lines",
        "post_value IS NULL OR post_value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_post_weight"),
        "contribution_plan_lines",
        "post_weight IS NULL OR post_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_recommended_amount"),
        "contribution_plan_lines",
        "recommended_amount IS NULL OR recommended_amount NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_target_weight"),
        "contribution_plan_lines",
        "target_weight IS NULL OR target_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_f_value_increment"),
        "contribution_plan_lines",
        "value_increment IS NULL OR value_increment NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_lines_format_currency"),
        "contribution_plan_lines",
        "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_format_reporting_currency"),
        "analytics_runs",
        "reporting_currency IS NULL OR reporting_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_absolute_drift"),
        "analytics_drift_rows",
        "absolute_drift IS NULL OR absolute_drift NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_actual_direct_weight"),
        "analytics_drift_rows",
        "actual_direct_weight IS NULL OR actual_direct_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_actual_value"),
        "analytics_drift_rows",
        "actual_value IS NULL OR actual_value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_effective_weight"),
        "analytics_drift_rows",
        "effective_weight IS NULL OR effective_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_monetary_gap"),
        "analytics_drift_rows",
        "monetary_gap IS NULL OR monetary_gap NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_relative_drift"),
        "analytics_drift_rows",
        "relative_drift IS NULL OR relative_drift NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_signed_drift"),
        "analytics_drift_rows",
        "signed_drift IS NULL OR signed_drift NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_f_target_weight"),
        "analytics_drift_rows",
        "target_weight IS NULL OR target_weight NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
    )
    op.create_check_constraint(
        op.f("ck_analytics_drift_rows_format_currency"),
        "analytics_drift_rows",
        "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_requests_bound_canonical_input"),
        "contribution_plan_requests",
        "octet_length(canonical_input) <= 8388608",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_sources_source_identity"),
        "contribution_plan_sources",
        "((kind='snapshot' AND source_id=snapshot_id) OR (kind='calculation' AND source_id=calculation_run_id) OR (kind='target' AND source_id=target_version_id) OR (kind='source_record' AND source_id=source_record_id) OR (kind='target_mapping' AND source_id=target_mapping_id)) IS TRUE",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_revisions_bound_canonical_result"),
        "contribution_plan_revisions",
        "octet_length(canonical_result) <= 8388608",
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_bound_canonical_input"),
        "analytics_runs",
        "octet_length(canonical_input) <= 8388608",
    )
    op.create_check_constraint(
        op.f("ck_analytics_runs_bound_canonical_result"),
        "analytics_runs",
        "octet_length(canonical_result) <= 8388608",
    )
    op.create_check_constraint(
        op.f("ck_contribution_plan_inputs_complete_fx"),
        "contribution_plan_inputs",
        "num_nonnulls(fx_source_id,fx_digest,fx_base_currency,fx_quote_currency,fx_rate,fx_effective_at,fx_first_observed_at)=0 OR (num_nonnulls(fx_source_id,fx_digest,fx_base_currency,fx_quote_currency,fx_rate,fx_effective_at,fx_first_observed_at)=7 AND fx_rate>0 AND fx_base_currency<>fx_quote_currency)",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes'))",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc')",
    )
    op.execute(
        "CREATE FUNCTION planning_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE body jsonb := to_jsonb(NEW); account_id uuid; request_row contribution_plan_requests;\n        plan_row contribution_plans; target_id uuid; run_row analytics_runs; ref uuid;\nBEGIN\n  IF TG_TABLE_NAME='contribution_plans' THEN\n    IF NOT EXISTS (SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id\n      JOIN virtual_portfolios p ON p.id=NEW.virtual_portfolio_id\n      WHERE a.id=NEW.broker_account_id AND c.owner_id=NEW.owner_id\n      AND p.owner_id=NEW.owner_id AND p.broker_account_id=a.id) THEN\n      RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514';\n    END IF;\n    RETURN NEW;\n  ELSIF TG_TABLE_NAME='analytics_runs' THEN\n    IF NOT EXISTS (SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id\n      WHERE a.id=NEW.broker_account_id AND c.owner_id=NEW.owner_id) THEN\n      RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514';\n    END IF;\n    RETURN NEW;\n  ELSIF TG_TABLE_NAME='contribution_plan_requests' THEN\n    request_row := NEW;\n  ELSIF body->>'request_id' IS NOT NULL THEN\n    SELECT * INTO request_row FROM contribution_plan_requests WHERE id=(body->>'request_id')::uuid;\n  ELSIF body->>'result_id' IS NOT NULL THEN\n    SELECT r.* INTO request_row FROM contribution_plan_requests r JOIN contribution_plan_revisions v\n      ON v.request_id=r.id WHERE v.id=(body->>'result_id')::uuid;\n  ELSIF body->>'job_id' IS NOT NULL THEN\n    SELECT r.* INTO request_row FROM contribution_plan_requests r JOIN contribution_plan_jobs j\n      ON j.request_id=r.id WHERE j.id=(body->>'job_id')::uuid;\n  ELSIF body->>'run_id' IS NOT NULL THEN\n    SELECT * INTO run_row FROM analytics_runs WHERE id=(body->>'run_id')::uuid;\n    IF run_row.owner_id IS DISTINCT FROM NEW.owner_id THEN\n      RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514';\n    END IF;\n    account_id := run_row.broker_account_id;\n    SELECT target_version_id INTO target_id FROM analytics_run_sources\n      WHERE run_id=run_row.id AND target_version_id IS NOT NULL LIMIT 1;\n  END IF;\n  IF request_row.id IS NOT NULL THEN\n    SELECT * INTO plan_row FROM contribution_plans WHERE id=request_row.plan_id;\n    account_id := plan_row.broker_account_id;\n    target_id := request_row.target_version_id;\n    IF plan_row.owner_id IS DISTINCT FROM NEW.owner_id OR request_row.owner_id IS DISTINCT FROM NEW.owner_id\n      OR NOT EXISTS (SELECT 1 FROM target_versions t JOIN portfolio_snapshots s ON s.id=request_row.snapshot_id\n        JOIN calculation_runs c ON c.id=request_row.calculation_run_id\n        WHERE t.id=target_id AND t.owner_id=NEW.owner_id AND t.virtual_portfolio_id=plan_row.virtual_portfolio_id\n        AND t.content_digest=request_row.target_content_digest AND t.published_at IS NOT NULL\n        AND s.broker_account_id=account_id AND s.calculation_run_id=c.id AND c.broker_account_id=account_id\n        AND t.reporting_currency=request_row.reporting_currency AND s.reporting_currency=request_row.reporting_currency)\n      THEN RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514'; END IF;\n  END IF;\n  IF body->>'broker_account_id' IS NOT NULL AND (body->>'broker_account_id')::uuid IS DISTINCT FROM account_id THEN\n    RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514';\n  END IF;\n  ref := coalesce((body->>'target_node_id')::uuid,(body->>'node_id')::uuid);\n  IF ref IS NOT NULL AND NOT EXISTS (SELECT 1 FROM target_nodes n WHERE n.id=ref AND n.owner_id=NEW.owner_id AND n.target_version_id=target_id) THEN\n    RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514';\n  END IF;\n  ref := (body->>'holding_id')::uuid;\n  IF ref IS NOT NULL AND NOT EXISTS (SELECT 1 FROM target_holdings h WHERE h.id=ref AND h.owner_id=NEW.owner_id AND h.target_version_id=target_id\n    AND (body->>'target_node_id' IS NULL OR h.node_id=(body->>'target_node_id')::uuid)\n    AND (body->>'node_id' IS NULL OR h.node_id=(body->>'node_id')::uuid)) THEN\n    RAISE EXCEPTION 'Invalid planning scope' USING ERRCODE='23514';\n  END IF;\n  ref := coalesce((body->>'source_record_id')::uuid,(body->>'fx_source_id')::uuid);\n  IF ref IS NOT NULL AND NOT EXISTS (SELECT 1 FROM source_records r WHERE r.id=ref AND r.broker_account_id=account_id) THEN\n    RAISE EXCEPTION 'Invalid planning source scope' USING ERRCODE='23514';\n  END IF;\n  ref := (body->>'snapshot_id')::uuid;\n  IF ref IS NOT NULL AND NOT EXISTS (SELECT 1 FROM portfolio_snapshots s WHERE s.id=ref AND s.broker_account_id=account_id) THEN\n    RAISE EXCEPTION 'Invalid planning source scope' USING ERRCODE='23514';\n  END IF;\n  ref := (body->>'target_version_id')::uuid;\n  IF ref IS NOT NULL AND NOT EXISTS (SELECT 1 FROM target_versions t WHERE t.id=ref AND t.owner_id=NEW.owner_id AND t.published_at IS NOT NULL) THEN\n    RAISE EXCEPTION 'Invalid planning source scope' USING ERRCODE='23514';\n  END IF;\n  RETURN NEW;\nEND $$;\n\nCREATE FUNCTION planning_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN\n  RAISE EXCEPTION 'Immutable planning record' USING ERRCODE='23514';\nEND $$;\n\nCREATE FUNCTION planning_child_seal_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE body jsonb:=to_jsonb(NEW); sealed boolean:=false;\nBEGIN\n  IF body->>'request_id' IS NOT NULL THEN\n    SELECT pg_xact_status(xmin::text::xid8) = 'committed' INTO sealed FROM contribution_plan_requests WHERE id=(body->>'request_id')::uuid;\n  ELSIF body->>'result_id' IS NOT NULL THEN\n    SELECT pg_xact_status(xmin::text::xid8) = 'committed' INTO sealed FROM contribution_plan_revisions WHERE id=(body->>'result_id')::uuid;\n  ELSIF body->>'run_id' IS NOT NULL THEN\n    SELECT pg_xact_status(xmin::text::xid8) = 'committed' INTO sealed FROM analytics_runs WHERE id=(body->>'run_id')::uuid;\n  END IF;\n  IF sealed THEN RAISE EXCEPTION 'Immutable planning record' USING ERRCODE='23514'; END IF;\n  RETURN NEW;\nEND $$;\n\nCREATE FUNCTION planning_economic_seal_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE body jsonb:= CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;\n        ref uuid; pinned boolean:=false;\nBEGIN\n  IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;\n  ref:=(body->>'id')::uuid;\n  IF TG_TABLE_NAME IN ('snapshot_positions','snapshot_cash') THEN\n    ref:=(body->>'snapshot_id')::uuid;\n    SELECT EXISTS(SELECT 1 FROM contribution_plan_requests WHERE snapshot_id=ref)\n      OR EXISTS(SELECT 1 FROM analytics_run_sources WHERE snapshot_id=ref) INTO pinned;\n  ELSIF TG_TABLE_NAME='portfolio_snapshots' THEN\n    SELECT EXISTS(SELECT 1 FROM contribution_plan_requests WHERE snapshot_id=ref)\n      OR EXISTS(SELECT 1 FROM analytics_run_sources WHERE snapshot_id=ref) INTO pinned;\n  ELSIF TG_TABLE_NAME='calculation_runs' THEN\n    SELECT EXISTS(SELECT 1 FROM contribution_plan_requests WHERE calculation_run_id=ref)\n      OR EXISTS(SELECT 1 FROM portfolio_snapshots s JOIN analytics_run_sources a ON a.snapshot_id=s.id WHERE s.calculation_run_id=ref) INTO pinned;\n  ELSIF TG_TABLE_NAME='source_records' THEN\n    SELECT EXISTS(SELECT 1 FROM contribution_plan_sources WHERE source_record_id=ref)\n      OR EXISTS(SELECT 1 FROM analytics_run_sources WHERE source_record_id=ref) INTO pinned;\n  END IF;\n  IF pinned THEN RAISE EXCEPTION 'Pinned economic source is immutable' USING ERRCODE='23514'; END IF;\n  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;\nEND $$;\n"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plans FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_requests FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_requests FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_inputs FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_inputs FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_inputs FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_catalog FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_catalog FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_catalog FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_request_constraints FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_request_constraints FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_request_constraints FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_selections FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_selections FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_selections FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_holding_constraints FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_holding_constraints FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_holding_constraints FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_sources FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_sources FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_sources FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_revisions FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_revisions FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_lines FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_lines FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_lines FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_explanations FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_explanations FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON contribution_plan_explanations FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON planning_command_identities FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON planning_command_identities FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_jobs FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_dispatch_outbox FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON contribution_plan_attempts FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON contribution_plan_attempts FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON planning_audit_events FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON planning_audit_events FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON analytics_runs FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON analytics_runs FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON analytics_run_sources FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON analytics_run_sources FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON analytics_run_sources FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON analytics_drift_rows FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON analytics_drift_rows FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_child_seal BEFORE INSERT ON analytics_drift_rows FOR EACH ROW EXECUTE FUNCTION planning_child_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_economic_seal BEFORE UPDATE OR DELETE ON portfolio_snapshots FOR EACH ROW EXECUTE FUNCTION planning_economic_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_economic_seal BEFORE INSERT OR UPDATE OR DELETE ON snapshot_positions FOR EACH ROW EXECUTE FUNCTION planning_economic_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_economic_seal BEFORE INSERT OR UPDATE OR DELETE ON snapshot_cash FOR EACH ROW EXECUTE FUNCTION planning_economic_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_economic_seal BEFORE UPDATE OR DELETE ON calculation_runs FOR EACH ROW EXECUTE FUNCTION planning_economic_seal_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_economic_seal BEFORE UPDATE OR DELETE ON source_records FOR EACH ROW EXECUTE FUNCTION planning_economic_seal_guard()"
    )

    op.execute(
        "CREATE TRIGGER planning_scope BEFORE INSERT OR UPDATE ON planning_collection_bindings FOR EACH ROW EXECUTE FUNCTION planning_scope_guard()"
    )
    op.execute(
        "CREATE TRIGGER planning_immutable BEFORE UPDATE ON planning_collection_bindings FOR EACH ROW EXECUTE FUNCTION planning_immutable_guard()"
    )


def downgrade() -> None:
    # Published financial artifacts cannot be discarded by a schema rollback.
    # Empty disposable databases remain reversible for historical migration tests.
    connection = op.get_bind()
    for table in (
        "analytics_runs",
        "contribution_plans",
        "analytics_run_sources",
        "contribution_plan_requests",
        "contribution_plan_catalog",
        "contribution_plan_inputs",
        "contribution_plan_jobs",
        "contribution_plan_request_constraints",
        "contribution_plan_revisions",
        "planning_audit_events",
        "planning_command_identities",
        "analytics_drift_rows",
        "contribution_plan_attempts",
        "contribution_plan_dispatch_outbox",
        "contribution_plan_explanations",
        "contribution_plan_holding_constraints",
        "contribution_plan_lines",
        "contribution_plan_selections",
        "contribution_plan_sources",
    ):
        relation = sa.table(table, sa.column("id"))
        if connection.scalar(sa.select(sa.exists(sa.select(relation.c.id).limit(1)))):
            raise RuntimeError("Planning schema downgrade requires empty planning tables.")
    op.execute("DROP TRIGGER planning_economic_seal ON portfolio_snapshots")
    op.execute("DROP TRIGGER planning_economic_seal ON snapshot_positions")
    op.execute("DROP TRIGGER planning_economic_seal ON snapshot_cash")
    op.execute("DROP TRIGGER planning_economic_seal ON calculation_runs")
    op.execute("DROP TRIGGER planning_economic_seal ON source_records")
    op.drop_table("planning_collection_bindings")
    op.drop_table("contribution_plan_sources")
    op.drop_table("contribution_plan_selections")
    op.drop_table("contribution_plan_lines")
    op.drop_table("contribution_plan_holding_constraints")
    op.drop_table("contribution_plan_explanations")
    op.drop_table("contribution_plan_dispatch_outbox")
    op.drop_table("contribution_plan_attempts")
    op.drop_table("analytics_drift_rows")
    op.drop_table("planning_command_identities")
    op.drop_table("planning_audit_events")
    op.drop_table("contribution_plan_revisions")
    op.drop_table("contribution_plan_request_constraints")
    op.drop_table("contribution_plan_jobs")
    op.drop_table("contribution_plan_inputs")
    op.drop_table("contribution_plan_catalog")
    op.drop_table("contribution_plan_requests")
    op.drop_table("analytics_run_sources")
    op.drop_table("contribution_plans")
    op.drop_table("analytics_runs")
    op.execute("DROP FUNCTION planning_scope_guard()")
    op.execute("DROP FUNCTION planning_immutable_guard()")
    op.execute("DROP FUNCTION planning_child_seal_guard()")
    op.execute("DROP FUNCTION planning_economic_seal_guard()")
    op.execute(
        "DELETE FROM collection_query_snapshots WHERE resource IN ('contribution_plans','plan_revisions','plan_lines','actual_target_rows')"
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('activity','dividends','positions_market_value','positions_weight','positions_ticker') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes'))",
    )
