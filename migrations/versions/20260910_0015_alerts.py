"""Immutable alert evaluations, ordered lifecycle jobs and provider invocation observations.

Revision ID: 20260910_0015
Revises: 20260909_0014

All DDL is frozen here; mutable application models are never imported.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)

revision = "20260910_0015"
down_revision = "20260909_0014"
branch_labels = None
depends_on = None


ALERT_STATES = "'queued','running','succeeded','failed','expired','cancelled'"

ALERT_LIFECYCLES = "'draft','active','paused','archived'"

ALERT_FAILURES = "'missing_input','missing_fx','currency_mismatch','unsupported','ambiguous_source','unknown_identity','unknown_denominator','incomplete_coverage','material_quality','inconclusive_lower_bound','not_configured','no_observations','source_restricted','source_expired','input_bound_exceeded','computation_failed','filtered_out','rule_paused','rule_archived','rule_superseded','lease_expired','attempts_exhausted','publication_unavailable','storage_unavailable','access_denied'"


def _owned(table: str) -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id")


def _account(table: str) -> UniqueConstraint:
    return UniqueConstraint("owner_id", "account_id", "id", name=f"uq_{table}_account_id")


def _parent(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{target}.owner_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


def _account_parent(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "account_id", column],
        [f"{target}.owner_id", f"{target}.account_id", f"{target}.id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


def _job(
    table: str,
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _account(table),
        _parent(table, "principal_id", "principals"),
        CheckConstraint(f"state IN ({ALERT_STATES})", name="state_allowed"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({ALERT_FAILURES})", name="failure_allowed"
        ),
        CheckConstraint("consumer_attempts BETWEEN 0 AND 4 AND fence >= 0", name="attempt_bound"),
        CheckConstraint(
            "(state='running') = (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL AND consumer_id IS NOT NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "state NOT IN ('succeeded','failed','expired','cancelled') OR completed_at IS NOT NULL",
            name="terminal_time",
        ),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
    )


def _outbox(
    table: str, jobs: str, task: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint | Index, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", jobs),
        UniqueConstraint("job_id", "task_name", name=f"uq_{table}_job_task"),
        CheckConstraint(f"task_name='{task}' AND schema_version='1.0.0'", name="task_allowed"),
        CheckConstraint(
            "state IN ('pending','claimed','published','failed')", name="state_allowed"
        ),
        CheckConstraint("publication_attempts BETWEEN 0 AND 8", name="attempt_bound"),
        CheckConstraint(
            "(state='claimed') = (claim_token IS NOT NULL AND dispatcher_id IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="claim_state",
        ),
        Index(f"ix_{table}_ready", "state", "available_at", "id"),
    )


def _attempt(
    table: str, job_table: str
) -> tuple[UniqueConstraint | ForeignKeyConstraint | CheckConstraint, ...]:
    return (
        _owned(table),
        _parent(table, "job_id", job_table),
        CheckConstraint("phase IN ('dispatch','consumer')", name="phase_allowed"),
        CheckConstraint("attempt BETWEEN 1 AND 8 AND fence>=0", name="attempt_bound"),
        CheckConstraint(
            "outcome IN ('claimed','published','retry','succeeded','failed','expired','cancelled')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({ALERT_FAILURES})", name="failure_allowed"
        ),
        UniqueConstraint("job_id", "phase", "attempt", "outcome", name=f"uq_{table}_outcome"),
    )


PROVIDER_CAPABILITIES = (
    "'price_history','corporate_actions','fx_rates','benchmark_series',"
    "'resolve_instrument','classifications','constituents'"
)

PROVIDER_FAILURES = (
    "'not_configured','unsupported','not_found','authentication_failed','access_denied',"
    "'rate_limited','timeout','transient_failure','invalid_schema','pagination_invalid',"
    "'license_denied','payload_too_large','permanent_failure'"
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
        "resource IN ('activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_resource_sort_match"),
        "collection_query_snapshots",
        "(resource IN ('historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc')",
    )
    op.drop_constraint(
        op.f("ck_principal_scope_grants_scope_allowed"), "principal_scope_grants", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_principal_scope_grants_scope_allowed"),
        "principal_scope_grants",
        "scope IN ('portfolio:read','activity:read','analytics:read','portfolio:refresh','configuration:read','targets:read','targets:write','plans:write','reports:read','reports:write','alerts:read','alerts:write')",
    )
    op.drop_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_collection_query_snapshots_account_scope_match"),
        "collection_query_snapshots",
        "((resource IN ('alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    )
    op.execute(
        sa.schema.CreateSequence(
            sa.Sequence("alert_admission_attempt_sequence", data_type=BigInteger())
        )
    )
    op.create_table(
        "alert_rules",
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
        sa.Column("name", String(120), nullable=False),
        sa.Column("lifecycle", String(20), nullable=False),
        sa.Column("revision", BigInteger, nullable=False),
        sa.Column("lifecycle_sequence", BigInteger, nullable=False),
        sa.Column("latest_version_id", sa.Uuid(), nullable=True),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("next_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_admission_sequence", BigInteger, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _owned("alert_rules"),
        _account("alert_rules"),
        _parent("alert_rules", "principal_id", "principals"),
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="name_bound"),
        CheckConstraint(f"lifecycle IN ({ALERT_LIFECYCLES})", name="lifecycle_allowed"),
        CheckConstraint("revision >= 1 AND lifecycle_sequence >= 1", name="revision_bound"),
        CheckConstraint(
            "lifecycle NOT IN ('active','paused') OR active_version_id IS NOT NULL",
            name="active_version_required",
        ),
        CheckConstraint(
            "last_admission_sequence IS NULL OR last_admission_sequence > 0",
            name="admission_sequence_positive",
        ),
        Index(
            "ix_alert_rules_due",
            "lifecycle",
            sa.text("last_admission_sequence ASC NULLS FIRST"),
            "next_scheduled_for",
            "id",
        ),
        Index("ix_alert_rules_owner_account", "owner_id", "account_id", "created_at", "id"),
    )
    op.execute(
        "ALTER SEQUENCE alert_admission_attempt_sequence "
        "OWNED BY alert_rules.last_admission_sequence"
    )
    op.create_table(
        "alert_rule_versions",
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
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", Integer, nullable=False),
        sa.Column("family", String(50), nullable=False),
        sa.Column("metric", String(60), nullable=False),
        sa.Column("severity", String(20), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("definition_payload", LargeBinary, nullable=False),
        sa.Column("schedule_kind", String(12), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_seconds", Integer, nullable=True),
        sa.Column("daily_minute", Integer, nullable=True),
        sa.Column("cooldown_seconds", Integer, nullable=False),
        _owned("alert_rule_versions"),
        _account("alert_rule_versions"),
        _account_parent("alert_rule_versions", "rule_id", "alert_rules"),
        UniqueConstraint("rule_id", "version_number", name="uq_alert_version_number"),
        UniqueConstraint("owner_id", "rule_id", "id", name="uq_alert_version_rule_id"),
        CheckConstraint("version_number >= 1", name="version_positive"),
        CheckConstraint(
            "family IN ('target_drift','group_drift','holding_drift','concentration','effective_company_concentration','etf_overlap','cash_threshold','stale_data','missing_coverage','reconciliation_failure','provider_failure','failed_refresh','dividend_received','unusual_activity','report_outcome')",
            name="family_allowed",
        ),
        CheckConstraint(
            "metric IN ('portfolio_l1_drift','group_absolute_drift','holding_absolute_drift','direct_max_weight','direct_top_n_weight','direct_hhi','effective_entity_weight','effective_top_n_weight','effective_hhi','etf_pair_overlap','portfolio_duplicated_exposure','cash_amount','cash_weight','source_age_seconds','source_missing_sessions','missing_count','missing_fraction','reconciliation_failed','reconciliation_discrepancy_count','provider_failed','provider_consecutive_failures','refresh_failed','positive_dividend','absolute_external_flow_amount','activity_count','unclassified_activity','report_terminal')",
            name="metric_allowed",
        ),
        CheckConstraint("severity IN ('info','warning','critical')", name="severity_allowed"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "octet_length(definition_payload) BETWEEN 1 AND 65536", name="definition_bound"
        ),
        CheckConstraint("cooldown_seconds BETWEEN 0 AND 604800", name="cooldown_bound"),
        CheckConstraint("schedule_kind IN ('interval','daily_utc')", name="schedule_kind"),
        CheckConstraint(
            "(schedule_kind='interval' AND anchor_at IS NOT NULL AND interval_seconds BETWEEN 300 AND 86400 AND daily_minute IS NULL) OR (schedule_kind='daily_utc' AND anchor_at IS NULL AND interval_seconds IS NULL AND daily_minute BETWEEN 0 AND 1439)",
            name="schedule_shape",
        ),
    )
    op.create_table(
        "alert_rule_events",
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
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", BigInteger, nullable=False),
        sa.Column("kind", String(24), nullable=False),
        sa.Column("lifecycle", String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_frontier", sa.DateTime(timezone=True), nullable=True),
        _owned("alert_rule_events"),
        _account("alert_rule_events"),
        _account_parent("alert_rule_events", "rule_id", "alert_rules"),
        _account_parent("alert_rule_events", "version_id", "alert_rule_versions"),
        _parent("alert_rule_events", "principal_id", "principals"),
        UniqueConstraint("rule_id", "sequence", name="uq_alert_rule_event_sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "kind IN ('created','version_created','activated','resumed','paused','archived','superseded')",
            name="kind_allowed",
        ),
        CheckConstraint(f"lifecycle IN ({ALERT_LIFECYCLES})", name="lifecycle_allowed"),
        Index("ix_alert_rule_events_asof", "owner_id", "rule_id", "occurred_at", "sequence"),
    )
    op.create_table(
        "alert_input_snapshots",
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
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_intent", String(16), nullable=False),
        sa.Column("input_digest", String(64), nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("payload", LargeBinary, nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        _owned("alert_input_snapshots"),
        _account("alert_input_snapshots"),
        _account_parent("alert_input_snapshots", "rule_version_id", "alert_rule_versions"),
        UniqueConstraint("rule_version_id", "scheduled_for", name="uq_alert_input_slot"),
        CheckConstraint("execution_intent IN ('live','observe_only')", name="intent_allowed"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("byte_length BETWEEN 1 AND 2097152", name="byte_bound"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        CheckConstraint("source_cutoff_at=scheduled_for", name="slot_cutoff"),
        CheckConstraint("expires_at <= created_at + interval '90 days'", name="expiry_bound"),
        Index("ix_alert_inputs_expiry", "owner_id", "expires_at", "id"),
    )
    op.create_table(
        "alert_evaluation_jobs",
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
        sa.Column("state", String(20), nullable=False),
        sa.Column("failure_code", String(40), nullable=True),
        sa.Column("consumer_attempts", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("consumer_id", String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("input_digest", String(64), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_intent", String(16), nullable=False),
        sa.Column("lifecycle_sequence", BigInteger, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_by_event_id", sa.Uuid(), nullable=True),
        *_job("alert_evaluation_jobs"),
        _account_parent("alert_evaluation_jobs", "rule_id", "alert_rules"),
        _account_parent("alert_evaluation_jobs", "rule_version_id", "alert_rule_versions"),
        _account_parent("alert_evaluation_jobs", "input_id", "alert_input_snapshots"),
        _account_parent("alert_evaluation_jobs", "cancelled_by_event_id", "alert_rule_events"),
        UniqueConstraint("rule_version_id", "scheduled_for", name="uq_alert_evaluation_slot"),
        UniqueConstraint("input_id", name="uq_alert_job_input"),
        CheckConstraint("execution_intent IN ('live','observe_only')", name="intent_allowed"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("lifecycle_sequence >= 1", name="lifecycle_sequence_positive"),
        Index(
            "ix_alert_jobs_predecessor",
            "rule_version_id",
            "execution_intent",
            "scheduled_for",
            "state",
        ),
    )
    op.create_table(
        "alert_evaluation_outbox",
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
        sa.Column("schema_version", String(10), nullable=False),
        sa.Column("state", String(16), nullable=False),
        sa.Column("publication_attempts", Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("dispatcher_id", String(120), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", String(40), nullable=True),
        *_outbox("alert_evaluation_outbox", "alert_evaluation_jobs", "alerts.evaluate.v1"),
    )
    op.create_table(
        "alert_evaluations",
        sa.Column("publication_fence", BigInteger, nullable=False),
        CheckConstraint("publication_fence > 0", name="publication_fence_positive"),
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
        sa.Column("input_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("input_digest", String(64), nullable=False),
        sa.Column("method_name", String(40), nullable=False),
        sa.Column("method_version", String(16), nullable=False),
        sa.Column("outcome", String(16), nullable=False),
        sa.Column("decision", Boolean, nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("byte_length", Integer, nullable=False),
        sa.Column("payload", LargeBinary, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        _owned("alert_evaluations"),
        _account("alert_evaluations"),
        _account_parent("alert_evaluations", "job_id", "alert_evaluation_jobs"),
        _account_parent("alert_evaluations", "input_id", "alert_input_snapshots"),
        _account_parent("alert_evaluations", "rule_version_id", "alert_rule_versions"),
        UniqueConstraint("job_id", name="uq_alert_evaluation_job"),
        UniqueConstraint(
            "rule_version_id",
            "input_digest",
            "method_version",
            name="uq_alert_evaluation_method_input",
        ),
        CheckConstraint(
            "outcome IN ('matched','not_matched','suppressed','unavailable','failed')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            "method_name='alert_evaluation_v1' AND method_version='1.0.0'", name="method_allowed"
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint("byte_length BETWEEN 1 AND 2097152", name="byte_bound"),
        CheckConstraint(
            "payload IS NULL OR octet_length(payload)=byte_length", name="payload_length"
        ),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        Index("ix_alert_evaluations_asof", "owner_id", "account_id", "evaluated_at", "id"),
    )
    op.create_table(
        "alert_conditions",
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
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("last_applied_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_payload", LargeBinary, nullable=False),
        _owned("alert_conditions"),
        _account("alert_conditions"),
        _account_parent("alert_conditions", "rule_version_id", "alert_rule_versions"),
        UniqueConstraint("rule_version_id", name="uq_alert_condition_version"),
        CheckConstraint("octet_length(state_payload) BETWEEN 1 AND 65536", name="state_bound"),
    )
    op.create_table(
        "alert_events",
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
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("dedup_digest", String(64), nullable=False),
        sa.Column("episode_key", String(200), nullable=True),
        sa.Column("episode_ordinal", Integer, nullable=True),
        sa.Column("event_identity", sa.Uuid(), nullable=True),
        sa.Column("event_revision_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family", String(50), nullable=False),
        sa.Column("severity", String(20), nullable=False),
        sa.Column("state", String(12), nullable=False),
        sa.Column("revision", BigInteger, nullable=False),
        sa.Column("notification_state", String(40), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", String(40), nullable=True),
        sa.Column("correction_of_id", sa.Uuid(), nullable=True),
        sa.Column("payload", LargeBinary, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        _owned("alert_events"),
        _account("alert_events"),
        _account_parent("alert_events", "rule_id", "alert_rules"),
        _account_parent("alert_events", "rule_version_id", "alert_rule_versions"),
        _account_parent("alert_events", "evaluation_id", "alert_evaluations"),
        _account_parent("alert_events", "correction_of_id", "alert_events"),
        UniqueConstraint("rule_version_id", "dedup_digest", name="uq_alert_event_identity"),
        CheckConstraint("dedup_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("state IN ('open','resolved')", name="state_allowed"),
        CheckConstraint(
            "notification_state IN ('eligible','suppressed_cooldown','external_delivery_unavailable')",
            name="notification_allowed",
        ),
        CheckConstraint("payload IS NULL OR octet_length(payload)<=2097152", name="payload_bound"),
        CheckConstraint("(purged_at IS NULL) = (payload IS NOT NULL)", name="payload_state"),
        Index("ix_alert_events_feed", "owner_id", "account_id", "opened_at", "id"),
    )
    op.create_table(
        "alert_event_transitions",
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
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("principal_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", BigInteger, nullable=False),
        sa.Column("kind", String(16), nullable=False),
        sa.Column("reason", String(40), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", String(1000), nullable=True),
        CheckConstraint("note IS NULL OR length(note)<=1000", name="note_bound"),
        _owned("alert_event_transitions"),
        _account("alert_event_transitions"),
        _account_parent("alert_event_transitions", "event_id", "alert_events"),
        _account_parent("alert_event_transitions", "evaluation_id", "alert_evaluations"),
        _parent("alert_event_transitions", "principal_id", "principals"),
        UniqueConstraint("event_id", "sequence", name="uq_alert_event_transition_sequence"),
        CheckConstraint(
            "kind IN ('opened','acknowledged','resolved','reopened','observed')",
            name="kind_allowed",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        Index("ix_alert_event_transitions_asof", "owner_id", "event_id", "occurred_at", "sequence"),
    )
    op.create_table(
        "alert_command_identities",
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
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("resulting_revision", BigInteger, nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        _owned("alert_command_identities"),
        _account("alert_command_identities"),
        _account_parent("alert_command_identities", "rule_id", "alert_rules"),
        _account_parent("alert_command_identities", "event_id", "alert_events"),
        UniqueConstraint("owner_id", "command", "idempotency_key", name="uq_alert_command_key"),
        CheckConstraint(
            "command IN ('create_rule','create_rule_version','activate_rule','pause_rule','archive_rule','acknowledge_event','resolve_event','backfill')",
            name="command_allowed",
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,180}$'", name="key_format"),
        CheckConstraint("command_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("num_nonnulls(rule_id,event_id)=1", name="parent_xor"),
    )
    op.create_table(
        "alert_acknowledgments",
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
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", String(1000), nullable=True),
        _owned("alert_acknowledgments"),
        _account("alert_acknowledgments"),
        _account_parent("alert_acknowledgments", "event_id", "alert_events"),
        _account_parent("alert_acknowledgments", "command_id", "alert_command_identities"),
        _parent("alert_acknowledgments", "principal_id", "principals"),
        UniqueConstraint("command_id", name="uq_alert_ack_command"),
        CheckConstraint("note IS NULL OR length(note)<=1000", name="note_bound"),
    )
    op.create_table(
        "in_app_notifications",
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
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("eligibility", String(40), nullable=False),
        _owned("in_app_notifications"),
        _account("in_app_notifications"),
        _account_parent("in_app_notifications", "event_id", "alert_events"),
        UniqueConstraint("owner_id", "event_id", name="uq_in_app_notification_event"),
    )
    op.create_table(
        "notification_destinations",
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
        sa.Column("configuration_key", String(120), nullable=False),
        sa.Column("state", String(20), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        _owned("notification_destinations"),
        _account("notification_destinations"),
        UniqueConstraint(
            "owner_id", "account_id", "configuration_key", name="uq_notification_destination_config"
        ),
        CheckConstraint("state IN ('configured','unavailable','disabled')", name="state_allowed"),
    )
    op.create_table(
        "notification_destination_versions",
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
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", Integer, nullable=False),
        sa.Column("channel", String(12), nullable=False),
        sa.Column("label", String(120), nullable=False),
        sa.Column("configuration_key", String(120), nullable=False),
        sa.Column("secret_reference", String(200), nullable=True),
        sa.Column("content_digest", String(64), nullable=False),
        _owned("notification_destination_versions"),
        _account("notification_destination_versions"),
        _account_parent(
            "notification_destination_versions", "destination_id", "notification_destinations"
        ),
        UniqueConstraint(
            "destination_id", "version_number", name="uq_notification_destination_version"
        ),
        UniqueConstraint("owner_id", "destination_id", "id", name="uq_destination_version_parent"),
        CheckConstraint("channel IN ('in_app','email','webhook')", name="channel_allowed"),
        CheckConstraint(
            "version_number>=1 AND length(label) BETWEEN 1 AND 120", name="version_label_bound"
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    op.create_table(
        "notification_delivery_jobs",
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
        sa.Column("state", String(20), nullable=False),
        sa.Column("failure_code", String(40), nullable=True),
        sa.Column("consumer_attempts", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("consumer_id", String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("destination_version_id", sa.Uuid(), nullable=False),
        sa.Column("channel", String(12), nullable=False),
        sa.Column("payload_digest", String(64), nullable=False),
        sa.Column("payload", LargeBinary, nullable=False),
        *_job("notification_delivery_jobs"),
        _account_parent("notification_delivery_jobs", "event_id", "alert_events"),
        _account_parent(
            "notification_delivery_jobs",
            "destination_version_id",
            "notification_destination_versions",
        ),
        UniqueConstraint(
            "event_id",
            "destination_version_id",
            "payload_digest",
            name="uq_notification_delivery_identity",
        ),
        CheckConstraint("channel IN ('email','webhook')", name="channel_allowed"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("octet_length(payload) BETWEEN 1 AND 65536", name="payload_bound"),
    )
    op.create_table(
        "notification_delivery_outbox",
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
        sa.Column("schema_version", String(10), nullable=False),
        sa.Column("state", String(16), nullable=False),
        sa.Column("publication_attempts", Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("dispatcher_id", String(120), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", String(40), nullable=True),
        *_outbox(
            "notification_delivery_outbox", "notification_delivery_jobs", "notifications.deliver.v1"
        ),
    )
    op.create_table(
        "alert_evaluation_attempts",
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
        sa.Column("phase", String(12), nullable=False),
        sa.Column("attempt", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("outcome", String(16), nullable=False),
        sa.Column("failure_code", String(40), nullable=True),
        *_attempt("alert_evaluation_attempts", "alert_evaluation_jobs"),
    )
    op.create_table(
        "notification_delivery_attempts",
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
        sa.Column("phase", String(12), nullable=False),
        sa.Column("attempt", Integer, nullable=False),
        sa.Column("fence", BigInteger, nullable=False),
        sa.Column("outcome", String(16), nullable=False),
        sa.Column("failure_code", String(40), nullable=True),
        *_attempt("notification_delivery_attempts", "notification_delivery_jobs"),
    )
    op.create_table(
        "alert_retention_work",
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
        sa.Column("reason", String(12), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _owned("alert_retention_work"),
        _parent("alert_retention_work", "input_id", "alert_input_snapshots"),
        UniqueConstraint("input_id", name="uq_alert_retention_input"),
        CheckConstraint("reason IN ('ttl','source','owner')", name="reason_allowed"),
    )
    op.create_table(
        "alert_input_dependencies",
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
        _owned("alert_input_dependencies"),
        _parent("alert_input_dependencies", "input_id", "alert_input_snapshots"),
        UniqueConstraint("input_id", "source_key", name="uq_alert_dependencies_source"),
        _parent("alert_input_dependencies", "license_version_id", "provider_license_versions"),
        _parent("alert_input_dependencies", "provider_id", "market_data_providers"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_alert_dependencies_provider_license",
            ondelete="RESTRICT",
        ),
        _parent("alert_input_dependencies", "price_snapshot_id", "price_snapshots"),
        _parent("alert_input_dependencies", "fx_snapshot_id", "fx_snapshots"),
        _parent("alert_input_dependencies", "benchmark_snapshot_id", "benchmark_snapshots"),
        _parent(
            "alert_input_dependencies", "corporate_action_snapshot_id", "corporate_action_snapshots"
        ),
        _parent(
            "alert_input_dependencies", "classification_snapshot_id", "classification_snapshots"
        ),
        _parent("alert_input_dependencies", "constituent_snapshot_id", "constituent_snapshots"),
        _parent(
            "alert_input_dependencies", "entity_evidence_version_id", "entity_evidence_versions"
        ),
        _parent("alert_input_dependencies", "fund_definition_id", "fund_definitions"),
        _parent("alert_input_dependencies", "fund_mapping_id", "fund_source_mappings"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "num_nonnulls(price_snapshot_id,fx_snapshot_id,benchmark_snapshot_id,corporate_action_snapshot_id,classification_snapshot_id,constituent_snapshot_id,entity_evidence_version_id,fund_definition_id,fund_mapping_id) = 1",
            name="physical_parent_xor",
        ),
        CheckConstraint(
            "COALESCE((kind='price' AND source_id=price_snapshot_id) OR (kind='fx' AND source_id=fx_snapshot_id) OR (kind='benchmark' AND source_id=benchmark_snapshot_id) OR (kind='corporate_action' AND source_id=corporate_action_snapshot_id) OR (kind='classification' AND source_id=classification_snapshot_id) OR (kind='constituent' AND source_id=constituent_snapshot_id) OR (kind='entity_evidence' AND source_id=entity_evidence_version_id) OR (kind='fund_definition' AND source_id=fund_definition_id) OR (kind='fund_mapping' AND source_id=fund_mapping_id),false)",
            name="source_kind",
        ),
        Index("ix_alert_dependencies_input", "owner_id", "input_id", "id"),
        Index("ix_alert_dependencies_license", "owner_id", "license_version_id", "input_id"),
        Index("ix_alert_dependencies_source", "owner_id", "kind", "source_id", "input_id"),
    )
    op.create_table(
        "alert_input_licenses",
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
        _owned("alert_input_licenses"),
        _parent("alert_input_licenses", "input_id", "alert_input_snapshots"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_alert_input_licenses_provider_license",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("input_id", "license_version_id", name="uq_alert_input_license"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_alert_licenses_input", "owner_id", "input_id", "id"),
    )
    op.create_table(
        "provider_invocation_observations",
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
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("observed_sequence", BigInteger, Identity(), nullable=False),
        sa.Column("capability", String(40), nullable=False),
        sa.Column("adapter_version", String(120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", String(20), nullable=False),
        sa.Column("failure_code", String(40), nullable=True),
        UniqueConstraint("owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id"],
            ["market_data_providers.owner_id", "market_data_providers.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("observed_sequence"),
        CheckConstraint(f"capability IN ({PROVIDER_CAPABILITIES})", name="capability_allowed"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({PROVIDER_FAILURES})", name="failure_allowed"
        ),
        CheckConstraint(
            "started_at <= completed_at AND completed_at <= first_known_at", name="chronology"
        ),
        CheckConstraint("outcome IN ('succeeded','failed','unavailable')", name="outcome_allowed"),
        CheckConstraint("(outcome='succeeded') = (failure_code IS NULL)", name="success_state"),
        CheckConstraint(
            "(outcome='unavailable') = (failure_code IN ('not_configured','unsupported','license_denied')) OR failure_code IS NULL",
            name="unavailable_state",
        ),
        Index(
            "ix_provider_invocation_cutoff",
            "owner_id",
            "provider_id",
            "completed_at",
            "observed_sequence",
        ),
    )
    op.create_foreign_key(
        "fk_alert_rules_latest_version_id",
        "alert_rules",
        "alert_rule_versions",
        ["owner_id", "id", "latest_version_id"],
        ["owner_id", "rule_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_alert_rules_active_version_id",
        "alert_rules",
        "alert_rule_versions",
        ["owner_id", "id", "active_version_id"],
        ["owner_id", "rule_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_destination_current_version",
        "notification_destinations",
        "notification_destination_versions",
        ["owner_id", "id", "current_version_id"],
        ["owner_id", "destination_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "activity_revision_evidence",
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
            "broker_account_id",
            sa.Uuid(),
            ForeignKey("broker_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.Uuid(),
            ForeignKey("principals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "new_source_record_id",
            sa.Uuid(),
            ForeignKey("source_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "superseded_source_record_id",
            sa.Uuid(),
            ForeignKey("source_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("authority", String(30), nullable=False),
        sa.Column("evidence_key", String(120), nullable=False),
        sa.Column("economic_key", String(255), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_digest", String(64), nullable=False),
        sa.Column("request_digest", String(64), nullable=False),
        sa.Column("idempotency_key", String(180), nullable=False),
        UniqueConstraint("owner_id", "id"),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_activity_revision_evidence_command"
        ),
        UniqueConstraint(
            "owner_id", "new_source_record_id", name="uq_activity_revision_evidence_new_source"
        ),
        CheckConstraint(
            "new_source_record_id <> superseded_source_record_id", name="different_sources"
        ),
        CheckConstraint(
            "authority IN ('owner_attestation','provider_evidence')", name="authority_allowed"
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint("length(evidence_key) BETWEEN 1 AND 120", name="evidence_key_bound"),
        Index(
            "ix_activity_revision_knowledge",
            "owner_id",
            "broker_account_id",
            "first_observed_at",
            "id",
        ),
    )
    op.add_column(
        "historical_dependencies",
        sa.Column("activity_revision_evidence_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_historical_dependencies_owner_id_activity_revision_evidence"),
        "historical_dependencies",
        "activity_revision_evidence",
        ["owner_id", "activity_revision_evidence_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f("ck_historical_dependencies_source_xor"), "historical_dependencies", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_historical_dependencies_source_xor"),
        "historical_dependencies",
        "num_nonnulls(ingestion_run_id,source_record_id,source_occurrence_id,portfolio_snapshot_id,calculation_run_id,reconciliation_run_id,price_snapshot_id,fx_snapshot_id,action_snapshot_id,benchmark_snapshot_id,mapping_id,calendar_id,license_version_id,benchmark_version_id,target_version_id,classification_id,registered_evidence_id,activity_revision_evidence_id)=1",
    )
    _guards()


def downgrade() -> None:
    _drop_guards()
    op.drop_constraint(
        op.f("fk_historical_dependencies_owner_id_activity_revision_evidence"),
        "historical_dependencies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_historical_dependencies_source_xor"), "historical_dependencies", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_historical_dependencies_source_xor"),
        "historical_dependencies",
        "num_nonnulls(ingestion_run_id,source_record_id,source_occurrence_id,portfolio_snapshot_id,calculation_run_id,reconciliation_run_id,price_snapshot_id,fx_snapshot_id,action_snapshot_id,benchmark_snapshot_id,mapping_id,calendar_id,license_version_id,benchmark_version_id,target_version_id,classification_id,registered_evidence_id)=1",
    )
    op.drop_column("historical_dependencies", "activity_revision_evidence_id")
    op.drop_table("activity_revision_evidence")
    op.drop_constraint("fk_alert_rules_latest_version_id", "alert_rules", type_="foreignkey")
    op.drop_constraint("fk_alert_rules_active_version_id", "alert_rules", type_="foreignkey")
    op.drop_constraint(
        "fk_destination_current_version", "notification_destinations", type_="foreignkey"
    )
    op.drop_table("provider_invocation_observations")
    op.drop_table("alert_input_licenses")
    op.drop_table("alert_input_dependencies")
    op.drop_table("alert_retention_work")
    op.drop_table("notification_delivery_attempts")
    op.drop_table("alert_evaluation_attempts")
    op.drop_table("notification_delivery_outbox")
    op.drop_table("notification_delivery_jobs")
    op.drop_table("notification_destination_versions")
    op.drop_table("notification_destinations")
    op.drop_table("in_app_notifications")
    op.drop_table("alert_acknowledgments")
    op.drop_table("alert_command_identities")
    op.drop_table("alert_event_transitions")
    op.drop_table("alert_events")
    op.drop_table("alert_conditions")
    op.drop_table("alert_evaluations")
    op.drop_table("alert_evaluation_outbox")
    op.drop_table("alert_evaluation_jobs")
    op.drop_table("alert_input_snapshots")
    op.drop_table("alert_rule_events")
    op.drop_table("alert_rule_versions")
    op.drop_table("alert_rules")
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
    op.drop_constraint(
        op.f("ck_principal_scope_grants_scope_allowed"), "principal_scope_grants", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_principal_scope_grants_scope_allowed"),
        "principal_scope_grants",
        "scope IN ('portfolio:read','activity:read','analytics:read','portfolio:refresh','configuration:read','targets:read','targets:write','plans:write','reports:read','reports:write')",
    )


_IMMUTABLE = (
    "alert_rule_versions",
    "alert_rule_events",
    "alert_input_dependencies",
    "alert_input_licenses",
    "alert_event_transitions",
    "alert_command_identities",
    "alert_acknowledgments",
    "in_app_notifications",
    "notification_destination_versions",
    "alert_evaluation_attempts",
    "notification_delivery_attempts",
    "provider_invocation_observations",
    "activity_revision_evidence",
)
_PAYLOADS = ("alert_input_snapshots", "alert_evaluations", "alert_events")
_MUTABLE = {
    "alert_rules": "name,lifecycle,revision,lifecycle_sequence,latest_version_id,active_version_id,next_scheduled_for,last_admission_sequence,updated_at,principal_id",
    "alert_conditions": "state_payload,last_applied_scheduled_for",
    "notification_destinations": "state,current_version_id",
}
_JOBS = ("alert_evaluation_jobs", "notification_delivery_jobs")
_OUTBOXES = ("alert_evaluation_outbox", "notification_delivery_outbox")


def _guards() -> None:
    op.execute(ALERT_GUARDS)
    for table in _IMMUTABLE:
        op.execute(
            f"CREATE TRIGGER alert_owned BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION alert_owned_guard('')"
        )
    for table, columns in _MUTABLE.items():
        op.execute(
            f"CREATE TRIGGER alert_owned BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION alert_owned_guard('{columns}')"
        )
    for table in _PAYLOADS:
        op.execute(
            f"CREATE TRIGGER alert_payload BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION alert_payload_guard()"
        )
    for table in _JOBS:
        op.execute(
            f"CREATE TRIGGER alert_job BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION alert_job_guard()"
        )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER alert_job_complete AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION alert_job_complete()"
        )
    for table in _OUTBOXES:
        op.execute(
            f"CREATE TRIGGER alert_outbox BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION alert_outbox_guard()"
        )
    op.execute(
        "CREATE CONSTRAINT TRIGGER alert_capture_complete AFTER INSERT OR UPDATE ON alert_input_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION alert_capture_complete()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER alert_result_complete AFTER INSERT ON alert_evaluations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION alert_result_complete()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER alert_event_complete AFTER INSERT ON alert_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION alert_event_complete()"
    )
    op.execute(
        "CREATE TRIGGER alert_retention BEFORE INSERT OR UPDATE OR DELETE ON alert_retention_work FOR EACH ROW EXECUTE FUNCTION alert_retention_guard()"
    )
    for table in (
        "source_retention_work",
        "source_expiry_events",
        "enrichment_retention_work",
        "enrichment_expiry_events",
    ):
        op.execute(
            f"CREATE TRIGGER alert_source_copies BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION alert_source_copy_guard()"
        )


def _drop_guards() -> None:
    for table in (*_IMMUTABLE, *_MUTABLE):
        op.execute(f"DROP TRIGGER alert_owned ON {table}")
    for table in _PAYLOADS:
        op.execute(f"DROP TRIGGER alert_payload ON {table}")
    for table in _JOBS:
        op.execute(f"DROP TRIGGER alert_job ON {table}")
        op.execute(f"DROP TRIGGER alert_job_complete ON {table}")
    for table in _OUTBOXES:
        op.execute(f"DROP TRIGGER alert_outbox ON {table}")
    for trigger, table in (
        ("alert_capture_complete", "alert_input_snapshots"),
        ("alert_result_complete", "alert_evaluations"),
        ("alert_event_complete", "alert_events"),
        ("alert_retention", "alert_retention_work"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    for table in (
        "source_retention_work",
        "source_expiry_events",
        "enrichment_retention_work",
        "enrichment_expiry_events",
    ):
        op.execute(f"DROP TRIGGER alert_source_copies ON {table}")
    for name in (
        "alert_source_copy_guard",
        "alert_retention_guard",
        "alert_event_complete",
        "alert_result_complete",
        "alert_capture_complete",
        "alert_outbox_guard",
        "alert_job_complete",
        "alert_job_guard",
        "alert_payload_guard",
        "alert_owned_guard",
    ):
        op.execute(f"DROP FUNCTION {name}()")
    op.execute("DROP FUNCTION alert_sources_permit(uuid,uuid)")
    op.execute("DROP FUNCTION alert_capture_pending(uuid,uuid)")


ALERT_GUARDS = r"""
CREATE FUNCTION alert_capture_pending(p_owner uuid,p_input uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM alert_input_snapshots WHERE owner_id=p_owner AND id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM alert_evaluations WHERE owner_id=p_owner AND input_id=p_input AND payload IS NOT NULL)
 OR EXISTS (SELECT 1 FROM alert_events e JOIN alert_evaluations a ON a.id=e.evaluation_id AND a.owner_id=e.owner_id
   WHERE a.owner_id=p_owner AND a.input_id=p_input AND e.payload IS NOT NULL)
$$;

CREATE FUNCTION alert_sources_permit(p_owner uuid,p_input uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT EXISTS (
  SELECT 1 FROM alert_input_licenses d
  LEFT JOIN provider_license_versions p ON p.id=d.license_version_id AND p.owner_id=d.owner_id AND p.provider_id=d.provider_id
  LEFT JOIN LATERAL (SELECT l.* FROM provider_license_versions l WHERE l.owner_id=d.owner_id AND l.provider_id=d.provider_id AND l.effective_at<=CURRENT_TIMESTAMP
   ORDER BY l.effective_at DESC,l.version_number DESC,l.id DESC LIMIT 1) c ON true
  WHERE d.owner_id=p_owner AND d.input_id=p_input AND (p.id IS NULL OR c.id IS NULL OR p.effective_at>CURRENT_TIMESTAMP
   OR p.store_permission<>'allowed' OR p.display_permission<>'allowed' OR c.store_permission<>'allowed' OR c.display_permission<>'allowed'))
 AND NOT EXISTS (SELECT 1 FROM alert_input_dependencies d WHERE d.owner_id=p_owner AND d.input_id=p_input AND (
  d.expires_at<=CURRENT_TIMESTAMP OR NOT EXISTS (SELECT 1 FROM alert_input_licenses l WHERE l.owner_id=d.owner_id AND l.input_id=d.input_id AND l.license_version_id=d.license_version_id)
  OR EXISTS (SELECT 1 FROM source_retention_work w WHERE w.owner_id=d.owner_id AND
   (w.price_snapshot_id=d.price_snapshot_id OR w.fx_snapshot_id=d.fx_snapshot_id OR w.benchmark_snapshot_id=d.benchmark_snapshot_id OR w.corporate_action_snapshot_id=d.corporate_action_snapshot_id OR w.constituent_snapshot_id=d.constituent_snapshot_id))
  OR EXISTS (SELECT 1 FROM enrichment_retention_work w WHERE w.owner_id=d.owner_id AND
   (w.entity_evidence_version_id=d.entity_evidence_version_id OR w.classification_snapshot_id=d.classification_snapshot_id OR w.fund_definition_id=d.fund_definition_id OR w.fund_mapping_id=d.fund_mapping_id))))
$$;

CREATE FUNCTION alert_owned_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb; o jsonb; allowed text[]:=string_to_array(TG_ARGV[0],','); inp alert_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Alert canonical records are immutable' USING ERRCODE='23514'; END IF;
 v:=to_jsonb(NEW);
 IF v ? 'account_id' AND NOT report_account_scope(NEW.owner_id,(v->>'account_id')::uuid) THEN RAISE EXCEPTION 'Alert account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  o:=to_jsonb(OLD);
  IF v-allowed IS DISTINCT FROM o-allowed THEN RAISE EXCEPTION 'Alert immutable identity changed' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='alert_rules' THEN
   IF OLD.last_admission_sequence IS NOT NULL AND (NEW.last_admission_sequence IS NULL OR NEW.last_admission_sequence<OLD.last_admission_sequence) THEN RAISE EXCEPTION 'Alert admission order cannot move backwards' USING ERRCODE='23514'; END IF;
   IF NEW.revision<OLD.revision OR NEW.revision>OLD.revision+1 OR NEW.lifecycle_sequence<OLD.lifecycle_sequence OR NEW.lifecycle_sequence>OLD.lifecycle_sequence+1 THEN RAISE EXCEPTION 'Alert lifecycle revision is not monotonic' USING ERRCODE='23514'; END IF;
   IF OLD.lifecycle='archived' AND NEW.lifecycle<>'archived' THEN RAISE EXCEPTION 'Archived alert cannot restart' USING ERRCODE='23514'; END IF;
   IF NEW.lifecycle IS DISTINCT FROM OLD.lifecycle OR NEW.active_version_id IS DISTINCT FROM OLD.active_version_id THEN
    IF NEW.revision<>OLD.revision+1 OR NEW.lifecycle_sequence<>OLD.lifecycle_sequence+1 THEN RAISE EXCEPTION 'Alert lifecycle transition requires a fence' USING ERRCODE='23514'; END IF;
   END IF;
  ELSIF TG_TABLE_NAME='alert_conditions' THEN
   IF OLD.last_applied_scheduled_for IS NOT NULL AND (NEW.last_applied_scheduled_for IS NULL OR NEW.last_applied_scheduled_for<OLD.last_applied_scheduled_for) THEN RAISE EXCEPTION 'Alert condition cannot move backwards' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='activity_revision_evidence' THEN
  IF NOT report_account_scope(NEW.owner_id,NEW.broker_account_id)
   OR NOT EXISTS(SELECT 1 FROM principals WHERE id=NEW.principal_id AND owner_id=NEW.owner_id AND status='active')
   OR NEW.first_observed_at IS DISTINCT FROM NEW.created_at
   OR NOT EXISTS(SELECT 1 FROM source_records WHERE id=NEW.new_source_record_id AND broker_account_id=NEW.broker_account_id AND observed_at<=NEW.first_observed_at)
   OR NOT EXISTS(SELECT 1 FROM source_records WHERE id=NEW.superseded_source_record_id AND broker_account_id=NEW.broker_account_id AND observed_at<=NEW.first_observed_at)
  THEN RAISE EXCEPTION 'Activity revision source or authority mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('alert_input_dependencies','alert_input_licenses') THEN
  SELECT * INTO inp FROM alert_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
  IF NOT FOUND OR inp.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Alert source projection must precede seal' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_payload_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb; o jsonb; inp uuid; j alert_evaluation_jobs; allowed text[];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Alert payload tombstones are immutable' USING ERRCODE='23514'; END IF;
 v:=to_jsonb(NEW);
 IF NOT report_account_scope(NEW.owner_id,NEW.account_id) THEN RAISE EXCEPTION 'Alert account mismatch' USING ERRCODE='23514'; END IF;
 inp:=CASE TG_TABLE_NAME WHEN 'alert_input_snapshots' THEN NEW.id WHEN 'alert_evaluations' THEN (v->>'input_id')::uuid ELSE (SELECT input_id FROM alert_evaluations WHERE id=(v->>'evaluation_id')::uuid) END;
 IF TG_OP='UPDATE' THEN
  o:=to_jsonb(OLD);
  allowed:=ARRAY['payload','purged_at'];
  IF TG_TABLE_NAME='alert_input_snapshots' AND o->>'sealed_at' IS NULL THEN allowed:=allowed||ARRAY['sealed_at','expires_at']; END IF;
  IF TG_TABLE_NAME='alert_events' THEN allowed:=allowed||ARRAY['state','revision','updated_at','resolved_at','resolution_reason','notification_state']; END IF;
  IF v-allowed IS DISTINCT FROM o-allowed THEN RAISE EXCEPTION 'Alert canonical identity changed' USING ERRCODE='23514'; END IF;
  IF NEW.payload IS DISTINCT FROM OLD.payload OR NEW.purged_at IS DISTINCT FROM OLD.purged_at THEN
   IF NEW.payload IS NOT NULL OR OLD.payload IS NULL OR NEW.purged_at IS NULL OR NOT EXISTS (SELECT 1 FROM alert_retention_work WHERE owner_id=NEW.owner_id AND input_id=inp AND completed_at IS NULL) THEN RAISE EXCEPTION 'Alert purge is not authorized' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='alert_events' THEN
   IF NEW.revision<OLD.revision OR NEW.revision>OLD.revision+1 OR (OLD.state='resolved' AND NEW.state<>'resolved') THEN RAISE EXCEPTION 'Alert event transition is invalid' USING ERRCODE='23514'; END IF;
   IF NEW.notification_state<>OLD.notification_state AND EXISTS(SELECT 1 FROM in_app_notifications WHERE event_id=NEW.id) THEN RAISE EXCEPTION 'Published notification eligibility is immutable' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF NEW.payload IS NOT NULL AND TG_TABLE_NAME='alert_input_snapshots' AND encode(sha256(NEW.payload),'hex')<>(v->>'input_digest') THEN RAISE EXCEPTION 'Alert input digest mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.payload IS NOT NULL AND TG_TABLE_NAME='alert_evaluations' THEN
  IF encode(sha256(NEW.payload),'hex')<>(v->>'content_digest') THEN RAISE EXCEPTION 'Alert result digest mismatch' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' THEN
   SELECT * INTO j FROM alert_evaluation_jobs WHERE id=(v->>'job_id')::uuid AND owner_id=NEW.owner_id;
   IF NOT FOUND OR j.state<>'running' OR j.input_id<>inp OR j.input_digest<>(v->>'input_digest') OR j.rule_version_id<>(v->>'rule_version_id')::uuid OR j.scheduled_for<>(v->>'scheduled_for')::timestamptz OR j.fence<>(v->>'publication_fence')::bigint OR NEW.expires_at>j.expires_at OR NOT alert_sources_permit(NEW.owner_id,inp) THEN RAISE EXCEPTION 'Alert result job or source mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb:=to_jsonb(NEW); o jsonb; inp alert_input_snapshots; r alert_rules;
 allowed text[]:=ARRAY['state','completed_at','failure_code','consumer_attempts','fence','lease_id','lease_expires_at','heartbeat_at','consumer_id','available_at','lifecycle_sequence','cancelled_by_event_id'];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Alert jobs are immutable' USING ERRCODE='23514'; END IF;
 IF NOT report_account_scope(NEW.owner_id,NEW.account_id) THEN RAISE EXCEPTION 'Alert job account mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='alert_evaluation_jobs' THEN
  SELECT * INTO inp FROM alert_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id;
  IF NOT FOUND OR inp.account_id<>NEW.account_id OR inp.rule_version_id<>NEW.rule_version_id OR inp.input_digest<>NEW.input_digest OR inp.scheduled_for<>NEW.scheduled_for OR inp.execution_intent<>NEW.execution_intent OR NEW.expires_at>inp.expires_at THEN RAISE EXCEPTION 'Alert job input mismatch' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS (SELECT 1 FROM alert_rule_versions WHERE id=NEW.rule_version_id AND rule_id=NEW.rule_id) THEN RAISE EXCEPTION 'Alert job rule mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.fence<>0 OR NEW.consumer_attempts<>0 OR (NEW.state<>'queued' AND NOT(TG_TABLE_NAME='notification_delivery_jobs' AND NEW.state='failed' AND NEW.failure_code='not_configured')) THEN RAISE EXCEPTION 'Alert job initial state mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  o:=to_jsonb(OLD);
  IF v-allowed IS DISTINCT FROM o-allowed THEN RAISE EXCEPTION 'Alert job pins are immutable' USING ERRCODE='23514'; END IF;
  IF NEW.state='running' AND OLD.state<>'running' AND (OLD.state<>'queued' OR NEW.fence<>OLD.fence+1 OR NEW.consumer_attempts<>OLD.consumer_attempts+1) THEN RAISE EXCEPTION 'Alert claim is not fenced' USING ERRCODE='23514'; END IF;
  IF NEW.state='running' AND OLD.state='running' AND NEW.lease_id IS DISTINCT FROM OLD.lease_id AND (OLD.lease_expires_at>CURRENT_TIMESTAMP OR NEW.fence<>OLD.fence+1 OR NEW.consumer_attempts<>OLD.consumer_attempts+1) THEN RAISE EXCEPTION 'Alert active lease cannot be replaced' USING ERRCODE='23514'; END IF;
  IF NEW.state='running' AND OLD.state='running' AND NEW.lease_id IS NOT DISTINCT FROM OLD.lease_id AND (NEW.fence<>OLD.fence OR NEW.consumer_attempts<>OLD.consumer_attempts OR NEW.consumer_id IS DISTINCT FROM OLD.consumer_id OR v->>'lifecycle_sequence' IS DISTINCT FROM o->>'lifecycle_sequence') THEN RAISE EXCEPTION 'Alert heartbeat changed identity' USING ERRCODE='23514'; END IF;
  IF NEW.state<>'running' AND (NEW.fence<>OLD.fence OR NEW.consumer_attempts<>OLD.consumer_attempts) THEN RAISE EXCEPTION 'Only an alert claim advances attempts' USING ERRCODE='23514'; END IF;
  IF OLD.state IN ('succeeded','failed','expired','cancelled') AND NEW.state<>OLD.state AND NEW.state NOT IN ('expired','cancelled') THEN RAISE EXCEPTION 'Terminal alert cannot restart' USING ERRCODE='23514'; END IF;
  IF NEW.state='succeeded' AND (OLD.state<>'running' OR OLD.lease_expires_at<=CURRENT_TIMESTAMP) THEN RAISE EXCEPTION 'Alert completion lease is stale' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='alert_evaluation_jobs' AND NEW.state IN ('running','succeeded') THEN
  SELECT * INTO r FROM alert_rules WHERE id=NEW.rule_id;
  IF NEW.execution_intent='live' AND (r.lifecycle<>'active' OR r.active_version_id<>NEW.rule_version_id OR r.lifecycle_sequence<>NEW.lifecycle_sequence OR EXISTS(SELECT 1 FROM alert_evaluation_jobs p WHERE p.rule_version_id=NEW.rule_version_id AND p.execution_intent='live' AND p.scheduled_for<NEW.scheduled_for AND p.state IN ('queued','running'))) THEN RAISE EXCEPTION 'Alert chronological lifecycle guard rejected job' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_job_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j jsonb; count_outboxes integer; outboxes text;
BEGIN
 EXECUTE format('SELECT to_jsonb(j) FROM %I j WHERE id=$1',TG_TABLE_NAME) INTO j USING NEW.id;
 outboxes:=CASE TG_TABLE_NAME WHEN 'alert_evaluation_jobs' THEN 'alert_evaluation_outbox' ELSE 'notification_delivery_outbox' END;
 EXECUTE format('SELECT count(*) FROM %I WHERE job_id=$1',outboxes) INTO count_outboxes USING NEW.id;
 IF count_outboxes<>1 THEN RAISE EXCEPTION 'Alert atomic outbox is absent' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='alert_evaluation_jobs' THEN
  IF NOT EXISTS(SELECT 1 FROM alert_input_snapshots WHERE id=(j->>'input_id')::uuid AND sealed_at IS NOT NULL) THEN RAISE EXCEPTION 'Alert capture is unsealed' USING ERRCODE='23514'; END IF;
  IF j->>'state'='succeeded' AND NOT EXISTS(SELECT 1 FROM alert_evaluations WHERE job_id=NEW.id AND publication_fence=(j->>'fence')::bigint AND payload IS NOT NULL) THEN RAISE EXCEPTION 'Alert successful result is absent' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_outbox_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v jsonb; o jsonb; allowed text[]:=ARRAY['state','publication_attempts','available_at','claim_token','dispatcher_id','claim_expires_at','published_at','failure_code'];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Alert dispatch identity is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  v:=to_jsonb(NEW);o:=to_jsonb(OLD);
  IF v-allowed IS DISTINCT FROM o-allowed OR NEW.publication_attempts<OLD.publication_attempts OR NEW.publication_attempts>OLD.publication_attempts+1 THEN RAISE EXCEPTION 'Alert dispatch identity changed' USING ERRCODE='23514'; END IF;
  IF NEW.publication_attempts<>OLD.publication_attempts AND NEW.state<>'claimed' THEN RAISE EXCEPTION 'Only a claim advances publication attempt' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_capture_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp alert_input_snapshots; body jsonb;
BEGIN
 SELECT * INTO inp FROM alert_input_snapshots WHERE id=NEW.id;
 IF inp.payload IS NULL THEN RETURN NEW; END IF;
 IF inp.sealed_at IS NULL OR NOT alert_sources_permit(inp.owner_id,inp.id) THEN RAISE EXCEPTION 'Alert capture is unsealed or restricted' USING ERRCODE='23514'; END IF;
 body:=convert_from(inp.payload,'UTF8')::jsonb;
 IF (body->'version'->>'id')::uuid<>inp.rule_version_id OR (body->>'scheduled_for')::timestamptz<>inp.scheduled_for OR body->>'execution_intent'<>inp.execution_intent THEN RAISE EXCEPTION 'Alert capture header mismatch' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM alert_input_licenses WHERE input_id=inp.id)<>jsonb_array_length(body->'licenses') THEN RAISE EXCEPTION 'Alert license projection incomplete' USING ERRCODE='23514'; END IF;
 IF EXISTS (SELECT 1 FROM jsonb_array_elements(body->'licenses') l WHERE NOT EXISTS (SELECT 1 FROM alert_input_licenses d WHERE d.input_id=inp.id AND d.license_version_id=(l->>'id')::uuid AND d.provider_id=(l->>'provider_id')::uuid)) THEN RAISE EXCEPTION 'Alert license projection mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_result_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM alert_evaluation_jobs WHERE id=NEW.job_id AND state='succeeded' AND fence=NEW.publication_fence) THEN RAISE EXCEPTION 'Alert result must commit with completion' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION alert_event_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM in_app_notifications WHERE event_id=NEW.id) THEN RAISE EXCEPTION 'Alert in-app notification must commit atomically' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

ALERT_GUARDS += r"""
CREATE FUNCTION alert_source_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
   IF EXISTS (SELECT 1 FROM alert_input_dependencies d WHERE d.owner_id=NEW.owner_id
       AND d.kind=family AND d.source_id=identifier AND alert_capture_pending(d.owner_id,d.input_id)) THEN
    RAISE EXCEPTION 'Alert source copies remain' USING ERRCODE='23514';
   END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE FUNCTION alert_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inp alert_input_snapshots;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Alert retention records are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO inp FROM alert_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Alert retention input is absent' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Retention must start pending' USING ERRCODE='23514'; END IF;
  IF NEW.reason='ttl' AND inp.expires_at>CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'Alert has not expired' USING ERRCODE='23514'; END IF;
  IF NEW.reason='source' AND NOT EXISTS (
   SELECT 1 FROM alert_input_dependencies d WHERE d.input_id=inp.id AND d.owner_id=inp.owner_id AND (
    d.expires_at<=CURRENT_TIMESTAMP OR EXISTS (
     SELECT 1 FROM source_retention_work w WHERE w.owner_id=d.owner_id AND
       (w.price_snapshot_id=d.price_snapshot_id OR w.fx_snapshot_id=d.fx_snapshot_id
       OR w.benchmark_snapshot_id=d.benchmark_snapshot_id OR w.corporate_action_snapshot_id=d.corporate_action_snapshot_id
       OR w.constituent_snapshot_id=d.constituent_snapshot_id)) OR EXISTS (
     SELECT 1 FROM enrichment_retention_work w WHERE w.owner_id=d.owner_id AND
       (w.entity_evidence_version_id=d.entity_evidence_version_id OR w.classification_snapshot_id=d.classification_snapshot_id
       OR w.fund_definition_id=d.fund_definition_id OR w.fund_mapping_id=d.fund_mapping_id)))) THEN
   RAISE EXCEPTION 'No expired report source' USING ERRCODE='23514';
  END IF;
  IF NEW.reason='owner' AND EXISTS (SELECT 1 FROM broker_accounts WHERE id=inp.account_id AND status='active') THEN
   RAISE EXCEPTION 'Owner termination requires inactive account' USING ERRCODE='23514';
  END IF;
 ELSE
  IF to_jsonb(NEW)-'completed_at' IS DISTINCT FROM to_jsonb(OLD)-'completed_at' OR OLD.completed_at IS NOT NULL THEN
   RAISE EXCEPTION 'Alert retention identity is immutable' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.completed_at IS NOT NULL AND alert_capture_pending(NEW.owner_id,NEW.input_id) THEN RAISE EXCEPTION 'Alert payload remains' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
