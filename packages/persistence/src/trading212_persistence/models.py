"""PostgreSQL system-of-record schema for the Phase 1 canonical model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .activity_revision_models import ActivityRevisionEvidenceModel
from .alert_models import ALERT_MODELS
from .base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from .historical_models import HISTORICAL_MODELS
from .intelligence_quality_models import INTELLIGENCE_QUALITY_MODELS
from .planning_models import PLANNING_MODELS
from .premium_models import PREMIUM_MODELS
from .provider_observation_models import PROVIDER_OBSERVATION_MODELS
from .report_models import REPORT_MODELS
from .risk_models import RISK_MODELS
from .scenario_models import SCENARIO_MODELS
from .scenario_source_models import SCENARIO_SOURCE_MODELS
from .source_models import SOURCE_MODELS
from .target_models import TARGET_MODELS
from .types import ExactNumeric, UTCDateTime
from .xray_models import XRAY_MODELS

JSON = dict[str, Any]


class OwnerModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "owners"

    display_name: Mapped[str | None] = mapped_column(String(200))


class PrincipalModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_principals_issuer_subject"),
        UniqueConstraint("owner_id", "id", name="uq_principals_owner_id"),
        CheckConstraint("status IN ('active','disabled')", name="status_allowed"),
        Index("ix_principals_owner_status", "owner_id", "status"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    last_authenticated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class BrokerConnectionModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "broker_connections"
    __table_args__ = (
        CheckConstraint("provider IN ('trading212','synthetic')", name="provider_allowed"),
        CheckConstraint("environment IN ('demo','live','synthetic')", name="environment_allowed"),
        CheckConstraint(
            "status IN ('active','inactive','disabled','error')", name="status_allowed"
        ),
        Index("ix_broker_connections_owner_provider", "owner_id", "provider", "environment"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class BrokerAccountModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "broker_accounts"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "provider_account_id",
            name="uq_broker_accounts_connection_provider_account",
        ),
        CheckConstraint("base_currency ~ '^[A-Z]{3}$'", name="base_currency_format"),
        CheckConstraint(
            "status IN ('active','inactive','disabled','error')", name="status_allowed"
        ),
        Index("ix_broker_accounts_connection_status", "connection_id", "status"),
    )

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_connections.id", ondelete="CASCADE"), nullable=False
    )
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(80), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class InstrumentModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "instruments"
    __table_args__ = (Index("ix_instruments_isin", "isin", unique=True),)

    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(80), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12))


class ListingModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "environment",
            "provider_instrument_id",
            name="uq_listings_provider_environment_instrument",
        ),
        CheckConstraint("provider IN ('trading212','synthetic')", name="provider_allowed"),
        CheckConstraint("environment IN ('demo','live','synthetic')", name="environment_allowed"),
        CheckConstraint("trading_currency ~ '^[A-Z]{3}$'", name="trading_currency_format"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        Index("ix_listings_ticker_provider", "ticker", "provider", "environment"),
        Index("ix_listings_instrument_status", "instrument_id", "status"),
    )

    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_instrument_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str] = mapped_column(String(80), nullable=False)
    exchange_mic: Mapped[str | None] = mapped_column(String(16))
    exchange_id: Mapped[str | None] = mapped_column(String(120))
    trading_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime())


class IngestionRunModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id", "idempotency_key", name="uq_ingestion_runs_account_idempotency"
        ),
        CheckConstraint("mode IN ('full','incremental','refresh')", name="mode_allowed"),
        CheckConstraint("requested_mode IN ('full','incremental')", name="requested_mode_allowed"),
        CheckConstraint("request_schema_version = 1", name="request_schema_version_supported"),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'", name="request_fingerprint_format"
        ),
        CheckConstraint(
            "jsonb_typeof(requested_capabilities) = 'array'",
            name="requested_capabilities_array",
        ),
        CheckConstraint(
            "jsonb_typeof(effective_capabilities) = 'array'",
            name="effective_capabilities_array",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','partial','failed','cancelled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "request_count >= 0 AND records_received >= 0 AND records_normalized >= 0 "
            "AND records_rejected >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="time_order"),
        Index("ix_ingestion_runs_account_started", "broker_account_id", "started_at"),
        Index("ix_ingestion_runs_account_status", "broker_account_id", "status"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    request_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_create_snapshot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    requested_capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    effective_capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_normalized: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    checkpoint_before: Mapped[JSON | None] = mapped_column(JSONB)
    checkpoint_after: Mapped[JSON | None] = mapped_column(JSONB)
    rate_limit_observations: Mapped[JSON | None] = mapped_column(JSONB)
    warnings: Mapped[list[JSON]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(100))


class RefreshDispatchOutboxModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "refresh_dispatch_outbox"
    __table_args__ = (
        UniqueConstraint("ingestion_run_id", name="uq_refresh_dispatch_outbox_run"),
        CheckConstraint("task_name = 'portfolio.refresh'", name="task_name_fixed"),
        CheckConstraint("task_version = 1", name="task_version_supported"),
        CheckConstraint(
            "status IN ('pending','publishing','published','dead')", name="status_allowed"
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "consumer_attempt_count BETWEEN 0 AND 4",
            name="consumer_attempt_count_bounded",
        ),
        CheckConstraint(
            "consecutive_failure_count >= 0",
            name="consecutive_failures_nonnegative",
        ),
        CheckConstraint(
            "consecutive_failure_count <= attempt_count",
            name="consecutive_failures_within_attempts",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND "
            "payload ?& ARRAY['run_id','account_id','request_fingerprint',"
            "'request_schema_version'] AND "
            "payload - ARRAY['run_id','account_id','request_fingerprint',"
            "'request_schema_version'] = '{}'::jsonb AND "
            "(payload->>'run_id')::uuid = ingestion_run_id AND "
            "(payload->>'account_id') ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND "
            "(payload->>'request_fingerprint') ~ '^[0-9a-f]{64}$' AND "
            "payload->>'request_schema_version' = '1'",
            name="payload_contract",
        ),
        CheckConstraint(
            "(status = 'publishing' AND claim_token IS NOT NULL "
            "AND claim_owner IS NOT NULL AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL) OR "
            "(status != 'publishing' AND claim_token IS NULL AND claim_owner IS NULL "
            "AND claimed_at IS NULL AND claim_expires_at IS NULL)",
            name="publishing_claim_present",
        ),
        CheckConstraint(
            "(status = 'pending' AND published_at IS NULL) OR "
            "(status = 'publishing' AND published_at IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL) OR "
            "(status = 'dead' AND published_at IS NULL)",
            name="publication_state_match",
        ),
        CheckConstraint(
            "claim_owner IS NULL OR claim_owner ~ '^[A-Za-z0-9._:-]{1,120}$'",
            name="claim_owner_format",
        ),
        CheckConstraint(
            "claim_expires_at IS NULL OR "
            "(claimed_at IS NOT NULL AND claim_expires_at > claimed_at)",
            name="claim_expiry_order",
        ),
        Index(
            "ix_refresh_dispatch_outbox_ready",
            "status",
            "available_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_refresh_dispatch_outbox_claim_expiry",
            "claim_expires_at",
            postgresql_where=text("status = 'publishing'"),
        ),
    )

    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_name: Mapped[str] = mapped_column(String(80), nullable=False)
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    consumer_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    consecutive_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    claim_token: Mapped[UUID | None] = mapped_column()
    claim_owner: Mapped[str | None] = mapped_column(String(120))
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class RefreshDispatcherHeartbeatModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "refresh_dispatcher_heartbeats"
    __table_args__ = (
        UniqueConstraint("dispatcher_id", name="uq_refresh_dispatcher_heartbeats_identity"),
        CheckConstraint(
            "dispatcher_id ~ '^[A-Za-z0-9._:-]{1,120}$'",
            name="identity_format",
        ),
        CheckConstraint("state IN ('healthy','degraded')", name="state_allowed"),
        CheckConstraint("heartbeat_at >= started_at", name="heartbeat_order"),
        CheckConstraint(
            "last_successful_cycle_at IS NULL OR "
            "(last_successful_cycle_at >= started_at "
            "AND last_successful_cycle_at <= heartbeat_at)",
            name="success_order",
        ),
        Index("ix_refresh_dispatcher_heartbeats_state_heartbeat", "state", "heartbeat_at"),
    )

    dispatcher_id: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_successful_cycle_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class CollectionQuerySnapshotModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Short-lived immutable identity set for one mutable collection traversal."""

    __tablename__ = "collection_query_snapshots"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_collection_snapshots_owner_identity"),
        CheckConstraint("schema_version = 1", name="schema_version_supported"),
        CheckConstraint(
            (
                "resource IN ('risk_definitions','risk_versions','risk_runs',"
                "'scenario_definitions','scenario_versions','scenario_runs',"
                "'intelligence_quality_sources','activity','dividends','instruments',"
                "'positions_market_value','positions_weight','positions_ticker',"
                "'portfolios_name','portfolios_updated','target_versions',"
                "'target_events','target_nodes','contribution_plans','plan_lines',"
                "'actual_target_rows','plan_revisions','market_source_status',"
                "'benchmark_source_status','fx_source_status','price_observations',"
                "'fx_observations','benchmark_observations','benchmark_defs_name',"
                "'benchmark_defs_created','benchmark_versions','historical_performance',"
                "'historical_cash_flows','composite_benchmark_points','xray_exposures',"
                "'xray_paths','xray_held_funds','xray_pairs','xray_common_entities',"
                "'constituent_holdings','reports','premium_reports','exports','alert_rules'"
                ",'alert_versions','alert_events','alert_evaluations','notification_destina"
                "tions')"
            ),
            name="resource_allowed",
        ),
        CheckConstraint(
            (
                "(resource IN ('intelligence_quality_sources','historical_performance',"
                "'historical_cash_flows',"
                "'composite_benchmark_points','xray_exposures','xray_paths',"
                "'xray_held_funds','xray_pairs','xray_common_entities',"
                "'constituent_holdings') AND sort_specification = 'ordinal_asc') OR "
                "(resource = 'activity' AND sort_specification = "
                "'occurred_at_desc_id_desc') OR (resource = 'dividends' AND "
                "sort_specification = 'paid_on_desc_id_desc') OR (resource = "
                "'instruments' AND sort_specification = "
                "'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR "
                "(resource = 'positions_market_value' AND sort_specification = "
                "'market_value_desc_ticker_asc_listing_id_asc') OR (resource = "
                "'positions_weight' AND sort_specification = "
                "'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = "
                "'positions_ticker' AND sort_specification = "
                "'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND "
                "sort_specification = 'name_asc_id_asc') OR (resource = "
                "'portfolios_updated' AND sort_specification = "
                "'updated_at_desc_id_desc') OR (resource = 'target_versions' AND "
                "sort_specification = 'version_number_desc_id_desc') OR (resource = "
                "'target_events' AND sort_specification = 'created_at_desc_id_desc') OR "
                "(resource = 'target_nodes' AND sort_specification = "
                "'depth_first_order_key') OR (resource = 'plan_revisions' AND "
                "sort_specification = 'revision_number_desc_id_desc') OR (resource = "
                "'contribution_plans' AND sort_specification = "
                "'created_at_desc_id_desc') OR (resource IN ('plan_lines',"
                "'actual_target_rows','plan_revisions') AND sort_specification = "
                "'ordinal_asc') OR (resource = 'market_source_status' AND "
                "sort_specification = 'source_key_asc_id_asc') OR (resource = "
                "'benchmark_source_status' AND sort_specification = "
                "'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND "
                "sort_specification = 'base_quote_provider_asc') OR (resource = "
                "'price_observations' AND sort_specification = 'ordinal_asc') OR "
                "(resource = 'fx_observations' AND sort_specification = 'ordinal_asc') "
                "OR (resource = 'benchmark_observations' AND sort_specification = "
                "'ordinal_asc') OR (resource = 'benchmark_defs_name' AND "
                "sort_specification = 'name_asc_id_asc') OR (resource = "
                "'benchmark_defs_created' AND sort_specification = "
                "'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND "
                "sort_specification = 'version_number_desc_id_desc') OR (resource IN "
                "('reports','premium_reports','exports','alert_rules','alert_versions','ale"
                "rt_events',"
                "'alert_evaluations','notification_destinations') AND sort_specification = "
                "'created_at_desc_id_desc') OR "
                "(resource IN ('risk_definitions','risk_runs',"
                "'scenario_definitions','scenario_runs') AND "
                "sort_specification='created_at_desc_id_desc') OR "
                "(resource IN ('risk_versions','scenario_versions') AND "
                "sort_specification='version_number_desc_id_desc')"
            ),
            name="resource_sort_match",
        ),
        CheckConstraint(
            (
                "((resource IN ('risk_definitions','risk_versions','risk_runs',"
                "'scenario_definitions','scenario_versions','scenario_runs',"
                "'intelligence_quality_sources','alert_rules','alert_versions',"
                "'alert_events','alert_evaluations',"
                "'notification_destinations','reports','premium_reports','exports','activit"
                "y','dividends',"
                "'positions_market_value','positions_weight','positions_ticker',"
                "'contribution_plans','plan_lines','actual_target_rows','plan_revisions',"
                "'historical_performance','historical_cash_flows','xray_exposures',"
                "'xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND "
                "broker_account_id IS NOT NULL) OR (resource = 'instruments' AND "
                "broker_account_id IS NULL) OR resource IN ('portfolios_name',"
                "'portfolios_updated','target_versions','target_events','target_nodes',"
                "'market_source_status','benchmark_source_status','fx_source_status',"
                "'price_observations','fx_observations','benchmark_observations',"
                "'benchmark_defs_name','benchmark_defs_created','benchmark_versions',"
                "'composite_benchmark_points','constituent_holdings'))"
            ),
            name="account_scope_match",
        ),
        CheckConstraint(
            "((resource IN ('positions_market_value','positions_weight','positions_ticker') "
            "AND source_snapshot_id IS NOT NULL) OR "
            "(resource NOT IN ('positions_market_value','positions_weight','positions_ticker') "
            "AND source_snapshot_id IS NULL))",
            name="source_snapshot_scope_match",
        ),
        CheckConstraint(
            "filter_fingerprint ~ '^[0-9a-f]{64}$'",
            name="filter_fingerprint_format",
        ),
        CheckConstraint("exact_total >= 0", name="exact_total_nonnegative"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_collection_query_snapshots_expiry", "expires_at", "id"),
        Index("ix_collection_query_snapshots_owner_expiry", "owner_id", "expires_at", "id"),
        Index("ix_collection_query_snapshots_broker_account", "broker_account_id"),
        Index("ix_collection_query_snapshots_source_snapshot", "source_snapshot_id"),
        Index(
            "ix_collection_query_snapshots_scope",
            "owner_id",
            "broker_account_id",
            "resource",
            "filter_fingerprint",
            "expires_at",
        ),
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False
    )
    broker_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE")
    )
    source_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="CASCADE")
    )
    sort_specification: Mapped[str] = mapped_column(String(100), nullable=False)
    filter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    exact_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class CollectionQuerySnapshotMemberModel(Base):
    """One record identity at its deterministic 1-based result ordinal."""

    __tablename__ = "collection_query_snapshot_members"
    __table_args__ = (
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        UniqueConstraint(
            "snapshot_id",
            "record_id",
            name="uq_collection_snapshot_member_record",
        ),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "collection_query_snapshots.id",
            name="fk_collection_snapshot_member_snapshot",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    record_id: Mapped[UUID] = mapped_column(nullable=False)


class IngestionCheckpointModel(UUIDPrimaryKeyMixin, UpdatedAtMixin, Base):
    __tablename__ = "ingestion_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id", "capability", name="uq_ingestion_checkpoints_account_capability"
        ),
        CheckConstraint(
            "coverage_end_at IS NULL OR coverage_start_at IS NULL "
            "OR coverage_end_at >= coverage_start_at",
            name="coverage_order",
        ),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    coverage_start_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    coverage_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    coverage_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    advanced_by_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )


class IngestionLeaseModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ingestion_leases"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id", "lease_type", name="uq_ingestion_leases_account_type"
        ),
        UniqueConstraint("fencing_token", name="uq_ingestion_leases_fencing_token"),
        CheckConstraint("expires_at > acquired_at", name="expiry_after_acquisition"),
        Index("ix_ingestion_leases_expiry", "expires_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    lease_type: Mapped[str] = mapped_column(String(100), nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(200), nullable=False)
    fencing_token: Mapped[UUID] = mapped_column(nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"))


class SourceRecordModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "capability",
            "provider_record_id",
            "payload_fingerprint",
            name="uq_source_records_account_capability_provider_version",
        ),
        Index(
            "uq_source_records_anonymous_fingerprint",
            "broker_account_id",
            "capability",
            "payload_fingerprint",
            unique=True,
            postgresql_where=text("provider_record_id IS NULL"),
        ),
        CheckConstraint("provider IN ('trading212','synthetic')", name="provider_allowed"),
        Index("ix_source_records_account_observed", "broker_account_id", "observed_at"),
        Index("ix_source_records_run", "ingestion_run_id"),
    )

    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"), nullable=False
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_record_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_record_id: Mapped[str | None] = mapped_column(String(255))
    payload_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    sanitized_payload: Mapped[JSON | None] = mapped_column(JSONB)


class SourceRecordOccurrenceModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Run membership for immutable source records, including unchanged observations."""

    __tablename__ = "source_record_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "ingestion_run_id",
            "source_record_id",
            name="uq_source_record_occurrences_run_record",
        ),
        Index("ix_source_record_occurrences_run", "ingestion_run_id"),
        Index("ix_source_record_occurrences_record", "source_record_id"),
    )

    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class TransactionModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "provider_transaction_id",
            name="uq_transactions_account_provider_id",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_transactions_account_occurred", "broker_account_id", "occurred_at"),
        Index("ix_transactions_listing_occurred", "instrument_listing_id", "occurred_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider_transaction_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    instrument_listing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    unit_price: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    gross_amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    fees: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    taxes: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    net_cash_amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    settlement_date: Mapped[date | None] = mapped_column(Date())
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )
    mapping_version: Mapped[str] = mapped_column(String(80), nullable=False)


class CashFlowModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cash_flows"
    __table_args__ = (
        UniqueConstraint("broker_account_id", "idempotency_key", name="uq_cash_flows_account_key"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "classification IN ('external','internal','unknown')", name="class_allowed"
        ),
        Index("ix_cash_flows_account_occurred", "broker_account_id", "occurred_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    source_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    flow_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    quality: Mapped[str] = mapped_column(String(30), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )


class DividendModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "dividends"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id", "provider_dividend_id", name="uq_dividends_account_provider_id"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_dividends_account_paid", "broker_account_id", "paid_on"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider_dividend_id: Mapped[str] = mapped_column(String(255), nullable=False)
    instrument_listing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT")
    )
    gross_amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    withholding_tax: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    net_amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    paid_on: Mapped[date] = mapped_column(Date(), nullable=False)
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )


class OrderObservationModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "order_observations"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "provider_order_id",
            "observed_at",
            name="uq_order_observations_account_order_observed",
        ),
        Index("ix_order_observations_account_observed", "broker_account_id", "observed_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    instrument_listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_quantity: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    requested_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    filled_quantity: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    filled_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    provider_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )


class PositionObservationModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "position_observations"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "listing_id",
            "observed_at",
            name="uq_position_observations_account_listing_observed",
        ),
        CheckConstraint("valuation_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_position_observations_account_observed", "broker_account_id", "observed_at"),
        Index("ix_position_observations_listing_observed", "listing_id", "observed_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    provider_average_price: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    provider_market_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    provider_unrealized_pnl: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    valuation_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )


class CashBalanceObservationModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cash_balance_observations"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "currency",
            "observed_at",
            name="uq_cash_observations_account_currency_observed",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_cash_observations_account_observed", "broker_account_id", "observed_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False
    )


class LedgerEntryModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id", "idempotency_key", name="uq_ledger_entries_account_key"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_ledger_entries_account_economic", "broker_account_id", "economic_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    source_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    source_dividend_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("dividends.id", ondelete="RESTRICT")
    )
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    economic_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    quality: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    fx_base_currency: Mapped[str | None] = mapped_column(String(3))
    fx_quote_currency: Mapped[str | None] = mapped_column(String(3))
    fx_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fx_source: Mapped[str | None] = mapped_column(String(120))


class CalculationRunModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "calculation_runs"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "calculation_name",
            "version",
            "input_fingerprint",
            name="uq_calculation_runs_reproducible_input",
        ),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_calculation_runs_account_calculated", "broker_account_id", "calculated_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    calculation_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    output_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    method: Mapped[str] = mapped_column(String(200), nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    options: Mapped[JSON] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    input_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    quality_state: Mapped[str] = mapped_column(String(30), nullable=False)
    coverage: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[JSON]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    missing_inputs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class PortfolioSnapshotModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "valuation_at",
            "source_cutoff_at",
            "calculation_version",
            name="uq_portfolio_snapshots_reproducible_key",
        ),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("source_cutoff_at <= valuation_at", name="cutoff_not_after_valuation"),
        Index("ix_portfolio_snapshots_account_valuation", "broker_account_id", "valuation_at"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    calculation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cash_total: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    invested_total: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    portfolio_total: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    net_contributions: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    calculation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(30), nullable=False)
    coverage: Mapped[JSON] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[JSON]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class SnapshotPositionModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "snapshot_positions"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "listing_id", name="uq_snapshot_positions_snapshot_listing"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_snapshot_positions_listing", "listing_id"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    market_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    cost_basis: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(30), nullable=False)
    value_origin: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance: Mapped[JSON] = mapped_column(JSONB, nullable=False)


class SnapshotCashModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "snapshot_cash"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "currency", name="uq_snapshot_cash_snapshot_currency"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(30), nullable=False)
    value_origin: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance: Mapped[JSON] = mapped_column(JSONB, nullable=False)


class ReconciliationRunModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "as_of",
            "algorithm_version",
            "input_fingerprint",
            name="uq_reconciliation_runs_reproducible_key",
        ),
        CheckConstraint("coverage_end_at >= coverage_start_at", name="coverage_order"),
        CheckConstraint("discrepancy_count >= 0", name="count_nonnegative"),
        Index("ix_reconciliation_runs_account_as_of", "broker_account_id", "as_of"),
    )

    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    tolerance_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(30), nullable=False)
    coverage_start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    coverage_end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    coverage_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    coverage_gaps: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings: Mapped[list[JSON]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    provenance: Mapped[JSON] = mapped_column(JSONB, nullable=False)


class ReconciliationDiscrepancyModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reconciliation_discrepancies"
    __table_args__ = (
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("tolerance IS NULL OR tolerance >= 0", name="tolerance_nonnegative"),
        CheckConstraint("last_seen_at >= first_seen_at", name="seen_order"),
        Index("ix_discrepancies_account_resolution", "broker_account_id", "resolution_state"),
        Index("ix_discrepancies_run_type", "reconciliation_run_id", "discrepancy_type"),
    )

    reconciliation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    discrepancy_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    resolution_state: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    observed_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    residual: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    tolerance: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    likely_cause: Mapped[str | None] = mapped_column(String(200))
    downstream_effect: Mapped[str] = mapped_column(String(500), nullable=False)
    resolution_reason: Mapped[str | None] = mapped_column(String(500))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_by_principal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("principals.id", ondelete="RESTRICT")
    )
    provenance: Mapped[JSON] = mapped_column(JSONB, nullable=False)


class AuditEventModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_owner_occurred", "owner_id", "occurred_at"),
        Index("ix_audit_events_account_occurred", "broker_account_id", "occurred_at"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False
    )
    principal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    broker_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120))
    safe_metadata: Mapped[JSON | None] = mapped_column(JSONB)


class CalculationRegistryModel(Base):
    __tablename__ = "calculation_registry"

    calculation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    input_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    method_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    quality_policy: Mapped[str] = mapped_column(String(500), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    definition_fingerprint: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False, unique=True
    )


ALL_MODELS = (
    OwnerModel,
    PrincipalModel,
    BrokerConnectionModel,
    BrokerAccountModel,
    InstrumentModel,
    ListingModel,
    IngestionRunModel,
    RefreshDispatchOutboxModel,
    RefreshDispatcherHeartbeatModel,
    CollectionQuerySnapshotModel,
    CollectionQuerySnapshotMemberModel,
    IngestionCheckpointModel,
    IngestionLeaseModel,
    SourceRecordModel,
    TransactionModel,
    CashFlowModel,
    DividendModel,
    OrderObservationModel,
    PositionObservationModel,
    CashBalanceObservationModel,
    LedgerEntryModel,
    CalculationRunModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
    SnapshotCashModel,
    ReconciliationRunModel,
    ReconciliationDiscrepancyModel,
    AuditEventModel,
    CalculationRegistryModel,
    *TARGET_MODELS,
    *PLANNING_MODELS,
    *SOURCE_MODELS,
    *HISTORICAL_MODELS,
    *INTELLIGENCE_QUALITY_MODELS,
    *XRAY_MODELS,
    *REPORT_MODELS,
    *ALERT_MODELS,
    ActivityRevisionEvidenceModel,
    *PROVIDER_OBSERVATION_MODELS,
    *PREMIUM_MODELS,
    *RISK_MODELS,
    *SCENARIO_MODELS,
    *SCENARIO_SOURCE_MODELS,
)
