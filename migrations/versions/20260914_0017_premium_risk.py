"""Bounded premium jobs and normalized risk records after the accepted Phase 2 head.

Revision ID: 20260914_0017
Revises: 20260911_0016

Frozen SQLAlchemy schema only; no mutable application/model imports.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_0017"
down_revision = "20260911_0016"
branch_labels = None
depends_on = None

_PREVIOUS_SCOPES = "'portfolio:read','activity:read','analytics:read','portfolio:refresh','configuration:read','targets:read','targets:write','plans:write','reports:read','reports:write','alerts:read','alerts:write'"
_PREMIUM_SCOPES = "'portfolio:read','activity:read','analytics:read','portfolio:refresh','configuration:read','targets:read','targets:write','plans:write','reports:read','reports:write','alerts:read','alerts:write','risk:write','scenarios:write','projections:write','goals:write','research:read','research:write','preferences:read','preferences:write','aggregate:read','aggregate:write'"
_PREVIOUS_COMMANDS = "command IN ('reports.generate.v1','exports.generate.v1')"
_PREMIUM_COMMANDS = "command IN ('reports.generate.v1','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1')"
_PREVIOUS_COMMAND_PARENT = "(command='reports.generate.v1' AND report_job_id IS NOT NULL AND export_job_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL)"
_PREMIUM_COMMAND_PARENT = "(command='reports.generate.v1' AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL)"


def _scopes(value: str) -> None:
    name = op.f("ck_principal_scope_grants_scope_allowed")
    op.drop_constraint(name, "principal_scope_grants", type_="check")
    op.create_check_constraint(name, "principal_scope_grants", "scope IN (" + value + ")")


def _commands(*, premium: bool) -> None:
    for name, value in (
        ("command_allowed", _PREMIUM_COMMANDS if premium else _PREVIOUS_COMMANDS),
        ("parent_kind", _PREMIUM_COMMAND_PARENT if premium else _PREVIOUS_COMMAND_PARENT),
    ):
        constraint = op.f("ck_application_command_identities_" + name)
        op.drop_constraint(constraint, "application_command_identities", type_="check")
        op.create_check_constraint(constraint, "application_command_identities", value)


_PREVIOUS_COLLECTIONS = {
    "resource_allowed": "resource IN ('intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "(resource IN ('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc')",
    "account_scope_match": "((resource IN ('intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
}


def _collections(*, premium: bool) -> None:
    for name, previous in _PREVIOUS_COLLECTIONS.items():
        value = previous
        if premium:
            if name == "resource_sort_match":
                value = (
                    "("
                    + previous
                    + ") OR (resource IN ('risk_definitions','risk_runs') AND sort_specification='created_at_desc_id_desc') OR (resource='risk_versions' AND sort_specification='version_number_desc_id_desc')"
                )
            elif name == "account_scope_match":
                value = (
                    "("
                    + previous
                    + ") OR (resource IN ('risk_definitions','risk_versions','risk_runs') AND broker_account_id IS NOT NULL)"
                )
            else:
                value = previous.replace(
                    "resource IN (",
                    "resource IN ('risk_definitions','risk_versions','risk_runs',",
                    1,
                )
        constraint = op.f("ck_collection_query_snapshots_" + name)
        op.drop_constraint(constraint, "collection_query_snapshots", type_="check")
        op.create_check_constraint(constraint, "collection_query_snapshots", value)


def upgrade() -> None:
    _collections(premium=True)
    _scopes(_PREMIUM_SCOPES)
    op.add_column(
        "application_command_identities", sa.Column("premium_resource_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "application_command_identities", sa.Column("premium_actor_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "application_command_identities",
        sa.Column("premium_correlation_id", sa.String(120), nullable=True),
    )
    op.create_unique_constraint(
        "uq_application_command_scoped_identity",
        "application_command_identities",
        ["owner_id", "account_id", "id"],
    )
    op.create_foreign_key(
        "fk_application_command_premium_actor",
        "application_command_identities",
        "principals",
        ["owner_id", "premium_actor_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    _commands(premium=True)
    op.create_table(
        "premium_owner_capacity",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("retained_bytes", sa.BigInteger(), nullable=False),
        sa.Column("active_jobs", sa.Integer(), nullable=False),
        sa.Column("definition_versions", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "active_jobs BETWEEN 0 AND 2 AND definition_versions BETWEEN 0 AND 512",
            name=op.f("ck_premium_owner_capacity_count_bound"),
        ),
        sa.CheckConstraint(
            "reserved_bytes >= 0 AND retained_bytes >= 0 AND reserved_bytes + retained_bytes <= 268435456",
            name=op.f("ck_premium_owner_capacity_bytes_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_owner_capacity_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("owner_id", name=op.f("pk_premium_owner_capacity")),
    )
    op.create_table(
        "risk_definitions",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name=op.f("ck_risk_definitions_name_bound")
        ),
        sa.CheckConstraint(
            "revision BETWEEN 1 AND 512", name=op.f("ck_risk_definitions_revision_bound")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_definitions_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_definitions_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_definitions")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_risk_definitions_owner_id")
        ),
    )
    op.create_index(
        "ix_risk_definitions_owner_account_created",
        "risk_definitions",
        ["owner_id", "account_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "risk_definition_versions",
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), nullable=True),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("return_kind", sa.String(length=10), nullable=False),
        sa.Column("annual_risk_free", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column(
            "annual_minimum_acceptable_return", sa.Numeric(precision=38, scale=18), nullable=False
        ),
        sa.Column("rolling_window", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("regularization", sa.String(length=30), nullable=False),
        sa.Column("shrinkage", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("method_version", sa.String(length=40), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_risk_definition_versions_content_digest_format"),
        ),
        sa.CheckConstraint(
            "frequency IN ('daily','monthly') AND return_kind IN ('simple','log')",
            name=op.f("ck_risk_definition_versions_return_basis"),
        ),
        sa.CheckConstraint(
            "method_version='1.0.0' AND char_length(name) BETWEEN 1 AND 120",
            name=op.f("ck_risk_definition_versions_version_name"),
        ),
        sa.CheckConstraint(
            "regularization IN ('none','diagonal_shrinkage') AND (regularization <> 'none' OR shrinkage=0)",
            name=op.f("ck_risk_definition_versions_shrinkage_explicit"),
        ),
        sa.CheckConstraint(
            "rolling_window BETWEEN 20 AND CASE WHEN frequency='daily' THEN 252 ELSE 120 END AND horizon BETWEEN 1 AND CASE WHEN frequency='daily' THEN 20 ELSE 12 END",
            name=op.f("ck_risk_definition_versions_window_bounds"),
        ),
        sa.CheckConstraint(
            "annual_risk_free > -1 AND annual_risk_free <= 1 AND annual_minimum_acceptable_return > -1 AND annual_minimum_acceptable_return <= 1",
            name=op.f("ck_risk_definition_versions_annual_bounds"),
        ),
        sa.CheckConstraint(
            "confidence IN (0.90,0.95,0.99) AND shrinkage BETWEEN 0 AND 1",
            name=op.f("ck_risk_definition_versions_estimator_bounds"),
        ),
        sa.CheckConstraint(
            "version_number BETWEEN 1 AND 512 AND (version_number=1) = (predecessor_id IS NULL)",
            name=op.f("ck_risk_definition_versions_version_order"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_definition_versions_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "definition_id", "predecessor_id"],
            [
                "risk_definition_versions.owner_id",
                "risk_definition_versions.account_id",
                "risk_definition_versions.definition_id",
                "risk_definition_versions.id",
            ],
            name="fk_risk_version_predecessor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "definition_id"],
            ["risk_definitions.owner_id", "risk_definitions.account_id", "risk_definitions.id"],
            name="fk_premium_risk_definitions_definition_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "calendar_id"],
            ["source_calendars.owner_id", "source_calendars.id"],
            name="fk_risk_source_calendars_calendar_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_definition_versions_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_definition_versions")),
        sa.UniqueConstraint(
            "definition_id",
            "version_number",
            name=op.f("uq_risk_definition_versions_definition_id"),
        ),
        sa.UniqueConstraint(
            "owner_id",
            "account_id",
            "definition_id",
            "id",
            name="uq_risk_version_definition_identity",
        ),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_risk_definition_versions_owner_id")
        ),
    )
    op.create_index(
        "ix_risk_versions_definition_number",
        "risk_definition_versions",
        ["definition_id", "version_number", "id"],
        unique=False,
    )
    op.create_table(
        "premium_audit_events",
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('created','cancelled')", name=op.f("ck_premium_audit_events_kind_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_premium_audit_events_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "command_id"],
            [
                "application_command_identities.owner_id",
                "application_command_identities.account_id",
                "application_command_identities.id",
            ],
            name="fk_premium_application_command_identities_command_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_audit_events_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_audit_events")),
        sa.UniqueConstraint("command_id", "kind", name=op.f("uq_premium_audit_events_command_id")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_premium_audit_events_owner_id")
        ),
    )
    op.create_table(
        "premium_runs",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.Uuid(), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method_version", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("numerical_profile", sa.String(length=60), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("retained_bytes", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_premium_runs_input_digest_format")
        ),
        sa.CheckConstraint(
            "kind IN ('risk','scenario','projection')", name=op.f("ck_premium_runs_kind_allowed")
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_premium_runs_expiry_order")),
        sa.CheckConstraint(
            "reserved_bytes BETWEEN 0 AND 33554432 AND retained_bytes BETWEEN 0 AND 33554432",
            name=op.f("ck_premium_runs_byte_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_premium_runs_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_principal_id"],
            ["principals.id"],
            name=op.f("fk_premium_runs_actor_principal_id_principals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "command_id"],
            [
                "application_command_identities.owner_id",
                "application_command_identities.account_id",
                "application_command_identities.id",
            ],
            name="fk_premium_application_command_identities_command_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_runs_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_runs")),
        sa.UniqueConstraint("command_id", name=op.f("uq_premium_runs_command_id")),
        sa.UniqueConstraint("owner_id", "account_id", "id", name=op.f("uq_premium_runs_owner_id")),
    )
    op.create_index("ix_premium_runs_expiry", "premium_runs", ["expires_at", "id"], unique=False)
    op.create_index(
        "ix_premium_runs_owner_account_created",
        "premium_runs",
        ["owner_id", "account_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "premium_jobs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("consumer_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumer_id", sa.String(length=120), nullable=True),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ('publication_unavailable','consumer_unavailable','lease_expired','invalid_message','input_unavailable','input_changed','access_denied','calculation_failed','storage_unavailable','attempts_exhausted','limit_exceeded','source_restricted')",
            name=op.f("ck_premium_jobs_failure_allowed"),
        ),
        sa.CheckConstraint(
            "(state IN ('succeeded','failed','expired','cancelled')) = (completed_at IS NOT NULL)",
            name=op.f("ck_premium_jobs_completion_state"),
        ),
        sa.CheckConstraint(
            "(state='running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND consumer_id IS NOT NULL AND deadline_at IS NOT NULL) OR (state<>'running' AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND consumer_id IS NULL AND deadline_at IS NULL)",
            name=op.f("ck_premium_jobs_lease_state"),
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','succeeded','failed','expired','cancelled')",
            name=op.f("ck_premium_jobs_state_allowed"),
        ),
        sa.CheckConstraint(
            "consumer_attempts BETWEEN 0 AND 4", name=op.f("ck_premium_jobs_attempts_bound")
        ),
        sa.CheckConstraint(
            "deadline_at IS NULL OR heartbeat_at <= deadline_at",
            name=op.f("ck_premium_jobs_deadline_order"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_premium_jobs_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            name="fk_premium_premium_runs_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_jobs_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_jobs")),
        sa.UniqueConstraint("owner_id", "account_id", "id", name=op.f("uq_premium_jobs_owner_id")),
        sa.UniqueConstraint("run_id", name=op.f("uq_premium_jobs_run_id")),
    )
    op.create_index(
        "ix_premium_jobs_owner_state", "premium_jobs", ["owner_id", "state", "id"], unique=False
    )
    op.create_index(
        "ix_premium_jobs_state_lease",
        "premium_jobs",
        ["state", "lease_expires_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_premium_single_running",
        "premium_jobs",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state = 'running'"),
    )
    op.create_table(
        "premium_retention_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('source_restricted','run_expired','owner_erasure')",
            name=op.f("ck_premium_retention_events_reason_allowed"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name=op.f("ck_premium_retention_events_completed_order"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_premium_retention_events_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            name="fk_premium_premium_runs_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_retention_events_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_retention_events")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_premium_retention_events_owner_id")
        ),
        sa.UniqueConstraint("run_id", name=op.f("uq_premium_retention_events_run_id")),
    )
    op.create_index(
        "ix_premium_retention_pending",
        "premium_retention_events",
        ["completed_at", "owner_id", "id"],
        unique=False,
    )
    op.create_table(
        "risk_runs",
        sa.Column("definition_version_id", sa.Uuid(), nullable=False),
        sa.Column("historical_input_id", sa.Uuid(), nullable=False),
        sa.Column("historical_input_digest", sa.String(length=64), nullable=False),
        sa.Column("portfolio_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("benchmark_version_id", sa.Uuid(), nullable=True),
        sa.Column("xray_run_id", sa.Uuid(), nullable=True),
        sa.Column("window_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reporting_currency", sa.String(length=3), nullable=False),
        sa.Column("sealed", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "historical_input_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_risk_runs_historical_input_digest_format"),
        ),
        sa.CheckConstraint(
            "reporting_currency ~ '^[A-Z]{3}$' AND window_start_at < window_end_at AND window_end_at <= source_cutoff_at",
            name=op.f("ck_risk_runs_window_currency"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_runs_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "definition_version_id"],
            [
                "risk_definition_versions.owner_id",
                "risk_definition_versions.account_id",
                "risk_definition_versions.id",
            ],
            name="fk_premium_risk_definition_versions_definition_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            name="fk_premium_premium_runs_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "benchmark_version_id"],
            ["benchmark_versions.owner_id", "benchmark_versions.id"],
            name="fk_risk_benchmark_versions_benchmark_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "historical_input_id"],
            ["historical_input_snapshots.owner_id", "historical_input_snapshots.id"],
            name="fk_risk_historical_input_snapshots_historical_input_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "xray_run_id"],
            ["xray_runs.owner_id", "xray_runs.id"],
            name="fk_risk_xray_runs_xray_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_runs_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_id"],
            ["portfolio_snapshots.id"],
            name=op.f("fk_risk_runs_portfolio_snapshot_id_portfolio_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_runs")),
        sa.UniqueConstraint("owner_id", "account_id", "id", name=op.f("uq_risk_runs_owner_id")),
    )
    op.create_index(
        "ix_risk_runs_historical", "risk_runs", ["historical_input_id", "id"], unique=False
    )
    op.create_index("ix_risk_runs_xray", "risk_runs", ["xray_run_id", "id"], unique=False)
    op.create_table(
        "premium_dispatch_outbox",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("publication_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatcher_id", sa.String(length=120), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ('publication_unavailable','consumer_unavailable','lease_expired','invalid_message','input_unavailable','input_changed','access_denied','calculation_failed','storage_unavailable','attempts_exhausted','limit_exceeded','source_restricted')",
            name=op.f("ck_premium_dispatch_outbox_failure_allowed"),
        ),
        sa.CheckConstraint(
            "(state='claimed' AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL AND dispatcher_id IS NOT NULL) OR (state<>'claimed' AND claim_token IS NULL AND claim_expires_at IS NULL AND dispatcher_id IS NULL)",
            name=op.f("ck_premium_dispatch_outbox_claim_state"),
        ),
        sa.CheckConstraint(
            "state IN ('pending','claimed','published','completed','dead_letter')",
            name=op.f("ck_premium_dispatch_outbox_state_allowed"),
        ),
        sa.CheckConstraint(
            "task_name IN ('risk.calculate.v1','scenarios.calculate.v1','projections.calculate.v1')",
            name=op.f("ck_premium_dispatch_outbox_fixed_tasks"),
        ),
        sa.CheckConstraint(
            "publication_attempts BETWEEN 0 AND 8",
            name=op.f("ck_premium_dispatch_outbox_attempts_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_premium_dispatch_outbox_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "job_id"],
            ["premium_jobs.owner_id", "premium_jobs.account_id", "premium_jobs.id"],
            name="fk_premium_premium_jobs_job_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_dispatch_outbox_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_dispatch_outbox")),
        sa.UniqueConstraint("job_id", name=op.f("uq_premium_dispatch_outbox_job_id")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_premium_dispatch_outbox_owner_id")
        ),
    )
    op.create_index(
        "ix_premium_outbox_available",
        "premium_dispatch_outbox",
        ["state", "available_at", "id"],
        unique=False,
    )
    op.create_table(
        "premium_job_attempts",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("event", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ('publication_unavailable','consumer_unavailable','lease_expired','invalid_message','input_unavailable','input_changed','access_denied','calculation_failed','storage_unavailable','attempts_exhausted','limit_exceeded','source_restricted')",
            name=op.f("ck_premium_job_attempts_failure_allowed"),
        ),
        sa.CheckConstraint(
            "event IN ('claimed','published','succeeded','failed','expired','cancelled')",
            name=op.f("ck_premium_job_attempts_event_allowed"),
        ),
        sa.CheckConstraint(
            "kind IN ('publication','consumer')", name=op.f("ck_premium_job_attempts_kind_allowed")
        ),
        sa.CheckConstraint(
            "sequence BETWEEN 1 AND 100 AND attempt_number BETWEEN 0 AND 8",
            name=op.f("ck_premium_job_attempts_count_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_premium_job_attempts_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "job_id"],
            ["premium_jobs.owner_id", "premium_jobs.account_id", "premium_jobs.id"],
            name="fk_premium_premium_jobs_job_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_premium_job_attempts_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_premium_job_attempts")),
        sa.UniqueConstraint("job_id", "sequence", name=op.f("uq_premium_job_attempts_job_id")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_premium_job_attempts_owner_id")
        ),
    )
    op.create_table(
        "risk_results",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("canonical_result", sa.LargeBinary(), nullable=False),
        sa.Column("series_count", sa.Integer(), nullable=False),
        sa.Column("interval_count", sa.Integer(), nullable=False),
        sa.Column("matrix_cell_count", sa.Integer(), nullable=False),
        sa.Column("component_count", sa.Integer(), nullable=False),
        sa.Column("metric_count", sa.Integer(), nullable=False),
        sa.Column("sealed", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_risk_results_content_digest_format")
        ),
        sa.CheckConstraint(
            "octet_length(canonical_result) <= 33554432", name=op.f("ck_risk_results_payload_bound")
        ),
        sa.CheckConstraint(
            "series_count BETWEEN 1 AND 34 AND interval_count BETWEEN 0 AND 100000 AND matrix_cell_count BETWEEN 0 AND 3072 AND component_count BETWEEN 0 AND 32 AND metric_count BETWEEN 1 AND 8192",
            name=op.f("ck_risk_results_count_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_results_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["risk_runs.owner_id", "risk_runs.account_id", "risk_runs.id"],
            name="fk_premium_risk_runs_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_results_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_results")),
        sa.UniqueConstraint("owner_id", "account_id", "id", name=op.f("uq_risk_results_owner_id")),
        sa.UniqueConstraint("run_id", name=op.f("uq_risk_results_run_id")),
    )
    op.create_index("ix_risk_result_run", "risk_results", ["run_id", "id"], unique=False)
    op.create_table(
        "risk_run_assets",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("source_series_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 31", name=op.f("ck_risk_run_assets_ordinal_bound")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_run_assets_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_risk_run_assets_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["risk_runs.owner_id", "risk_runs.account_id", "risk_runs.id"],
            name="fk_premium_risk_runs_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_series_id"],
            ["market_source_series.owner_id", "market_source_series.id"],
            name="fk_risk_market_source_series_source_series_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_run_assets_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_run_assets")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_risk_run_assets_owner_id")
        ),
        sa.UniqueConstraint("run_id", "instrument_id", name="uq_risk_assets_instrument"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_risk_assets_ordinal"),
        sa.UniqueConstraint("run_id", "source_series_id", name="uq_risk_assets_source"),
    )
    op.create_index("ix_risk_assets_run", "risk_run_assets", ["run_id", "id"], unique=False)
    op.create_table(
        "risk_components",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("weight_reason", sa.String(length=40), nullable=True),
        sa.Column("marginal", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("marginal_reason", sa.String(length=40), nullable=True),
        sa.Column("component", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("component_reason", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "component IS NULL OR (component > '-Infinity'::numeric AND component < 'Infinity'::numeric)",
            name=op.f("ck_risk_components_component_finite"),
        ),
        sa.CheckConstraint(
            "marginal IS NULL OR (marginal > '-Infinity'::numeric AND marginal < 'Infinity'::numeric)",
            name=op.f("ck_risk_components_marginal_finite"),
        ),
        sa.CheckConstraint(
            "weight IS NULL OR (weight > '-Infinity'::numeric AND weight < 'Infinity'::numeric)",
            name=op.f("ck_risk_components_weight_finite"),
        ),
        sa.CheckConstraint(
            "(component IS NULL) = (component_reason IS NOT NULL)",
            name=op.f("ck_risk_components_component_availability"),
        ),
        sa.CheckConstraint(
            "(marginal IS NULL) = (marginal_reason IS NOT NULL)",
            name=op.f("ck_risk_components_marginal_availability"),
        ),
        sa.CheckConstraint(
            "(weight IS NULL) = (weight_reason IS NOT NULL)",
            name=op.f("ck_risk_components_weight_availability"),
        ),
        sa.CheckConstraint(
            "weight IS NULL OR weight BETWEEN 0 AND 1", name=op.f("ck_risk_components_weight_bound")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_components_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_risk_components_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            ["risk_results.owner_id", "risk_results.account_id", "risk_results.id"],
            name="fk_premium_risk_results_result_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_components_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_components")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_risk_components_owner_id")
        ),
        sa.UniqueConstraint(
            "result_id", "instrument_id", name=op.f("uq_risk_components_result_id")
        ),
    )
    op.create_index(
        "ix_risk_components_result", "risk_components", ["result_id", "id"], unique=False
    )
    op.create_table(
        "risk_metrics",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name=op.f("ck_risk_metrics_value_finite"),
        ),
        sa.CheckConstraint(
            "(value IS NULL AND reason IS NOT NULL) OR (value IS NOT NULL AND (reason IS NULL OR key='observed.maximum_drawdown'))",
            name=op.f("ck_risk_metrics_value_availability"),
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 3660 AND char_length(key) BETWEEN 1 AND 80",
            name=op.f("ck_risk_metrics_key_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_metrics_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            ["risk_results.owner_id", "risk_results.account_id", "risk_results.id"],
            name="fk_premium_risk_results_result_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_metrics_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_metrics")),
        sa.UniqueConstraint("owner_id", "account_id", "id", name=op.f("uq_risk_metrics_owner_id")),
        sa.UniqueConstraint("result_id", "key", "ordinal", name=op.f("uq_risk_metrics_result_id")),
    )
    op.create_index("ix_risk_metrics_result", "risk_metrics", ["result_id", "id"], unique=False)
    op.create_table(
        "risk_series",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("series_key", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("interval_count", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind IN ('portfolio','benchmark') AND series_key=kind) OR (kind='asset' AND series_key=instrument_id::text)",
            name=op.f("ck_risk_series_series_key"),
        ),
        sa.CheckConstraint(
            "kind IN ('portfolio','benchmark','asset') AND (kind='asset') = (instrument_id IS NOT NULL)",
            name=op.f("ck_risk_series_series_identity"),
        ),
        sa.CheckConstraint(
            "interval_count BETWEEN 0 AND 3660", name=op.f("ck_risk_series_count_bound")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_series_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_risk_series_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            ["risk_results.owner_id", "risk_results.account_id", "risk_results.id"],
            name="fk_premium_risk_results_result_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_series_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_series")),
        sa.UniqueConstraint("owner_id", "account_id", "id", name=op.f("uq_risk_series_owner_id")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "result_id", "id", name="uq_risk_series_result_identity"
        ),
        sa.UniqueConstraint("result_id", "series_key", name=op.f("uq_risk_series_result_id")),
    )
    op.create_index("ix_risk_series_result", "risk_series", ["result_id", "id"], unique=False)
    op.create_table(
        "risk_intervals",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("simple_return", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("quality", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quality IN ('fresh','stale','partial','estimated','unreconciled','failed') AND (simple_return IS NOT NULL OR quality <> 'fresh')",
            name=op.f("ck_risk_intervals_quality_bound"),
        ),
        sa.CheckConstraint(
            "simple_return IS NULL OR (simple_return > '-Infinity'::numeric AND simple_return < 'Infinity'::numeric)",
            name=op.f("ck_risk_intervals_simple_return_finite"),
        ),
        sa.CheckConstraint(
            "(simple_return IS NULL) = (reason IS NOT NULL)",
            name=op.f("ck_risk_intervals_simple_return_availability"),
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 3659 AND start_at < end_at",
            name=op.f("ck_risk_intervals_interval_bound"),
        ),
        sa.CheckConstraint(
            "simple_return IS NULL OR simple_return >= -1",
            name=op.f("ck_risk_intervals_return_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_intervals_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "series_id"],
            [
                "risk_series.owner_id",
                "risk_series.account_id",
                "risk_series.result_id",
                "risk_series.id",
            ],
            name="fk_risk_interval_series_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            ["risk_results.owner_id", "risk_results.account_id", "risk_results.id"],
            name="fk_premium_risk_results_result_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_intervals_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_intervals")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_risk_intervals_owner_id")
        ),
        sa.UniqueConstraint("series_id", "ordinal", name=op.f("uq_risk_intervals_series_id")),
        sa.UniqueConstraint("series_id", "start_at", "end_at", name="uq_risk_intervals_boundaries"),
    )
    op.create_index("ix_risk_intervals_result", "risk_intervals", ["result_id", "id"], unique=False)
    op.create_table(
        "risk_matrix_cells",
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("row_series_id", sa.Uuid(), nullable=False),
        sa.Column("column_series_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind <> 'correlation' OR value IS NULL OR value BETWEEN -1 AND 1",
            name=op.f("ck_risk_matrix_cells_correlation_bound"),
        ),
        sa.CheckConstraint(
            "kind IN ('covariance','regularized_covariance','correlation')",
            name=op.f("ck_risk_matrix_cells_kind_allowed"),
        ),
        sa.CheckConstraint(
            "value IS NULL OR (value > '-Infinity'::numeric AND value < 'Infinity'::numeric)",
            name=op.f("ck_risk_matrix_cells_value_finite"),
        ),
        sa.CheckConstraint(
            "(value IS NULL) = (reason IS NOT NULL)",
            name=op.f("ck_risk_matrix_cells_value_availability"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["broker_accounts.id"],
            name=op.f("fk_risk_matrix_cells_account_id_broker_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "column_series_id"],
            [
                "risk_series.owner_id",
                "risk_series.account_id",
                "risk_series.result_id",
                "risk_series.id",
            ],
            name="fk_risk_matrix_column_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "row_series_id"],
            [
                "risk_series.owner_id",
                "risk_series.account_id",
                "risk_series.result_id",
                "risk_series.id",
            ],
            name="fk_risk_matrix_row_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id"],
            ["risk_results.owner_id", "risk_results.account_id", "risk_results.id"],
            name="fk_premium_risk_results_result_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_risk_matrix_cells_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_matrix_cells")),
        sa.UniqueConstraint(
            "owner_id", "account_id", "id", name=op.f("uq_risk_matrix_cells_owner_id")
        ),
        sa.UniqueConstraint(
            "result_id",
            "kind",
            "row_series_id",
            "column_series_id",
            name=op.f("uq_risk_matrix_cells_result_id"),
        ),
    )
    op.create_index("ix_risk_matrix_result", "risk_matrix_cells", ["result_id", "id"], unique=False)

    _guards()


def downgrade() -> None:
    _collections(premium=False)
    for trigger in ("premium_scope", "premium_command_complete"):
        op.execute(sa.text("DROP TRIGGER " + trigger + " ON application_command_identities"))
    op.drop_table("risk_matrix_cells")
    op.drop_table("risk_intervals")
    op.drop_table("risk_series")
    op.drop_table("risk_metrics")
    op.drop_table("risk_components")
    op.drop_table("risk_run_assets")
    op.drop_table("risk_results")
    op.drop_table("premium_job_attempts")
    op.drop_table("premium_dispatch_outbox")
    op.drop_table("risk_runs")
    op.drop_table("premium_retention_events")
    op.drop_table("premium_jobs")
    op.drop_table("premium_runs")
    op.drop_table("premium_audit_events")
    op.drop_table("risk_definition_versions")
    op.drop_table("risk_definitions")
    op.drop_table("premium_owner_capacity")
    _commands(premium=False)
    op.drop_constraint(
        "fk_application_command_premium_actor", "application_command_identities", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_application_command_scoped_identity", "application_command_identities", type_="unique"
    )
    for column in ("premium_resource_id", "premium_actor_id", "premium_correlation_id"):
        op.drop_column("application_command_identities", column)
    _scopes(_PREVIOUS_SCOPES)
    for name in (
        "premium_scope_guard",
        "premium_immutable_guard",
        "premium_child_guard",
        "premium_run_complete",
        "premium_result_complete",
        "premium_definition_complete",
        "premium_command_complete",
    ):
        op.execute(sa.text("DROP FUNCTION " + name + "()"))


def _guards() -> None:
    op.execute(sa.text(_GUARDS))
    op.execute(
        sa.text(
            "CREATE TRIGGER premium_scope BEFORE INSERT OR UPDATE ON application_command_identities FOR EACH ROW EXECUTE FUNCTION premium_scope_guard()"
        )
    )
    op.execute(
        sa.text(
            "CREATE CONSTRAINT TRIGGER premium_command_complete AFTER INSERT ON application_command_identities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION premium_command_complete()"
        )
    )
    for table in (
        "premium_runs",
        "premium_jobs",
        "premium_dispatch_outbox",
        "premium_job_attempts",
        "premium_retention_events",
        "premium_audit_events",
        "risk_definitions",
        "risk_definition_versions",
        "risk_runs",
        "risk_run_assets",
        "risk_results",
        "risk_series",
        "risk_intervals",
        "risk_matrix_cells",
        "risk_metrics",
        "risk_components",
    ):
        op.execute(
            sa.text(
                "CREATE TRIGGER premium_scope BEFORE INSERT OR UPDATE ON "
                + table
                + " FOR EACH ROW EXECUTE FUNCTION premium_scope_guard()"
            )
        )
    for table in (
        "premium_runs",
        "premium_jobs",
        "premium_dispatch_outbox",
        "premium_retention_events",
        "risk_definitions",
        "premium_job_attempts",
        "premium_audit_events",
        "risk_definition_versions",
        "risk_runs",
        "risk_run_assets",
        "risk_results",
        "risk_series",
        "risk_intervals",
        "risk_matrix_cells",
        "risk_metrics",
        "risk_components",
    ):
        op.execute(
            sa.text(
                "CREATE TRIGGER premium_immutable BEFORE UPDATE OR DELETE ON "
                + table
                + " FOR EACH ROW EXECUTE FUNCTION premium_immutable_guard()"
            )
        )
    for table in (
        "risk_run_assets",
        "risk_series",
        "risk_intervals",
        "risk_matrix_cells",
        "risk_metrics",
        "risk_components",
    ):
        op.execute(
            sa.text(
                "CREATE TRIGGER premium_child BEFORE INSERT ON "
                + table
                + " FOR EACH ROW EXECUTE FUNCTION premium_child_guard()"
            )
        )
    op.execute(
        sa.text(
            "CREATE CONSTRAINT TRIGGER premium_definition_complete AFTER INSERT OR UPDATE ON risk_definitions "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION premium_definition_complete()"
        )
    )
    op.execute(
        sa.text(
            "CREATE CONSTRAINT TRIGGER premium_run_complete AFTER INSERT ON premium_runs "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION premium_run_complete()"
        )
    )
    op.execute(
        sa.text(
            "CREATE CONSTRAINT TRIGGER premium_result_complete AFTER INSERT ON risk_results "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION premium_result_complete()"
        )
    )


_GUARDS = r"""
CREATE FUNCTION premium_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; pinned boolean; version integer; family text; snapshot uuid; cutoff timestamptz;
BEGIN
 IF TG_TABLE_NAME='application_command_identities' THEN
  IF NEW.command NOT LIKE 'risk.%' THEN RETURN NEW; END IF;
 END IF;
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT owner_id INTO actual FROM principals WHERE id=NEW.actor_principal_id;
  IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium principal scope mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT premium_resource_id INTO actual FROM application_command_identities WHERE id=NEW.command_id AND command='risk.run.create.v1' AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF actual IS DISTINCT FROM NEW.id THEN RAISE EXCEPTION 'Premium run command mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='risk_definition_versions' AND TG_OP='INSERT' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)>=512 THEN RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514'; END IF;
  SELECT revision INTO version FROM risk_definitions WHERE id=NEW.definition_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF version IS DISTINCT FROM NEW.version_number THEN RAISE EXCEPTION 'Risk aggregate revision mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT version_number INTO version FROM risk_definition_versions WHERE id=NEW.predecessor_id AND definition_id=NEW.definition_id;
   IF version IS DISTINCT FROM NEW.version_number-1 THEN RAISE EXCEPTION 'Risk predecessor mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_runs' THEN
  SELECT kind INTO family FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF family IS DISTINCT FROM 'risk' THEN RAISE EXCEPTION 'Risk run family mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id, sealed INTO actual,pinned FROM historical_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.historical_input_id AND input_digest=NEW.historical_input_digest;
  IF actual IS DISTINCT FROM NEW.account_id OR NOT coalesce(pinned,false) THEN RAISE EXCEPTION 'Risk history binding mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id INTO actual FROM portfolio_snapshots WHERE id=NEW.portfolio_snapshot_id;
  IF actual IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Risk snapshot binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.xray_run_id IS NOT NULL THEN
   SELECT i.account_id,i.snapshot_id,i.source_cutoff_at INTO actual,snapshot,cutoff FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id WHERE r.id=NEW.xray_run_id AND r.owner_id=NEW.owner_id AND r.sealed_at IS NOT NULL AND i.sealed_at IS NOT NULL;
   IF actual IS DISTINCT FROM NEW.account_id OR snapshot IS DISTINCT FROM NEW.portfolio_snapshot_id OR cutoff IS DISTINCT FROM NEW.source_cutoff_at THEN RAISE EXCEPTION 'Risk X-ray binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_run_assets' THEN
  SELECT instrument_id INTO actual FROM market_source_series WHERE id=NEW.source_series_id AND owner_id=NEW.owner_id;
  IF actual IS DISTINCT FROM NEW.instrument_id THEN RAISE EXCEPTION 'Risk asset source mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_dispatch_outbox' THEN
  SELECT r.kind INTO family FROM premium_jobs j JOIN premium_runs r ON r.id=j.run_id WHERE j.id=NEW.job_id;
  IF NEW.task_name IS DISTINCT FROM (CASE family WHEN 'risk' THEN 'risk.calculate.v1' WHEN 'scenario' THEN 'scenarios.calculate.v1' WHEN 'projection' THEN 'projections.calculate.v1' END) THEN RAISE EXCEPTION 'Premium task identity mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_jobs' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Premium capacity reservation missing' USING ERRCODE='23514'; END IF;
  IF NEW.state IN ('queued','running') AND (SELECT count(*) FROM premium_jobs WHERE owner_id=NEW.owner_id AND id<>NEW.id AND state IN ('queued','running')) >= 2 THEN RAISE EXCEPTION 'Premium owner active capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; run uuid; allowed boolean;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='risk_definitions' THEN
  IF NEW.revision=OLD.revision+1 AND NEW.updated_at>=OLD.updated_at AND (to_jsonb(NEW)-ARRAY['revision','name','archived','updated_at'])=(body-ARRAY['revision','name','archived','updated_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_jobs' THEN
  IF (to_jsonb(NEW)-ARRAY['state','consumer_attempts','lease_token','lease_expires_at','heartbeat_at','deadline_at','consumer_id','failure_code','completed_at'])=(body-ARRAY['state','consumer_attempts','lease_token','lease_expires_at','heartbeat_at','deadline_at','consumer_id','failure_code','completed_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_dispatch_outbox' THEN
  IF (to_jsonb(NEW)-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','published_at','failure_code'])=(body-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','published_at','failure_code']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_retention_events' THEN
  IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL AND (to_jsonb(NEW)-'completed_at')=(body-'completed_at') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('risk_runs','risk_results') AND TG_OP='UPDATE' THEN
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' AND TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['reserved_bytes','retained_bytes'])=(body-ARRAY['reserved_bytes','retained_bytes']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('risk_run_assets','risk_results','risk_series','risk_intervals','risk_matrix_cells','risk_metrics','risk_components') THEN
  IF TG_TABLE_NAME IN ('risk_run_assets','risk_results') THEN run:=(body->>'run_id')::uuid;
  ELSE SELECT run_id INTO run FROM risk_results WHERE id=(body->>'result_id')::uuid; END IF;
  SELECT EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=OLD.owner_id AND account_id=OLD.account_id AND run_id=run) INTO allowed;
  IF allowed AND TG_OP='DELETE' AND TG_TABLE_NAME<>'risk_results' THEN RETURN OLD; END IF;
  IF allowed AND TG_OP='UPDATE' AND TG_TABLE_NAME='risk_results' THEN
   IF NEW.canonical_result='\x'::bytea AND (to_jsonb(NEW)-'canonical_result')=(body-'canonical_result') THEN RETURN NEW; END IF;
  END IF;
 END IF;
 RAISE EXCEPTION 'Published premium content is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION premium_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean;
BEGIN
 IF TG_TABLE_NAME='risk_run_assets' THEN SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.run_id FOR UPDATE;
 ELSE SELECT sealed INTO pinned FROM risk_results WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.result_id FOR UPDATE; END IF;
 IF coalesce(pinned,true) THEN RAISE EXCEPTION 'Premium parent is already sealed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_definition_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE aggregate risk_definitions; version risk_definition_versions;
BEGIN
 SELECT * INTO aggregate FROM risk_definitions WHERE id=NEW.id;
 SELECT * INTO version FROM risk_definition_versions WHERE definition_id=NEW.id ORDER BY version_number DESC LIMIT 1;
 IF version.id IS NULL OR aggregate.revision IS DISTINCT FROM version.version_number OR aggregate.name IS DISTINCT FROM version.name THEN RAISE EXCEPTION 'Risk definition publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_command_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; account uuid;
BEGIN
 IF NEW.command NOT LIKE 'risk.%' THEN RETURN NEW; END IF;
 IF NEW.command='risk.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='risk.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('risk.run.create.v1','risk.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='risk'; END IF;
 IF actual IS DISTINCT FROM NEW.owner_id OR account IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Premium command target mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_run_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean; jobs integer;
BEGIN
 IF NEW.kind<>'risk' THEN RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.id;
 SELECT count(*) INTO jobs FROM premium_jobs j JOIN premium_dispatch_outbox o ON o.job_id=j.id AND o.owner_id=j.owner_id AND o.account_id=j.account_id WHERE j.run_id=NEW.id;
 IF NOT coalesce(pinned,false) OR jobs<>1 THEN RAISE EXCEPTION 'Premium request publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION premium_result_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current risk_results; state text;
BEGIN
 SELECT * INTO current FROM risk_results WHERE id=NEW.id;
 SELECT j.state INTO state FROM premium_jobs j WHERE j.run_id=NEW.run_id AND j.owner_id=NEW.owner_id AND j.account_id=NEW.account_id;
 IF NOT current.sealed OR octet_length(current.canonical_result)=0 OR state IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'Premium result publication incomplete' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM risk_series WHERE result_id=NEW.id)<>current.series_count OR
    (SELECT count(*) FROM risk_intervals WHERE result_id=NEW.id)<>current.interval_count OR
    (SELECT count(*) FROM risk_matrix_cells WHERE result_id=NEW.id)<>current.matrix_cell_count OR
    (SELECT count(*) FROM risk_metrics WHERE result_id=NEW.id)<>current.metric_count OR
    (SELECT count(*) FROM risk_components WHERE result_id=NEW.id)<>current.component_count THEN RAISE EXCEPTION 'Premium normalized publication incomplete' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM risk_series s WHERE s.result_id=NEW.id AND s.interval_count<>(SELECT count(*) FROM risk_intervals i WHERE i.series_id=s.id)) THEN RAISE EXCEPTION 'Premium series publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
