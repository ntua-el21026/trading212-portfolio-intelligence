"""Private reproducible report storage and fenced durable execution.

Revision ID: 20260909_0014
Revises: 20260909_0013

DDL is frozen here; the migration never imports mutable application models.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)

revision = "20260909_0014"
down_revision = "20260909_0013"
branch_labels = None
depends_on = None

REPORT_STATES = "'queued','running','succeeded','failed','expired','cancelled'"

REPORT_TYPES = "'monthly','quarterly','annual','portfolio_summary','target_drift','contribution_plan','performance_benchmark','dividend_income','portfolio_xray','quality_reconciliation'"

REPORT_SCOPES = "'portfolio:read','activity:read','analytics:read','portfolio:refresh','configuration:read','targets:read','targets:write','plans:write','reports:read','reports:write'"

REPORT_FAILURES = "'invalid_input','input_unavailable','input_changed','access_denied','source_restricted','limit_exceeded','render_failed','storage_unavailable','publication_unavailable','lease_expired','attempts_exhausted'"


def _owned(table: str) -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id")


def _parent(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{target}.owner_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


def _job_constraints(
    table: str,
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        UniqueConstraint("owner_id", "account_id", "id", name=f"uq_{table}_account_id"),
        UniqueConstraint("input_id", name=f"uq_{table}_input"),
        _parent(table, "principal_id", "principals"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "input_id"],
            [
                "report_input_snapshots.owner_id",
                "report_input_snapshots.account_id",
                "report_input_snapshots.id",
            ],
            name=f"fk_{table}_input_id",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"state IN ({REPORT_STATES})", name="state_allowed"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({REPORT_FAILURES})", name="failure_allowed"
        ),
        CheckConstraint("consumer_attempts BETWEEN 0 AND 4 AND fence >= 0", name="attempt_bound"),
        CheckConstraint(
            "expires_at > requested_at AND expires_at <= requested_at + interval '30 days'",
            name="expiry_bound",
        ),
        CheckConstraint(
            "command_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint("authorization_policy='report_delegation_v1'", name="policy_allowed"),
        CheckConstraint(
            "(state='running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL AND consumer_id IS NOT NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "state<>'succeeded' OR (completed_at IS NOT NULL AND manifest_digest IS NOT NULL AND failure_code IS NULL)",
            name="success_state",
        ),
        Index(f"ix_{table}_owner_account_created", "owner_id", "account_id", "requested_at", "id"),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
        Index(f"ix_{table}_input", "owner_id", "input_id", "id"),
    )


def _manifest_constraints(
    table: str, jobs: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        _parent(table, "input_id", "report_input_snapshots"),
        UniqueConstraint("job_id", name=f"uq_{table}_job"),
        CheckConstraint("byte_length BETWEEN 1 AND 2097152", name="byte_bound"),
        CheckConstraint("publication_fence > 0", name="fence_positive"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
    )


def _artifact_constraints(
    table: str, jobs: str, manifests: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        _parent(table, "manifest_id", manifests),
        UniqueConstraint("job_id", "format", name=f"uq_{table}_job_format"),
        CheckConstraint("format IN ('pdf','csv','json','xlsx')", name="format_allowed"),
        CheckConstraint("byte_length BETWEEN 1 AND 10485760", name="byte_bound"),
        CheckConstraint("publication_fence > 0", name="fence_positive"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "contents IS NULL OR octet_length(contents)=byte_length", name="content_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (contents IS NOT NULL)", name="payload_state"),
        CheckConstraint("expires_at > created_at", name="expiry_order"),
        CheckConstraint("filename ~ '^[A-Za-z0-9._-]{1,160}$'", name="filename_safe"),
        Index(f"ix_{table}_expiry", "owner_id", "expires_at", "id"),
    )


def _dispatch_constraints(
    table: str, jobs: str, task: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        UniqueConstraint("job_id", "task_name", "schema_version", name=f"uq_{table}_job_task"),
        CheckConstraint(f"task_name='{task}' AND schema_version='1.0.0'", name="task_fixed"),
        CheckConstraint(
            "state IN ('pending','claimed','published','dead_letter')", name="state_allowed"
        ),
        CheckConstraint("publication_attempts BETWEEN 0 AND 8", name="attempt_bound"),
        CheckConstraint(
            "(state='claimed') = (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL AND dispatcher_id IS NOT NULL)",
            name="claim_state",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({REPORT_FAILURES})", name="failure_allowed"
        ),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
    )


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','exports')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource IN ('historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','exports') AND sort_specification = 'created_at_desc_id_desc')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    )
    op.create_unique_constraint("uq_principals_owner_id", "principals", ["owner_id", "id"])
    op.create_table(
        "principal_scope_grants",
        sa.Column(
            "principal_id",
            sa.Uuid(),
            ForeignKey("principals.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("scope", String(40), primary_key=True, nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        CheckConstraint(f"scope IN ({REPORT_SCOPES})", name="scope_allowed"),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="expiry_order"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="revoke_order"),
    )
    op.create_table(
        "report_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("report_type", String(40), nullable=False),
        sa.Column("period_rule", String(30), nullable=False),
        sa.Column("sections", ARRAY(String(30)), nullable=False),
        sa.Column("template_version", String(40), nullable=False),
        sa.Column("reporting_currency", String(3), nullable=False),
        sa.Column("revision", Integer, nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        _owned("report_definitions"),
        UniqueConstraint("owner_id", "content_digest", name="uq_report_definitions_digest"),
        CheckConstraint(f"report_type IN ({REPORT_TYPES})", name="type_allowed"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("cardinality(sections) BETWEEN 1 AND 13", name="section_bound"),
    )
    op.create_table(
        "report_input_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", String(10), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", Date, nullable=False),
        sa.Column("end_date", Date, nullable=False),
        sa.Column("valuation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reporting_currency", String(3), nullable=False),
        sa.Column("input_digest", String(64), nullable=False),
        sa.Column("document_digest", String(64), nullable=False),
        sa.Column("canonical_byte_length", BigInteger, nullable=False),
        sa.Column("chunk_count", Integer, nullable=False),
        sa.Column("pin_count", Integer, nullable=False),
        sa.Column("source_count", Integer, nullable=False),
        sa.Column("canonical_manifest", LargeBinary, nullable=True),
        sa.Column("canonical_context", LargeBinary, nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        _owned("report_input_snapshots"),
        UniqueConstraint("owner_id", "account_id", "id", name="uq_report_inputs_account_id"),
        CheckConstraint("kind IN ('report','export')", name="kind_allowed"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("document_digest ~ '^[0-9a-f]{64}$'", name="document_digest_format"),
        CheckConstraint("canonical_byte_length BETWEEN 0 AND 33554432", name="byte_bound"),
        CheckConstraint("chunk_count BETWEEN 0 AND 100000", name="chunk_bound"),
        CheckConstraint("pin_count BETWEEN 1 AND 256", name="pin_bound"),
        CheckConstraint("source_count BETWEEN 0 AND 100000", name="source_bound"),
        CheckConstraint(
            "end_date >= start_date AND end_date-start_date <= 3660", name="period_bound"
        ),
        CheckConstraint("expires_at > created_at", name="expiry_order"),
        CheckConstraint("octet_length(canonical_manifest) <= 2097152", name="manifest_bound"),
        CheckConstraint("octet_length(canonical_context) <= 2097152", name="context_bound"),
        CheckConstraint(
            "(purged_at IS NULL) = (canonical_manifest IS NOT NULL AND canonical_context IS NOT NULL)",
            name="payload_state",
        ),
        Index("ix_report_inputs_owner_expiry", "owner_id", "expires_at", "id"),
    )
    op.create_table(
        "report_input_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("table_key", String(80), nullable=False),
        sa.Column("ordinal", Integer, nullable=False),
        sa.Column("row_count", Integer, nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("payload", LargeBinary, nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        _owned("report_input_chunks"),
        _parent("report_input_chunks", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", "table_key", "ordinal", name="uq_report_chunks_table_ordinal"),
        CheckConstraint("ordinal >= 0 AND row_count BETWEEN 0 AND 100000", name="row_bound"),
        CheckConstraint("byte_length BETWEEN 1 AND 1048576", name="byte_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        Index("ix_report_chunks_input_id", "owner_id", "input_id", "id"),
    )
    op.create_table(
        "report_input_pins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", Integer, nullable=False),
        sa.Column("kind", String(80), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("content_digest", String(64), nullable=False),
        _owned("report_input_pins"),
        _parent("report_input_pins", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", "kind", "subject_id", name="uq_report_pins_subject"),
        CheckConstraint("ordinal BETWEEN 0 AND 255", name="ordinal_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_report_pins_input", "owner_id", "input_id", "ordinal"),
    )
    op.create_table(
        "report_input_dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", String(200), nullable=False),
        sa.Column("kind", String(80), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("fx_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("benchmark_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("corporate_action_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("classification_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("constituent_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("entity_evidence_version_id", sa.Uuid(), nullable=True),
        sa.Column("fund_definition_id", sa.Uuid(), nullable=True),
        sa.Column("fund_mapping_id", sa.Uuid(), nullable=True),
        _owned("report_input_dependencies"),
        _parent("report_input_dependencies", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", "source_key", name="uq_report_dependencies_source"),
        _parent("report_input_dependencies", "license_version_id", "provider_license_versions"),
        _parent("report_input_dependencies", "provider_id", "market_data_providers"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_report_dependencies_provider_license",
            ondelete="RESTRICT",
        ),
        _parent("report_input_dependencies", "price_snapshot_id", "price_snapshots"),
        _parent("report_input_dependencies", "fx_snapshot_id", "fx_snapshots"),
        _parent("report_input_dependencies", "benchmark_snapshot_id", "benchmark_snapshots"),
        _parent(
            "report_input_dependencies",
            "corporate_action_snapshot_id",
            "corporate_action_snapshots",
        ),
        _parent(
            "report_input_dependencies", "classification_snapshot_id", "classification_snapshots"
        ),
        _parent("report_input_dependencies", "constituent_snapshot_id", "constituent_snapshots"),
        _parent(
            "report_input_dependencies", "entity_evidence_version_id", "entity_evidence_versions"
        ),
        _parent("report_input_dependencies", "fund_definition_id", "fund_definitions"),
        _parent("report_input_dependencies", "fund_mapping_id", "fund_source_mappings"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "num_nonnulls(price_snapshot_id,fx_snapshot_id,benchmark_snapshot_id,corporate_action_snapshot_id,classification_snapshot_id,constituent_snapshot_id,entity_evidence_version_id,fund_definition_id,fund_mapping_id) = 1",
            name="physical_parent_xor",
        ),
        CheckConstraint(
            "COALESCE((kind='price' AND source_id=price_snapshot_id) OR (kind='fx' AND source_id=fx_snapshot_id) OR (kind='benchmark' AND source_id=benchmark_snapshot_id) OR (kind='corporate_action' AND source_id=corporate_action_snapshot_id) OR (kind='classification' AND source_id=classification_snapshot_id) OR (kind='constituent' AND source_id=constituent_snapshot_id) OR (kind='entity_evidence' AND source_id=entity_evidence_version_id) OR (kind='fund_definition' AND source_id=fund_definition_id) OR (kind='fund_mapping' AND source_id=fund_mapping_id),false)",
            name="source_kind",
        ),
        Index("ix_report_dependencies_input", "owner_id", "input_id", "id"),
        Index("ix_report_dependencies_license", "owner_id", "license_version_id", "input_id"),
        Index("ix_report_dependencies_source", "owner_id", "kind", "source_id", "input_id"),
    )
    op.create_table(
        "report_input_licenses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("license_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        _owned("report_input_licenses"),
        _parent("report_input_licenses", "input_id", "report_input_snapshots"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_report_input_licenses_provider_license",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("input_id", "license_version_id", name="uq_report_input_license"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_report_licenses_input", "owner_id", "input_id", "id"),
    )
    op.create_table(
        "report_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("command_digest", String(64), nullable=False),
        sa.Column("input_digest", String(64), nullable=False),
        sa.Column("authorization_policy", String(40), nullable=False),
        sa.Column("state", String(20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", String(40), nullable=True),
        sa.Column("consumer_attempts", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumer_id", String(120), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_digest", String(64), nullable=True),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("report_type", String(40), nullable=False),
        sa.Column("formats", ARRAY(String(10)), nullable=False),
        *_job_constraints("report_jobs"),
        _parent("report_jobs", "definition_id", "report_definitions"),
        CheckConstraint(f"report_type IN ({REPORT_TYPES})", name="type_allowed"),
        CheckConstraint(
            "cardinality(formats) BETWEEN 1 AND 4 AND formats <@ ARRAY['pdf','csv','json','xlsx']::varchar[]",
            name="format_bound",
        ),
    )
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("command_digest", String(64), nullable=False),
        sa.Column("input_digest", String(64), nullable=False),
        sa.Column("authorization_policy", String(40), nullable=False),
        sa.Column("state", String(20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", String(40), nullable=True),
        sa.Column("consumer_attempts", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumer_id", String(120), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_digest", String(64), nullable=True),
        sa.Column("dataset", String(30), nullable=False),
        sa.Column("field_set", String(10), nullable=False),
        sa.Column("format", String(10), nullable=False),
        *_job_constraints("export_jobs"),
        CheckConstraint(
            "dataset IN ('positions','activity','dividends','targets','plans','performance','xray','alerts')",
            name="dataset_allowed",
        ),
        CheckConstraint("field_set IN ('standard','audit')", name="field_set_allowed"),
        CheckConstraint("format IN ('csv','json','xlsx')", name="format_allowed"),
    )
    op.create_table(
        "application_command_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("command", String(40), nullable=False),
        sa.Column("idempotency_key", String(180), nullable=False),
        sa.Column("command_digest", String(64), nullable=False),
        sa.Column("report_job_id", sa.Uuid(), nullable=True),
        sa.Column("export_job_id", sa.Uuid(), nullable=True),
        _owned("application_command_identities"),
        UniqueConstraint(
            "owner_id", "command", "idempotency_key", name="uq_application_command_owner_key"
        ),
        _parent("application_command_identities", "report_job_id", "report_jobs"),
        _parent("application_command_identities", "export_job_id", "export_jobs"),
        CheckConstraint(
            "command IN ('reports.generate.v1','exports.generate.v1')", name="command_allowed"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,180}$'", name="key_format"),
        CheckConstraint("command_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "(command='reports.generate.v1' AND report_job_id IS NOT NULL AND export_job_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL)",
            name="parent_kind",
        ),
    )
    op.create_table(
        "report_manifests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("publication_fence", BigInteger, nullable=False),
        sa.Column("payload", LargeBinary, nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        *_manifest_constraints("report_manifests", "report_jobs"),
    )
    op.create_table(
        "export_manifests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("publication_fence", BigInteger, nullable=False),
        sa.Column("payload", LargeBinary, nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        *_manifest_constraints("export_manifests", "export_jobs"),
    )
    op.create_table(
        "report_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_id", sa.Uuid(), nullable=False),
        sa.Column("format", String(10), nullable=False),
        sa.Column("mime_type", String(100), nullable=False),
        sa.Column("filename", String(160), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("publication_fence", BigInteger, nullable=False),
        sa.Column("contents", LargeBinary, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        *_artifact_constraints("report_artifacts", "report_jobs", "report_manifests"),
    )
    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_id", sa.Uuid(), nullable=False),
        sa.Column("format", String(10), nullable=False),
        sa.Column("mime_type", String(100), nullable=False),
        sa.Column("filename", String(160), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("publication_fence", BigInteger, nullable=False),
        sa.Column("contents", LargeBinary, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        *_artifact_constraints("export_artifacts", "export_jobs", "export_manifests"),
    )
    op.create_table(
        "artifact_download_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("report_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("export_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("token_digest", String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _owned("artifact_download_grants"),
        _parent("artifact_download_grants", "report_artifact_id", "report_artifacts"),
        _parent("artifact_download_grants", "export_artifact_id", "export_artifacts"),
        CheckConstraint(
            "num_nonnulls(report_artifact_id,export_artifact_id)=1", name="artifact_xor"
        ),
        CheckConstraint("token_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "expires_at > issued_at AND expires_at <= issued_at + interval '5 minutes'",
            name="expiry_bound",
        ),
        UniqueConstraint("token_digest", name="uq_artifact_grants_digest"),
        Index("ix_artifact_grants_report", "owner_id", "report_artifact_id", "expires_at", "id"),
        Index("ix_artifact_grants_export", "owner_id", "export_artifact_id", "expires_at", "id"),
    )
    op.create_table(
        "report_dispatch_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", String(40), nullable=False),
        sa.Column("schema_version", String(20), nullable=False),
        sa.Column("state", String(20), nullable=False),
        sa.Column("publication_attempts", Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatcher_id", String(120), nullable=True),
        sa.Column("failure_code", String(40), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_dispatch_constraints("report_dispatch_outbox", "report_jobs", "reports.generate.v1"),
    )
    op.create_table(
        "export_dispatch_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", String(40), nullable=False),
        sa.Column("schema_version", String(20), nullable=False),
        sa.Column("state", String(20), nullable=False),
        sa.Column("publication_attempts", Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatcher_id", String(120), nullable=True),
        sa.Column("failure_code", String(40), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_dispatch_constraints("export_dispatch_outbox", "export_jobs", "exports.generate.v1"),
    )
    op.create_table(
        "report_job_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("report_job_id", sa.Uuid(), nullable=True),
        sa.Column("export_job_id", sa.Uuid(), nullable=True),
        sa.Column("phase", String(20), nullable=False),
        sa.Column("attempt", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("outcome", String(20), nullable=False),
        sa.Column("failure_code", String(40), nullable=True),
        _owned("report_job_attempts"),
        _parent("report_job_attempts", "report_job_id", "report_jobs"),
        _parent("report_job_attempts", "export_job_id", "export_jobs"),
        CheckConstraint("num_nonnulls(report_job_id,export_job_id)=1", name="job_xor"),
        CheckConstraint("phase IN ('dispatch','consumer')", name="phase_allowed"),
        CheckConstraint("attempt BETWEEN 1 AND 8 AND fence >= 0", name="attempt_bound"),
        CheckConstraint(
            "outcome IN ('claimed','published','succeeded','retry','failed','expired')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({REPORT_FAILURES})", name="failure_allowed"
        ),
        Index("ix_report_attempts_report", "owner_id", "report_job_id", "created_at"),
        Index("ix_report_attempts_export", "owner_id", "export_job_id", "created_at"),
    )
    op.create_table(
        "report_retention_work",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "owner_id", sa.Uuid(), ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("reason", String(10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _owned("report_retention_work"),
        _parent("report_retention_work", "input_id", "report_input_snapshots"),
        UniqueConstraint("input_id", name="uq_report_retention_input"),
        CheckConstraint("reason IN ('ttl','source','owner')", name="reason_allowed"),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="time_order"),
        Index("ix_report_retention_pending", "owner_id", "completed_at", "input_id"),
    )
    _guards()


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_allowed"),
        "collection_query_snapshots",
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource IN ('historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    )
    _drop_guards()
    op.drop_table("report_retention_work")
    op.drop_table("report_job_attempts")
    op.drop_table("export_dispatch_outbox")
    op.drop_table("report_dispatch_outbox")
    op.drop_table("artifact_download_grants")
    op.drop_table("export_artifacts")
    op.drop_table("report_artifacts")
    op.drop_table("export_manifests")
    op.drop_table("report_manifests")
    op.drop_table("application_command_identities")
    op.drop_table("export_jobs")
    op.drop_table("report_jobs")
    op.drop_table("report_input_licenses")
    op.drop_table("report_input_dependencies")
    op.drop_table("report_input_pins")
    op.drop_table("report_input_chunks")
    op.drop_table("report_input_snapshots")
    op.drop_table("report_definitions")
    op.drop_table("principal_scope_grants")
    op.drop_constraint("uq_principals_owner_id", "principals", type_="unique")


def _guards() -> None:
    op.execute(REPORT_GUARDS)
    for table in (
        "report_definitions",
        "report_input_snapshots",
        "report_input_chunks",
        "report_input_pins",
        "report_input_dependencies",
        "report_input_licenses",
        "application_command_identities",
        "report_manifests",
        "export_manifests",
        "report_artifacts",
        "export_artifacts",
        "report_job_attempts",
    ):
        op.execute(
            f"CREATE TRIGGER report_owned BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION report_owned_guard()"
        )


def _drop_guards() -> None:
    op.execute(REPORT_DROP_GUARDS)


REPORT_GUARDS = r"""
CREATE FUNCTION report_account_scope(p_owner uuid, p_account uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id
 WHERE a.id=p_account AND c.owner_id=p_owner)
$$;

CREATE FUNCTION report_capture_pending(p_owner uuid, p_input uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM report_input_snapshots WHERE owner_id=p_owner AND id=p_input
   AND (canonical_manifest IS NOT NULL OR canonical_context IS NOT NULL))
 OR EXISTS (SELECT 1 FROM report_input_chunks WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM report_manifests WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM export_manifests WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM report_artifacts a JOIN report_jobs j ON j.id=a.job_id AND j.owner_id=a.owner_id
   WHERE j.owner_id=p_owner AND j.input_id=p_input AND a.contents IS NOT NULL)
 OR EXISTS (SELECT 1 FROM export_artifacts a JOIN export_jobs j ON j.id=a.job_id AND j.owner_id=a.owner_id
   WHERE j.owner_id=p_owner AND j.input_id=p_input AND a.contents IS NOT NULL)
 OR EXISTS (SELECT 1 FROM artifact_download_grants g JOIN report_artifacts a ON a.id=g.report_artifact_id
   JOIN report_jobs j ON j.id=a.job_id WHERE g.owner_id=p_owner AND j.input_id=p_input)
 OR EXISTS (SELECT 1 FROM artifact_download_grants g JOIN export_artifacts a ON a.id=g.export_artifact_id
   JOIN export_jobs j ON j.id=a.job_id WHERE g.owner_id=p_owner AND j.input_id=p_input)
$$;

CREATE FUNCTION report_source_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb := to_jsonb(NEW); entry record; family text; identifier uuid;
BEGIN
 IF TG_TABLE_NAME IN ('source_retention_work','enrichment_retention_work') THEN
  IF NEW.phase<>'complete' THEN RETURN NEW; END IF;
 END IF;
 FOR entry IN SELECT * FROM jsonb_each_text(v) LOOP
  family := CASE entry.key WHEN 'price_snapshot_id' THEN 'price' WHEN 'fx_snapshot_id' THEN 'fx'
   WHEN 'benchmark_snapshot_id' THEN 'benchmark' WHEN 'corporate_action_snapshot_id' THEN 'corporate_action'
   WHEN 'constituent_snapshot_id' THEN 'constituent' WHEN 'classification_snapshot_id' THEN 'classification'
   WHEN 'entity_evidence_version_id' THEN 'entity_evidence' WHEN 'fund_definition_id' THEN 'fund_definition'
   WHEN 'fund_mapping_id' THEN 'fund_mapping' ELSE NULL END;
  IF family IS NOT NULL AND entry.value IS NOT NULL THEN
   identifier := entry.value::uuid;
   IF EXISTS (SELECT 1 FROM report_input_dependencies d WHERE d.owner_id=NEW.owner_id
       AND d.kind=family AND d.source_id=identifier AND report_capture_pending(d.owner_id,d.input_id)) THEN
    RAISE EXCEPTION 'Report source copies remain';
   END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER reports_source_completion BEFORE INSERT OR UPDATE ON source_retention_work FOR EACH ROW EXECUTE FUNCTION report_source_copy_guard();
CREATE TRIGGER reports_source_expiry BEFORE INSERT ON source_expiry_events FOR EACH ROW EXECUTE FUNCTION report_source_copy_guard();
CREATE TRIGGER reports_enrichment_completion BEFORE INSERT OR UPDATE ON enrichment_retention_work FOR EACH ROW EXECUTE FUNCTION report_source_copy_guard();
CREATE TRIGGER reports_enrichment_expiry BEFORE INSERT ON enrichment_expiry_events FOR EACH ROW EXECUTE FUNCTION report_source_copy_guard();

CREATE FUNCTION report_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report retention records are immutable'; END IF;
 SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Report retention input is absent'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Retention must start pending'; END IF;
  IF NEW.reason='ttl' AND inp.expires_at>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report has not expired'; END IF;
  IF NEW.reason='source' AND NOT EXISTS (
   SELECT 1 FROM report_input_dependencies d WHERE d.input_id=inp.id AND d.owner_id=inp.owner_id AND (
    d.expires_at<=CURRENT_TIMESTAMP OR EXISTS (
     SELECT 1 FROM source_retention_work w WHERE w.owner_id=d.owner_id AND
       (w.price_snapshot_id=d.price_snapshot_id OR w.fx_snapshot_id=d.fx_snapshot_id
       OR w.benchmark_snapshot_id=d.benchmark_snapshot_id OR w.corporate_action_snapshot_id=d.corporate_action_snapshot_id
       OR w.constituent_snapshot_id=d.constituent_snapshot_id)) OR EXISTS (
     SELECT 1 FROM enrichment_retention_work w WHERE w.owner_id=d.owner_id AND
       (w.entity_evidence_version_id=d.entity_evidence_version_id OR w.classification_snapshot_id=d.classification_snapshot_id
       OR w.fund_definition_id=d.fund_definition_id OR w.fund_mapping_id=d.fund_mapping_id)))) THEN
   RAISE EXCEPTION 'No expired report source';
  END IF;
  IF NEW.reason='owner' AND EXISTS (SELECT 1 FROM broker_accounts WHERE id=inp.account_id AND status='active') THEN
   RAISE EXCEPTION 'Owner termination requires inactive account';
  END IF;
 ELSE
  IF to_jsonb(NEW)-'completed_at' IS DISTINCT FROM to_jsonb(OLD)-'completed_at' OR OLD.completed_at IS NOT NULL THEN
   RAISE EXCEPTION 'Report retention identity is immutable';
  END IF;
 END IF;
 IF NEW.completed_at IS NOT NULL AND report_capture_pending(NEW.owner_id,NEW.input_id) THEN RAISE EXCEPTION 'Report payload remains'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER report_retention_authorized BEFORE INSERT OR UPDATE OR DELETE ON report_retention_work FOR EACH ROW EXECUTE FUNCTION report_retention_guard();

CREATE FUNCTION report_owned_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb; o jsonb; inp report_input_snapshots; jid uuid; jt text; job jsonb; physical uuid; actual_provider uuid; actual_license uuid;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report canonical records are immutable'; END IF;
 v:=to_jsonb(NEW);
 IF v ? 'account_id' AND NOT report_account_scope(NEW.owner_id,(v->>'account_id')::uuid) THEN RAISE EXCEPTION 'Report account scope mismatch'; END IF;
 IF TG_TABLE_NAME='report_input_snapshots' THEN
  IF NOT EXISTS (SELECT 1 FROM portfolio_snapshots WHERE id=NEW.snapshot_id AND broker_account_id=NEW.account_id) THEN RAISE EXCEPTION 'Report snapshot scope mismatch'; END IF;
  IF TG_OP='INSERT' AND NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Report capture must be built before sealing'; END IF;
  IF TG_OP='UPDATE' THEN
   o:=to_jsonb(OLD);
   IF OLD.sealed_at IS NULL THEN
    IF (v-'sealed_at'-'canonical_manifest'-'canonical_context'-'input_digest'-'document_digest'-'canonical_byte_length'-'chunk_count'-'pin_count'-'source_count'-'expires_at') IS DISTINCT FROM
       (o-'sealed_at'-'canonical_manifest'-'canonical_context'-'input_digest'-'document_digest'-'canonical_byte_length'-'chunk_count'-'pin_count'-'source_count'-'expires_at') THEN RAISE EXCEPTION 'Report capture identity changed'; END IF;
   ELSE
    IF v-'canonical_manifest'-'canonical_context'-'purged_at' IS DISTINCT FROM o-'canonical_manifest'-'canonical_context'-'purged_at'
       OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL OR NEW.canonical_manifest IS NOT NULL OR NEW.canonical_context IS NOT NULL
       OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=NEW.id AND completed_at IS NULL) THEN
     RAISE EXCEPTION 'Report capture is immutable';
    END IF;
   END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF v ? 'input_id' THEN
  SELECT * INTO inp FROM report_input_snapshots WHERE id=(v->>'input_id')::uuid AND owner_id=NEW.owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Report input scope mismatch'; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('report_input_chunks','report_input_pins','report_input_dependencies','report_input_licenses') THEN
  IF TG_OP='INSERT' AND (inp.sealed_at IS NOT NULL OR inp.purged_at IS NOT NULL OR inp.expires_at<=CURRENT_TIMESTAMP) THEN RAISE EXCEPTION 'Report capture is closed'; END IF;
  IF TG_TABLE_NAME='report_input_licenses' THEN
   IF NOT EXISTS (SELECT 1 FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND id=NEW.license_version_id) THEN RAISE EXCEPTION 'Report pinned license scope mismatch'; END IF;
  END IF;
  IF TG_TABLE_NAME='report_input_dependencies' THEN
   jt := CASE NEW.kind WHEN 'price' THEN 'price_snapshots' WHEN 'fx' THEN 'fx_snapshots' WHEN 'benchmark' THEN 'benchmark_snapshots'
    WHEN 'corporate_action' THEN 'corporate_action_snapshots' WHEN 'classification' THEN 'classification_snapshots'
    WHEN 'constituent' THEN 'constituent_snapshots' WHEN 'entity_evidence' THEN 'entity_evidence_versions'
    WHEN 'fund_definition' THEN 'fund_definitions' WHEN 'fund_mapping' THEN 'fund_source_mappings' END;
   EXECUTE format('SELECT provider_id,license_version_id FROM %I WHERE owner_id=$1 AND id=$2',jt)
     INTO actual_provider,actual_license USING NEW.owner_id,NEW.source_id;
   IF actual_provider IS DISTINCT FROM NEW.provider_id OR actual_license IS DISTINCT FROM NEW.license_version_id THEN RAISE EXCEPTION 'Report source license mismatch'; END IF;
  END IF;
  IF TG_OP='UPDATE' THEN
   IF TG_TABLE_NAME<>'report_input_chunks' THEN RAISE EXCEPTION 'Report source pins are immutable'; END IF;
   IF v-'payload'-'purged_at' IS DISTINCT FROM to_jsonb(OLD)-'payload'-'purged_at' OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL OR NEW.payload IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=NEW.input_id AND completed_at IS NULL) THEN RAISE EXCEPTION 'Report chunk is immutable'; END IF;
  ELSIF TG_TABLE_NAME='report_input_chunks' THEN
   IF encode(sha256(NEW.payload),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report chunk hash mismatch'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('report_manifests','export_manifests','report_artifacts','export_artifacts') THEN
  jt := CASE WHEN TG_TABLE_NAME LIKE 'report_%' THEN 'report_jobs' ELSE 'export_jobs' END;
  EXECUTE format('SELECT to_jsonb(j) FROM %I j WHERE owner_id=$1 AND id=$2',jt) INTO job USING NEW.owner_id,NEW.job_id;
  IF job IS NULL THEN RAISE EXCEPTION 'Report publication job is absent'; END IF;
  SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=(job->>'input_id')::uuid;
  IF TG_OP='UPDATE' THEN
   IF v-'payload'-'contents'-'purged_at' IS DISTINCT FROM to_jsonb(OLD)-'payload'-'contents'-'purged_at' OR OLD.purged_at IS NOT NULL OR NEW.purged_at IS NULL
    OR (v->>'payload') IS NOT NULL OR (v->>'contents') IS NOT NULL
    OR NOT EXISTS (SELECT 1 FROM report_retention_work WHERE owner_id=NEW.owner_id AND input_id=inp.id AND completed_at IS NULL) THEN RAISE EXCEPTION 'Report publication is immutable'; END IF;
   RETURN NEW;
  END IF;
  IF job->>'state'<>'running' OR (job->>'fence')::bigint<>NEW.publication_fence OR (job->>'lease_expires_at')::timestamptz<=CURRENT_TIMESTAMP
    OR inp.sealed_at IS NULL OR inp.purged_at IS NOT NULL OR inp.expires_at<=CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Report publication fence is stale'; END IF;
  IF TG_TABLE_NAME IN ('report_manifests','export_manifests') THEN
   IF NEW.input_id<>inp.id OR NEW.payload IS DISTINCT FROM inp.canonical_manifest OR encode(sha256(NEW.payload),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report manifest does not match capture'; END IF;
  ELSE
   IF NEW.account_id<>inp.account_id OR NEW.expires_at>(job->>'expires_at')::timestamptz OR encode(sha256(NEW.contents),'hex')<>NEW.content_digest THEN RAISE EXCEPTION 'Report artifact metadata mismatch'; END IF;
   jt := CASE WHEN TG_TABLE_NAME='report_artifacts' THEN 'report_manifests' ELSE 'export_manifests' END;
   EXECUTE format('SELECT to_jsonb(m) FROM %I m WHERE owner_id=$1 AND id=$2',jt) INTO job USING NEW.owner_id,NEW.manifest_id;
   IF job IS NULL OR (job->>'job_id')::uuid<>NEW.job_id OR (job->>'publication_fence')::bigint<>NEW.publication_fence THEN RAISE EXCEPTION 'Report artifact manifest mismatch'; END IF;
   IF NEW.mime_type<>(CASE NEW.format WHEN 'pdf' THEN 'application/pdf' WHEN 'csv' THEN 'text/csv; charset=utf-8' WHEN 'json' THEN 'application/json' WHEN 'xlsx' THEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' END) THEN RAISE EXCEPTION 'Report artifact MIME mismatch'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'Report canonical identity is immutable'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_capture_sealed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots; rows bigint; size bigint; pins bigint; sources bigint;
BEGIN
 SELECT * INTO inp FROM report_input_snapshots WHERE id=NEW.id;
 IF NOT FOUND OR inp.sealed_at IS NULL THEN RAISE EXCEPTION 'Unsealed report capture'; END IF;
 IF inp.purged_at IS NOT NULL THEN RETURN NEW; END IF;
 SELECT count(*),COALESCE(sum(byte_length),0) INTO rows,size FROM report_input_chunks WHERE input_id=inp.id;
 SELECT count(*) INTO pins FROM report_input_pins WHERE input_id=inp.id;
 SELECT count(*) INTO sources FROM report_input_dependencies WHERE input_id=inp.id;
 IF rows<>inp.chunk_count OR pins<>inp.pin_count OR sources<>inp.source_count OR size+octet_length(inp.canonical_manifest)<>inp.canonical_byte_length THEN RAISE EXCEPTION 'Report capture counts mismatch'; END IF;
 IF EXISTS (SELECT 1 FROM report_input_chunks WHERE input_id=inp.id GROUP BY table_key HAVING min(ordinal)<>0 OR max(ordinal)<>count(*)-1 OR sum(row_count)>100000) THEN RAISE EXCEPTION 'Report chunk ordering or row bound mismatch'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER report_capture_complete AFTER INSERT OR UPDATE ON report_input_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_capture_sealed();

CREATE FUNCTION report_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp report_input_snapshots; v jsonb:=to_jsonb(NEW); o jsonb; allowed text[] := ARRAY['state','completed_at','failure_code','consumer_attempts','fence','lease_id','lease_expires_at','heartbeat_at','consumer_id','available_at','manifest_digest'];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report job identity is immutable'; END IF;
 IF NOT report_account_scope(NEW.owner_id,NEW.account_id) THEN RAISE EXCEPTION 'Report job account mismatch'; END IF;
 SELECT * INTO inp FROM report_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND OR inp.account_id<>NEW.account_id OR NEW.input_digest<>inp.input_digest OR inp.kind<>(CASE TG_TABLE_NAME WHEN 'report_jobs' THEN 'report' ELSE 'export' END) THEN RAISE EXCEPTION 'Report job capture mismatch'; END IF;
 IF NEW.expires_at>inp.expires_at THEN RAISE EXCEPTION 'Report job extends source expiry'; END IF;
 IF TG_TABLE_NAME='report_jobs' AND NOT EXISTS (SELECT 1 FROM report_definitions WHERE id=(v->>'definition_id')::uuid AND owner_id=NEW.owner_id AND account_id=NEW.account_id AND report_type=v->>'report_type') THEN RAISE EXCEPTION 'Report definition scope mismatch'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'queued' OR NEW.fence<>0 OR NEW.consumer_attempts<>0 THEN RAISE EXCEPTION 'Report job must begin queued'; END IF;
 ELSE
  o:=to_jsonb(OLD);
  IF v-allowed IS DISTINCT FROM o-allowed THEN RAISE EXCEPTION 'Report job pins are immutable'; END IF;
  IF NEW.state='running' AND OLD.state<>'running' AND (OLD.state<>'queued' OR NEW.fence<>OLD.fence+1 OR NEW.consumer_attempts<>OLD.consumer_attempts+1) THEN RAISE EXCEPTION 'Report claim is not fenced'; END IF;
  IF NEW.state='running' AND OLD.state='running' AND NEW.lease_id IS DISTINCT FROM OLD.lease_id AND (OLD.lease_expires_at>CURRENT_TIMESTAMP OR NEW.fence<>OLD.fence+1 OR NEW.consumer_attempts<>OLD.consumer_attempts+1) THEN RAISE EXCEPTION 'Report active lease cannot be replaced'; END IF;
  IF NEW.state='running' AND OLD.state='running' AND NEW.lease_id IS NOT DISTINCT FROM OLD.lease_id
    AND (NEW.fence<>OLD.fence OR NEW.consumer_attempts<>OLD.consumer_attempts OR NEW.consumer_id IS DISTINCT FROM OLD.consumer_id)
    THEN RAISE EXCEPTION 'Report heartbeat cannot change its fence'; END IF;
  IF NEW.state<>'running' AND (NEW.fence<>OLD.fence OR NEW.consumer_attempts<>OLD.consumer_attempts) THEN RAISE EXCEPTION 'Only a claim advances the report fence'; END IF;
  IF OLD.state IN ('succeeded','failed','expired','cancelled') AND NEW.state<>OLD.state AND NEW.state NOT IN ('expired','cancelled') THEN RAISE EXCEPTION 'Terminal report cannot restart'; END IF;
  IF NEW.state='succeeded' AND (OLD.state<>'running' OR OLD.lease_expires_at<=CURRENT_TIMESTAMP OR NEW.fence<>OLD.fence) THEN RAISE EXCEPTION 'Report completion lease is stale'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION report_job_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j jsonb; formats text[]; actual_formats text[]; bytes bigint; count_manifests bigint; manifests text; artifacts text; outboxes text; kind text;
BEGIN
 EXECUTE format('SELECT to_jsonb(j) FROM %I j WHERE id=$1',TG_TABLE_NAME) INTO j USING NEW.id;
 IF j IS NULL THEN RETURN NEW; END IF;
 kind:=CASE TG_TABLE_NAME WHEN 'report_jobs' THEN 'report' ELSE 'export' END;
 manifests:=kind||'_manifests'; artifacts:=kind||'_artifacts'; outboxes:=kind||'_dispatch_outbox';
 IF NOT EXISTS (SELECT 1 FROM report_input_snapshots WHERE id=(j->>'input_id')::uuid AND sealed_at IS NOT NULL) THEN RAISE EXCEPTION 'Report job input is not sealed'; END IF;
 EXECUTE format('SELECT count(*) FROM %I WHERE job_id=$1',outboxes) INTO count_manifests USING NEW.id;
 IF count_manifests<>1 OR NOT EXISTS (SELECT 1 FROM application_command_identities WHERE owner_id=NEW.owner_id AND (report_job_id=NEW.id OR export_job_id=NEW.id) AND command_digest=NEW.command_digest AND account_id=NEW.account_id) THEN RAISE EXCEPTION 'Report job has no atomic delivery identity'; END IF;
 IF j->>'state'<>'succeeded' THEN RETURN NEW; END IF;
 EXECUTE format('SELECT count(*) FROM %I WHERE job_id=$1 AND content_digest=$2 AND publication_fence=$3 AND payload IS NOT NULL',manifests)
   INTO count_manifests USING NEW.id,j->>'manifest_digest',(j->>'fence')::bigint;
 EXECUTE format('SELECT array_agg(format ORDER BY format),COALESCE(sum(byte_length),0) FROM %I WHERE job_id=$1 AND publication_fence=$2 AND contents IS NOT NULL',artifacts)
   INTO actual_formats,bytes USING NEW.id,(j->>'fence')::bigint;
 IF kind='report' THEN SELECT array_agg(value ORDER BY value) INTO formats FROM jsonb_array_elements_text(j->'formats'); ELSE formats:=ARRAY[j->>'format']; END IF;
 IF count_manifests<>1 OR actual_formats IS DISTINCT FROM formats OR bytes>26214400 THEN RAISE EXCEPTION 'Report formats are not atomically complete'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER report_job_state BEFORE INSERT OR UPDATE OR DELETE ON report_jobs FOR EACH ROW EXECUTE FUNCTION report_job_guard();
CREATE TRIGGER export_job_state BEFORE INSERT OR UPDATE OR DELETE ON export_jobs FOR EACH ROW EXECUTE FUNCTION report_job_guard();
CREATE CONSTRAINT TRIGGER report_job_complete AFTER INSERT OR UPDATE ON report_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_job_complete();
CREATE CONSTRAINT TRIGGER export_job_complete AFTER INSERT OR UPDATE ON export_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_job_complete();

CREATE FUNCTION report_publication_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j jsonb; jt text;
BEGIN
 jt:=CASE WHEN TG_TABLE_NAME LIKE 'report_%' THEN 'report_jobs' ELSE 'export_jobs' END;
 EXECUTE format('SELECT to_jsonb(j) FROM %I j WHERE owner_id=$1 AND id=$2',jt) INTO j USING NEW.owner_id,NEW.job_id;
 IF j IS NULL OR j->>'state'<>'succeeded' OR (j->>'fence')::bigint<>NEW.publication_fence THEN
  RAISE EXCEPTION 'Report publication must commit with the successful job';
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER report_manifest_complete AFTER INSERT ON report_manifests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_publication_complete();
CREATE CONSTRAINT TRIGGER export_manifest_complete AFTER INSERT ON export_manifests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_publication_complete();
CREATE CONSTRAINT TRIGGER report_artifact_complete AFTER INSERT ON report_artifacts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_publication_complete();
CREATE CONSTRAINT TRIGGER export_artifact_complete AFTER INSERT ON export_artifacts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION report_publication_complete();

CREATE FUNCTION report_grant_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE art jsonb; jt text; parent uuid; count_active bigint;
BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.expires_at>CURRENT_TIMESTAMP AND OLD.revoked_at IS NULL AND NOT EXISTS (
   SELECT 1 FROM report_retention_work w JOIN report_jobs j ON j.input_id=w.input_id JOIN report_artifacts a ON a.job_id=j.id WHERE a.id=OLD.report_artifact_id AND w.completed_at IS NULL
   UNION ALL SELECT 1 FROM report_retention_work w JOIN export_jobs j ON j.input_id=w.input_id JOIN export_artifacts a ON a.job_id=j.id WHERE a.id=OLD.export_artifact_id AND w.completed_at IS NULL) THEN RAISE EXCEPTION 'Active artifact grant cannot be deleted'; END IF;
  RETURN OLD;
 END IF;
 IF TG_OP='UPDATE' THEN
  IF to_jsonb(NEW)-'last_used_at'-'revoked_at' IS DISTINCT FROM to_jsonb(OLD)-'last_used_at'-'revoked_at' OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN RAISE EXCEPTION 'Artifact grant scope is immutable'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.report_artifact_id IS NOT NULL THEN jt:='report_artifacts'; parent:=NEW.report_artifact_id; ELSE jt:='export_artifacts'; parent:=NEW.export_artifact_id; END IF;
 EXECUTE format('SELECT jsonb_build_object(''account_id'',a.account_id,''purged_at'',a.purged_at,''expires_at'',a.expires_at) FROM %I a WHERE owner_id=$1 AND id=$2 FOR UPDATE',jt) INTO art USING NEW.owner_id,parent;
 IF art IS NULL OR (art->>'account_id')::uuid<>NEW.account_id OR art->>'purged_at' IS NOT NULL OR NEW.expires_at>(art->>'expires_at')::timestamptz OR NEW.issued_at>=NEW.expires_at THEN RAISE EXCEPTION 'Artifact grant scope or expiry mismatch'; END IF;
 SELECT count(*) INTO count_active FROM artifact_download_grants WHERE owner_id=NEW.owner_id AND (report_artifact_id=parent OR export_artifact_id=parent) AND revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP;
 IF count_active>=10 THEN RAISE EXCEPTION 'Artifact grant capacity exceeded'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER artifact_grant_authorized BEFORE INSERT OR UPDATE OR DELETE ON artifact_download_grants FOR EACH ROW EXECUTE FUNCTION report_grant_guard();

CREATE FUNCTION report_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Report outbox identity is immutable'; END IF;
 IF TG_OP='UPDATE' AND to_jsonb(NEW)-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','failure_code','published_at'] IS DISTINCT FROM to_jsonb(OLD)-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','failure_code','published_at'] THEN RAISE EXCEPTION 'Report dispatch pins are immutable'; END IF;
 IF TG_OP='UPDATE' AND (NEW.publication_attempts<OLD.publication_attempts OR NEW.publication_attempts>OLD.publication_attempts+1) THEN RAISE EXCEPTION 'Report dispatch attempts are not bounded'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER report_dispatch_identity BEFORE INSERT OR UPDATE OR DELETE ON report_dispatch_outbox FOR EACH ROW EXECUTE FUNCTION report_dispatch_guard();
CREATE TRIGGER export_dispatch_identity BEFORE INSERT OR UPDATE OR DELETE ON export_dispatch_outbox FOR EACH ROW EXECUTE FUNCTION report_dispatch_guard();
"""

REPORT_DROP_GUARDS = r"""
DROP TRIGGER reports_source_completion ON source_retention_work;
DROP TRIGGER reports_source_expiry ON source_expiry_events;
DROP TRIGGER reports_enrichment_completion ON enrichment_retention_work;
DROP TRIGGER reports_enrichment_expiry ON enrichment_expiry_events;
DROP FUNCTION report_source_copy_guard();
DROP FUNCTION report_capture_sealed() CASCADE;
DROP FUNCTION report_owned_guard() CASCADE;
DROP FUNCTION report_job_guard() CASCADE;
DROP FUNCTION report_job_complete() CASCADE;
DROP FUNCTION report_publication_complete() CASCADE;
DROP FUNCTION report_grant_guard() CASCADE;
DROP FUNCTION report_dispatch_guard() CASCADE;
DROP FUNCTION report_retention_guard() CASCADE;
DROP FUNCTION report_capture_pending(uuid,uuid);
DROP FUNCTION report_account_scope(uuid,uuid);
"""
