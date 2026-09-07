"""Immutable historical evidence, capture, source uses and analytical projections."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import ExactNumeric, UTCDateTime


class HistoricalOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


def owned() -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id")


def owner_fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{table}.owner_id", f"{table}.id"],
        ondelete="RESTRICT",
        name="fk_historical_dependency_registered_evidence"
        if column == "registered_evidence_id"
        else "fk_historical_use_expected_series"
        if column == "expected_series_id"
        else None,
    )


class HistoricalPolicyModel(HistoricalOwned):
    __tablename__ = "historical_policy_versions"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id", "broker_account_id", "key", name="uq_historical_policy_account_key"
        ),
        owner_fk("calendar_id", "source_calendars"),
        CheckConstraint("octet_length(canonical_policy) <= 33554432", name="payload_bound"),
        Index("ix_historical_policy_selection", "owner_id", "broker_account_id", "effective_at"),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    key: Mapped[str] = mapped_column(String(120))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    calendar_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    canonical_policy: Mapped[bytes] = mapped_column(LargeBinary)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class HistoricalPolicySourceModel(HistoricalOwned):
    __tablename__ = "historical_policy_sources"
    __table_args__ = (
        owned(),
        owner_fk("policy_id", "historical_policy_versions"),
        owner_fk("series_id", "market_source_series"),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint("policy_id", "kind", "ordinal"),
        CheckConstraint(
            "kind IN ('price','action','fx_provider') AND ordinal BETWEEN 0 AND 255",
            name="kind_bound",
        ),
        CheckConstraint(
            "(kind='fx_provider' AND provider_id IS NOT NULL AND series_id IS "
            "NULL) OR (kind IN ('price','action') AND series_id IS NOT NULL AND "
            "provider_id IS NULL)",
            name="identity_xor",
        ),
    )
    policy_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    ordinal: Mapped[int] = mapped_column(Integer)
    series_id: Mapped[UUID | None] = mapped_column()
    provider_id: Mapped[UUID | None] = mapped_column()


class HistoricalEvidenceModel(HistoricalOwned):
    __tablename__ = "historical_evidence_sets"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id", "broker_account_id", "key", name="uq_historical_evidence_account_key"
        ),
        CheckConstraint("octet_length(canonical_evidence) <= 33554432", name="payload_bound"),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    key: Mapped[str] = mapped_column(String(120))
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))
    canonical_evidence: Mapped[bytes] = mapped_column(LargeBinary)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class HistoricalActivityCoverageModel(HistoricalOwned):
    __tablename__ = "historical_activity_coverage"
    __table_args__ = (
        owned(),
        owner_fk("evidence_id", "historical_evidence_sets"),
        UniqueConstraint("evidence_id", "ingestion_run_id", "capability"),
        CheckConstraint(
            "capability IN ('historical_orders','historical_transactions','historical_dividends')",
            name="capability_allowed",
        ),
        CheckConstraint(
            "start_at <= end_at AND end_at <= first_observed_at", name="coverage_time_order"
        ),
    )
    evidence_id: Mapped[UUID] = mapped_column()
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT")
    )
    capability: Mapped[str] = mapped_column(String(100))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    coverage_complete: Mapped[bool] = mapped_column(Boolean)


class HistoricalAnchorModel(HistoricalOwned):
    __tablename__ = "historical_valuation_anchors"
    __table_args__ = (
        owned(),
        owner_fk("evidence_id", "historical_evidence_sets"),
        UniqueConstraint("evidence_id", "anchor_key"),
        CheckConstraint("timing IN ('before_events','after_events')", name="timing_allowed"),
    )
    evidence_id: Mapped[UUID] = mapped_column()
    anchor_key: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    timing: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(80))
    canonical_anchor: Mapped[bytes] = mapped_column(LargeBinary)


class HistoricalAnchorPositionModel(HistoricalOwned):
    __tablename__ = "historical_anchor_positions"
    __table_args__ = (
        owned(),
        owner_fk("anchor_id", "historical_valuation_anchors"),
        UniqueConstraint("anchor_id", "listing_id"),
    )
    anchor_id: Mapped[UUID] = mapped_column()
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(ExactNumeric())
    currency: Mapped[str] = mapped_column(String(3))
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    acquisition_cost: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalAnchorCashModel(HistoricalOwned):
    __tablename__ = "historical_anchor_cash"
    __table_args__ = (
        owned(),
        owner_fk("anchor_id", "historical_valuation_anchors"),
        UniqueConstraint("anchor_id", "currency"),
    )
    anchor_id: Mapped[UUID] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalReconciliationLineModel(HistoricalOwned):
    __tablename__ = "historical_reconciliation_lines"
    __table_args__ = (
        owned(),
        owner_fk("anchor_id", "historical_valuation_anchors"),
        UniqueConstraint("anchor_id", "ordinal"),
        CheckConstraint("observed - expected = residual AND tolerance >= 0", name="equation"),
    )
    anchor_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    identity: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str | None] = mapped_column(String(3))
    expected: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    observed: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    residual: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    tolerance: Mapped[Decimal] = mapped_column(ExactNumeric())
    state: Mapped[str] = mapped_column(String(30))


class HistoricalClassificationModel(HistoricalOwned):
    __tablename__ = "historical_classification_evidence"
    __table_args__ = (
        owned(),
        owner_fk("evidence_id", "historical_evidence_sets"),
        owner_fk("license_version_id", "provider_license_versions"),
        CheckConstraint("dimension IN ('sector','asset_class')", name="dimension_allowed"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity"),
    )
    evidence_id: Mapped[UUID] = mapped_column()
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    dimension: Mapped[str] = mapped_column(String(20))
    taxonomy: Mapped[str] = mapped_column(String(120))
    taxonomy_version: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(120))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    license_version_id: Mapped[UUID] = mapped_column()
    canonical_classification: Mapped[bytes] = mapped_column(LargeBinary)


class HistoricalInputModel(HistoricalOwned):
    __tablename__ = "historical_input_snapshots"
    __table_args__ = (
        owned(),
        owner_fk("policy_id", "historical_policy_versions"),
        owner_fk("benchmark_version_id", "benchmark_versions"),
        owner_fk("target_version_id", "target_versions"),
        UniqueConstraint(
            "owner_id", "broker_account_id", "input_digest", name="uq_historical_capture_digest"
        ),
        CheckConstraint(
            "period_end >= period_start AND period_end-period_start <= 3660", name="period_bound"
        ),
        CheckConstraint(
            "knowledge_policy IN ('as_of_cutoff','point_in_time')", name="knowledge_allowed"
        ),
        CheckConstraint("octet_length(canonical_input) <= 33554432", name="payload_bound"),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    policy_id: Mapped[UUID | None] = mapped_column()
    benchmark_version_id: Mapped[UUID | None] = mapped_column()
    target_version_id: Mapped[UUID | None] = mapped_column()
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    knowledge_policy: Mapped[str] = mapped_column(String(30))
    input_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    canonical_input: Mapped[bytes] = mapped_column(LargeBinary)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class HistoricalInputInstrumentModel(HistoricalOwned):
    __tablename__ = "historical_input_instruments"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "historical_input_snapshots"),
        UniqueConstraint("input_id", "listing_id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    currency: Mapped[str] = mapped_column(String(3))


class HistoricalDependencyModel(HistoricalOwned):
    """Closed real FK union shared by capture and registered evidence dependencies."""

    __tablename__ = "historical_dependencies"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "historical_input_snapshots"),
        owner_fk("evidence_id", "historical_evidence_sets"),
        owner_fk("price_snapshot_id", "price_snapshots"),
        owner_fk("fx_snapshot_id", "fx_snapshots"),
        owner_fk("action_snapshot_id", "corporate_action_snapshots"),
        owner_fk("benchmark_snapshot_id", "benchmark_snapshots"),
        owner_fk("mapping_id", "market_data_instruments"),
        owner_fk("calendar_id", "source_calendars"),
        owner_fk("license_version_id", "provider_license_versions"),
        owner_fk("benchmark_version_id", "benchmark_versions"),
        owner_fk("target_version_id", "target_versions"),
        owner_fk("classification_id", "historical_classification_evidence"),
        owner_fk("registered_evidence_id", "historical_evidence_sets"),
        CheckConstraint("num_nonnulls(input_id,evidence_id)=1", name="parent_xor"),
        CheckConstraint(
            "num_nonnulls(ingestion_run_id,source_record_id,source_occurrence_id,portfolio_snapshot_id,calculation_run_id,reconciliation_run_id,price_snapshot_id,fx_snapshot_id,action_snapshot_id,benchmark_snapshot_id,mapping_id,calendar_id,license_version_id,benchmark_version_id,target_version_id,classification_id,registered_evidence_id)=1",
            name="source_xor",
        ),
    )
    input_id: Mapped[UUID | None] = mapped_column()
    evidence_id: Mapped[UUID | None] = mapped_column()
    ingestion_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT")
    )
    reference_key: Mapped[str] = mapped_column(String(160))
    source_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    source_occurrence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_record_occurrences.id", ondelete="RESTRICT")
    )
    portfolio_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    calculation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )
    reconciliation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT")
    )
    price_snapshot_id: Mapped[UUID | None] = mapped_column()
    fx_snapshot_id: Mapped[UUID | None] = mapped_column()
    action_snapshot_id: Mapped[UUID | None] = mapped_column()
    benchmark_snapshot_id: Mapped[UUID | None] = mapped_column()
    mapping_id: Mapped[UUID | None] = mapped_column()
    calendar_id: Mapped[UUID | None] = mapped_column()
    license_version_id: Mapped[UUID | None] = mapped_column()
    benchmark_version_id: Mapped[UUID | None] = mapped_column()
    target_version_id: Mapped[UUID | None] = mapped_column()
    classification_id: Mapped[UUID | None] = mapped_column()
    registered_evidence_id: Mapped[UUID | None] = mapped_column()


class HistoricalEventModel(HistoricalOwned):
    __tablename__ = "historical_event_revisions"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "historical_input_snapshots"),
        UniqueConstraint("input_id", "revision_id"),
        CheckConstraint(
            "kind IN "
            "('external_flow','execution','dividend','cash_effect','corporate_action','unknown_activity')",
            name="kind_allowed",
        ),
    )
    input_id: Mapped[UUID] = mapped_column()
    revision_id: Mapped[str] = mapped_column(String(120))
    economic_key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(30))
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    source_occurrence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_record_occurrences.id", ondelete="RESTRICT")
    )
    economic_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revision_sequence: Mapped[int | None] = mapped_column(Integer)
    order_key: Mapped[str | None] = mapped_column(String(120))
    fill_key: Mapped[str | None] = mapped_column(String(120))
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    currency: Mapped[str | None] = mapped_column(String(3))
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    quantity: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    price: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    canonical_event: Mapped[bytes] = mapped_column(LargeBinary)


class HistoricalRunModel(HistoricalOwned):
    __tablename__ = "historical_analytics_runs"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "historical_input_snapshots"),
        owner_fk("analytics_run_id", "analytics_runs"),
        UniqueConstraint(
            "owner_id", "input_id", "kind", "options_digest", name="uq_historical_run_options"
        ),
        UniqueConstraint("analytics_run_id"),
        CheckConstraint(
            "kind IN ('performance','benchmark','income','attribution','cash_flow')",
            name="kind_allowed",
        ),
    )
    input_id: Mapped[UUID] = mapped_column()
    analytics_run_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30))
    options_digest: Mapped[str] = mapped_column(String(64))
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class HistoricalResultRow(HistoricalOwned):
    __abstract__ = True
    run_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    row_key: Mapped[str] = mapped_column(String(160))
    canonical_row: Mapped[bytes] = mapped_column(LargeBinary)


def row_constraints() -> tuple[object, ...]:
    return (
        owned(),
        owner_fk("run_id", "historical_analytics_runs"),
        UniqueConstraint("run_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 100000", name="ordinal_bound"),
    )


class PerformancePointModel(HistoricalResultRow):
    __tablename__ = "performance_points"
    __table_args__ = row_constraints()
    date: Mapped[date] = mapped_column(Date)
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime())
    portfolio_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    cash_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    wealth: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    period_return: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class PerformancePeriodModel(HistoricalResultRow):
    __tablename__ = "performance_period_returns"
    __table_args__ = row_constraints()
    period_kind: Mapped[str] = mapped_column(String(30))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    period_return: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalIncomeRowModel(HistoricalResultRow):
    __tablename__ = "income_components"
    __table_args__ = row_constraints()
    row_kind: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(3))
    net: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    gross: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    withholding: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalAttributionRowModel(HistoricalResultRow):
    __tablename__ = "attribution_components"
    __table_args__ = row_constraints()
    currency: Mapped[str | None] = mapped_column(String(3))
    gain: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    return_contribution: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalCashFlowRowModel(HistoricalResultRow):
    __tablename__ = "historical_cash_flow_points"
    __table_args__ = row_constraints()
    economic_at: Mapped[datetime] = mapped_column(UTCDateTime())
    kind: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(3))
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalSourceUseModel(HistoricalOwned):
    __tablename__ = "historical_selected_source_uses"
    __table_args__ = (
        owned(),
        owner_fk("run_id", "historical_analytics_runs"),
        owner_fk("dependency_id", "historical_dependencies"),
        UniqueConstraint("run_id", "use_key"),
        owner_fk("component_source_id", "market_source_series"),
        owner_fk("expected_series_id", "market_source_series"),
        owner_fk("calendar_id", "source_calendars"),
        CheckConstraint(
            "consumer_kind IN ('holding','cash','event','group','benchmark','portfolio')",
            name="consumer_kind",
        ),
        CheckConstraint("kind IN ('observation','evidence','missing')", name="kind_allowed"),
        CheckConstraint(
            "(kind='observation' AND observation_index BETWEEN 0 AND 99999 AND "
            "dependency_id IS NOT NULL) OR (kind='evidence' AND "
            "observation_index IS NULL AND dependency_id IS NOT NULL) OR "
            "(kind='missing' AND observation_index IS NULL AND dependency_id IS "
            "NULL)",
            name="use_variant",
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    use_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(40))
    use_at: Mapped[datetime] = mapped_column(UTCDateTime())
    knowledge_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    dependency_id: Mapped[UUID | None] = mapped_column()
    observation_index: Mapped[int | None] = mapped_column(Integer)
    consumer_kind: Mapped[str] = mapped_column(String(40))
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    event_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    group_key: Mapped[str | None] = mapped_column(String(120))
    component_source_id: Mapped[UUID | None] = mapped_column()
    expected_series_id: Mapped[UUID | None] = mapped_column()
    expected_base: Mapped[str | None] = mapped_column(String(3))
    expected_quote: Mapped[str | None] = mapped_column(String(3))
    calendar_id: Mapped[UUID | None] = mapped_column()
    expected_session: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(120))
    canonical_use: Mapped[bytes] = mapped_column(LargeBinary)


class HistoricalUseCandidateModel(HistoricalOwned):
    __tablename__ = "historical_use_candidates"
    __table_args__ = (
        owned(),
        owner_fk("source_use_id", "historical_selected_source_uses"),
        owner_fk("dependency_id", "historical_dependencies"),
        UniqueConstraint("source_use_id", "dependency_id"),
    )
    source_use_id: Mapped[UUID] = mapped_column()
    dependency_id: Mapped[UUID] = mapped_column()


class HistoricalConversionLegModel(HistoricalOwned):
    __tablename__ = "historical_conversion_legs"
    __table_args__ = (
        owned(),
        owner_fk("run_id", "historical_analytics_runs"),
        owner_fk("source_use_id", "historical_selected_source_uses"),
        UniqueConstraint("run_id", "conversion_key", "ordinal"),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 1 AND direction IN ('direct','inverse') AND base <> quote",
            name="leg_bound",
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    source_use_id: Mapped[UUID] = mapped_column()
    conversion_key: Mapped[str] = mapped_column(String(160))
    ordinal: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(10))
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))


class HistoricalCollectionBindingModel(HistoricalOwned):
    __tablename__ = "historical_collection_bindings"
    __table_args__ = (
        owned(),
        owner_fk("run_id", "historical_analytics_runs"),
        UniqueConstraint("collection_snapshot_id"),
        Index("ix_historical_collection_cache", "owner_id", "cache_key"),
    )
    run_id: Mapped[UUID] = mapped_column()
    collection_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("collection_query_snapshots.id", ondelete="CASCADE")
    )
    cache_key: Mapped[str] = mapped_column(String(64))


class HistoricalCommandModel(HistoricalOwned):
    __tablename__ = "historical_command_identities"
    __table_args__ = (
        owned(),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_historical_command_key"),
        owner_fk("policy_id", "historical_policy_versions"),
        owner_fk("evidence_id", "historical_evidence_sets"),
        CheckConstraint(
            "(kind='historical.policy.register' AND policy_id IS NOT NULL AND "
            "evidence_id IS NULL) OR (kind='historical.evidence.register' AND "
            "evidence_id IS NOT NULL AND policy_id IS NULL)",
            name="command_variant",
        ),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    request_digest: Mapped[str] = mapped_column(String(64))
    policy_id: Mapped[UUID | None] = mapped_column()
    evidence_id: Mapped[UUID | None] = mapped_column()
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(100))


class HistoricalCompositeModel(HistoricalOwned):
    __tablename__ = "historical_composite_benchmarks"
    __table_args__ = (
        owned(),
        owner_fk("run_id", "historical_analytics_runs"),
        owner_fk("snapshot_id", "benchmark_snapshots"),
        UniqueConstraint("run_id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    snapshot_id: Mapped[UUID] = mapped_column()
    canonical_composite: Mapped[bytes] = mapped_column(LargeBinary)


class BenchmarkSnapshotComponentModel(HistoricalOwned):
    __tablename__ = "benchmark_snapshot_components"
    __table_args__ = (
        owned(),
        owner_fk("snapshot_id", "benchmark_snapshots"),
        owner_fk("source_id", "market_source_series"),
        UniqueConstraint("snapshot_id", "source_id"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight_bounds"),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    source_id: Mapped[UUID] = mapped_column()
    weight: Mapped[Decimal] = mapped_column(ExactNumeric())


class BenchmarkSnapshotDependencyModel(HistoricalOwned):
    __tablename__ = "benchmark_snapshot_dependencies"
    __table_args__ = (
        owned(),
        owner_fk("component_id", "benchmark_snapshot_components"),
        owner_fk("dependency_id", "historical_dependencies"),
        UniqueConstraint("component_id", "dependency_id"),
    )
    component_id: Mapped[UUID] = mapped_column()
    dependency_id: Mapped[UUID] = mapped_column()


class BenchmarkCompositePointModel(HistoricalOwned):
    __tablename__ = "benchmark_composite_points"
    __table_args__ = (
        owned(),
        owner_fk("snapshot_id", "benchmark_snapshots"),
        UniqueConstraint("snapshot_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 3661", name="ordinal_bound"),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    session_date: Mapped[date] = mapped_column(Date)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    wealth: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    interval_return: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    canonical_point: Mapped[bytes] = mapped_column(LargeBinary)


class HistoricalConversionModel(HistoricalOwned):
    __tablename__ = "historical_conversions"
    __table_args__ = (
        owned(),
        owner_fk("run_id", "historical_analytics_runs"),
        UniqueConstraint("run_id", "conversion_key"),
        CheckConstraint(
            "rate > 0 AND operation IN ('identity','direct','reciprocal','triangulated')",
            name="conversion_allowed",
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    conversion_key: Mapped[str] = mapped_column(String(160))
    use_at: Mapped[datetime] = mapped_column(UTCDateTime())
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    operation: Mapped[str] = mapped_column(String(20))
    rate: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class HistoricalRetentionEventModel(HistoricalOwned):
    __tablename__ = "historical_retention_events"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "historical_input_snapshots"),
        owner_fk("dependency_id", "historical_dependencies"),
        UniqueConstraint("input_id"),
        CheckConstraint("reason='retention_removed'", name="reason_fixed"),
    )
    input_id: Mapped[UUID] = mapped_column()
    dependency_id: Mapped[UUID] = mapped_column()
    removed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reason: Mapped[str] = mapped_column(String(40), default="retention_removed")


class HistoricalAuditEventModel(HistoricalOwned):
    __tablename__ = "historical_audit_events"
    __table_args__ = (
        owned(),
        owner_fk("command_id", "historical_command_identities"),
        owner_fk("input_id", "historical_input_snapshots"),
        owner_fk("run_id", "historical_analytics_runs"),
        CheckConstraint(
            "kind IN "
            "('policy_registered','evidence_registered','input_captured','result_published')",
            name="kind_allowed",
        ),
        CheckConstraint("num_nonnulls(command_id,input_id,run_id)=1", name="audit_parent"),
    )
    command_id: Mapped[UUID | None] = mapped_column()
    input_id: Mapped[UUID | None] = mapped_column()
    run_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30))
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(100))


HISTORICAL_MODELS = (
    HistoricalCompositeModel,
    BenchmarkSnapshotComponentModel,
    BenchmarkSnapshotDependencyModel,
    BenchmarkCompositePointModel,
    HistoricalConversionModel,
    HistoricalAuditEventModel,
    HistoricalRetentionEventModel,
    HistoricalPolicyModel,
    HistoricalPolicySourceModel,
    HistoricalEvidenceModel,
    HistoricalActivityCoverageModel,
    HistoricalAnchorModel,
    HistoricalAnchorPositionModel,
    HistoricalAnchorCashModel,
    HistoricalReconciliationLineModel,
    HistoricalClassificationModel,
    HistoricalInputModel,
    HistoricalInputInstrumentModel,
    HistoricalDependencyModel,
    HistoricalEventModel,
    HistoricalRunModel,
    PerformancePointModel,
    PerformancePeriodModel,
    HistoricalIncomeRowModel,
    HistoricalAttributionRowModel,
    HistoricalCashFlowRowModel,
    HistoricalSourceUseModel,
    HistoricalUseCandidateModel,
    HistoricalConversionLegModel,
    HistoricalCollectionBindingModel,
    HistoricalCommandModel,
)


# Defense in depth for every retained exact financial scalar.
for _model in HISTORICAL_MODELS:
    for _column in _model.__table__.columns:
        if isinstance(_column.type, ExactNumeric):
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} IS NULL OR {_column.name} NOT IN "
                    "('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
                    name=f"finite_{_column.name}",
                )
            )
        if _column.name in {"currency", "reporting_currency", "base", "quote"}:
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} IS NULL OR {_column.name} ~ '^[A-Z]{{3}}$'",
                    name=f"currency_{_column.name}",
                )
            )
        if _column.name.endswith("digest") or _column.name == "cache_key":
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} ~ '^[0-9a-f]{{64}}$'",
                    name=f"hash_{_column.name}",
                )
            )
