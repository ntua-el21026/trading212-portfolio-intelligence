"""Normalized owner-scoped immutable market reference sources and benchmarks."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import ExactNumeric, UTCDateTime


class SourceOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


def owned() -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id")


def owner_fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column], [f"{table}.owner_id", f"{table}.id"], ondelete="RESTRICT"
    )


class MarketDataProviderModel(SourceOwned):
    __tablename__ = "market_data_providers"
    __table_args__ = (
        CheckConstraint(
            "(freshness_policy_version IS NULL AND max_age_seconds IS NULL) OR "
            "(freshness_policy_version IS NOT NULL AND max_age_seconds IS NOT NULL AND "
            "max_age_seconds BETWEEN 0 AND 315360000)",
            name="freshness_policy",
        ),
        CheckConstraint(
            "cardinality(capabilities) <= 7 AND capabilities <@ "
            "ARRAY['price_history','corporate_actions','fx_rates','benchmark_series','"
            "resolve_instrument','classifications','constituents']::varchar[] AND card"
            "inality(supported_price_bases) <= 3 AND supported_price_bases <@ ARRAY['r"
            "aw_close','split_adjusted','total_return']::varchar[]",
            name="capabilities_allowed",
        ),
        owned(),
        UniqueConstraint("owner_id", "key", name="uq_source_provider_key"),
        CheckConstraint(
            "configuration_state IN ('configured','not_configured','disabled')",
            name="configuration_allowed",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )
    freshness_policy_version: Mapped[str | None] = mapped_column(String(120))
    max_age_seconds: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    supported_price_bases: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    key: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    adapter_version: Mapped[str] = mapped_column(String(120))
    configuration_state: Mapped[str] = mapped_column(String(20))
    synthetic: Mapped[bool] = mapped_column(Boolean)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ProviderLicenseVersionModel(SourceOwned):
    __tablename__ = "provider_license_versions"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint(
            "owner_id", "provider_id", "id", name="uq_source_license_provider_identity"
        ),
        UniqueConstraint("provider_id", "version"),
        CheckConstraint(
            "store_permission IN ('allowed','denied','unknown') AND display_permission IN "
            "('allowed','denied','unknown') AND report_permission IN "
            "('allowed','denied','unknown') AND export_permission IN "
            "('allowed','denied','unknown')",
            name="permissions_allowed",
        ),
        CheckConstraint(
            "retention_days BETWEEN 1 AND 36500 OR (retention_days IS NULL AND "
            "store_permission <> 'allowed')",
            name="retention_bounded",
        ),
        Index("ix_source_licenses_effective", "owner_id", "provider_id", "effective_at", "id"),
    )
    provider_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(120))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    store_permission: Mapped[str] = mapped_column(String(10))
    display_permission: Mapped[str] = mapped_column(String(10))
    report_permission: Mapped[str] = mapped_column(String(10))
    export_permission: Mapped[str] = mapped_column(String(10))
    retention_days: Mapped[int | None] = mapped_column(Integer)
    attribution: Mapped[str] = mapped_column(String(2000))
    evidence_key: Mapped[str] = mapped_column(String(120))


class SourceCalendarModel(SourceOwned):
    __tablename__ = "source_calendars"
    __table_args__ = (
        owned(),
        UniqueConstraint("owner_id", "key", "version", name="uq_source_calendar_version"),
        CheckConstraint(
            "period_end >= period_start AND period_end - period_start <= 3660",
            name="period_bounded",
        ),
    )
    key: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(120))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    content_digest: Mapped[str] = mapped_column(String(64))


class SourceCalendarSessionModel(SourceOwned):
    __tablename__ = "source_calendar_sessions"
    __table_args__ = (
        owned(),
        owner_fk("calendar_id", "source_calendars"),
        UniqueConstraint("calendar_id", "session_date"),
    )
    calendar_id: Mapped[UUID] = mapped_column()
    session_date: Mapped[date] = mapped_column(Date)
    close_at: Mapped[datetime] = mapped_column(UTCDateTime())


class MarketDataInstrumentModel(SourceOwned):
    __tablename__ = "market_data_instruments"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint(
            "owner_id", "provider_id", "id", name="uq_source_mapping_provider_identity"
        ),
        UniqueConstraint("provider_id", "provider_key", "version"),
        CheckConstraint("state IN ('resolved','unresolved','ambiguous')", name="state_allowed"),
        CheckConstraint(
            "(state = 'resolved' AND instrument_id IS NOT NULL) OR (state <> 'resolved' "
            "AND instrument_id IS NULL AND listing_id IS NULL)",
            name="resolved_identity",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity"),
    )
    provider_id: Mapped[UUID] = mapped_column()
    provider_key: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    identifier_kind: Mapped[str] = mapped_column(String(20))
    identifier_value: Mapped[str] = mapped_column(String(120))
    identifier_mic: Mapped[str | None] = mapped_column(String(4))
    currency: Mapped[str] = mapped_column(String(3))
    asset_type: Mapped[str] = mapped_column(String(120))
    evidence_key: Mapped[str] = mapped_column(String(120))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))


class SourceMappingCandidateModel(SourceOwned):
    __tablename__ = "source_mapping_candidates"
    __table_args__ = (
        owned(),
        owner_fk("mapping_id", "market_data_instruments"),
        UniqueConstraint("mapping_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 19 AND confidence BETWEEN 0 AND 1", name="bounds"),
    )
    mapping_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    evidence_key: Mapped[str] = mapped_column(String(120))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confidence: Mapped[Decimal] = mapped_column(ExactNumeric())


class MarketSourceSeriesModel(SourceOwned):
    __tablename__ = "market_source_series"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("calendar_id", "source_calendars"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "mapping_id"],
            [
                "market_data_instruments.owner_id",
                "market_data_instruments.provider_id",
                "market_data_instruments.id",
            ],
        ),
        UniqueConstraint(
            "owner_id",
            "provider_id",
            "license_version_id",
            "id",
            name="uq_source_series_provider_identity",
        ),
        UniqueConstraint(
            "provider_id",
            "provider_key",
            "mapping_version",
            "basis",
            "license_version_id",
            "calendar_id",
        ),
        CheckConstraint(
            "(kind = 'security_price' AND mapping_id IS NOT NULL AND instrument_id IS NOT "
            "NULL) OR (kind = 'benchmark_level' AND mapping_id IS NULL AND instrument_id "
            "IS NULL AND listing_id IS NULL)",
            name="kind_identity",
        ),
        CheckConstraint(
            "basis IN ('raw_close','split_adjusted','total_return')", name="basis_allowed"
        ),
        Index("ix_source_series_catalog", "owner_id", "kind", "provider_key", "id"),
    )
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    calendar_id: Mapped[UUID] = mapped_column()
    mapping_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    provider_key: Mapped[str] = mapped_column(String(120))
    mapping_version: Mapped[str] = mapped_column(String(120))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    basis: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    content_digest: Mapped[str] = mapped_column(String(64))


class SourceSnapshotFields(SourceOwned):
    __abstract__ = True
    economic_digest: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    adapter_version: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(120))
    source_revision: Mapped[str] = mapped_column(String(120))
    revision_order: Mapped[int | None] = mapped_column(BigInteger)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    synthetic: Mapped[bool] = mapped_column(Boolean)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    expected_count: Mapped[int] = mapped_column(Integer)
    available_count: Mapped[int] = mapped_column(Integer)
    quality: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(40))
    content_digest: Mapped[str] = mapped_column(String(64))


def snapshot_constraints() -> tuple[object, ...]:
    return (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
        ),
        UniqueConstraint("content_digest", "owner_id"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "period_end >= period_start AND period_end - period_start <= 3660",
            name="period_bounded",
        ),
        CheckConstraint(
            "available_count BETWEEN 0 AND expected_count AND expected_count BETWEEN 0 AND 100000",
            name="coverage_bounds",
        ),
        CheckConstraint("expires_at > first_observed_at", name="retention_interval"),
    )


def series_snapshot_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "provider_id", "license_version_id", "series_id"],
        [
            "market_source_series.owner_id",
            "market_source_series.provider_id",
            "market_source_series.license_version_id",
            "market_source_series.id",
        ],
    )


class PriceSnapshotModel(SourceSnapshotFields):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        *snapshot_constraints(),
        series_snapshot_fk(),
        Index(
            "ix_price_snapshot_selection",
            "owner_id",
            "series_id",
            "first_observed_at",
            "effective_at",
            "id",
        ),
    )
    series_id: Mapped[UUID] = mapped_column()


class FxSnapshotModel(SourceSnapshotFields):
    __tablename__ = "fx_snapshots"
    calendar_id: Mapped[UUID] = mapped_column()
    __table_args__ = (
        *snapshot_constraints(),
        owner_fk("calendar_id", "source_calendars"),
        Index(
            "ix_fx_snapshot_selection",
            "owner_id",
            "provider_id",
            "first_observed_at",
            "effective_at",
            "id",
        ),
    )


class CorporateActionSnapshotModel(SourceSnapshotFields):
    __tablename__ = "corporate_action_snapshots"
    __table_args__ = (*snapshot_constraints(), series_snapshot_fk())
    series_id: Mapped[UUID] = mapped_column()


class BenchmarkDefinitionModel(SourceOwned):
    __tablename__ = "benchmark_definitions"
    __table_args__ = (
        owned(),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index("ix_benchmark_definition_name", "owner_id", "name", "id"),
    )
    name: Mapped[str] = mapped_column(String(120))
    reporting_currency: Mapped[str] = mapped_column(String(3))
    revision: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class BenchmarkVersionModel(SourceOwned):
    __tablename__ = "benchmark_versions"
    __table_args__ = (
        owner_fk("calendar_id", "source_calendars"),
        owned(),
        owner_fk("definition_id", "benchmark_definitions"),
        UniqueConstraint("definition_id", "version_number"),
        CheckConstraint("version_number >= 1", name="version_positive"),
    )
    definition_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    reporting_currency: Mapped[str] = mapped_column(String(3))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    basis: Mapped[str] = mapped_column(String(20))
    calendar_id: Mapped[UUID] = mapped_column()
    rebalance: Mapped[str] = mapped_column(String(30))
    content_digest: Mapped[str] = mapped_column(String(64))


class BenchmarkComponentModel(SourceOwned):
    __tablename__ = "benchmark_components"
    __table_args__ = (
        owned(),
        owner_fk("version_id", "benchmark_versions"),
        owner_fk("source_id", "market_source_series"),
        UniqueConstraint("version_id", "source_id"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight_bounds"),
    )
    version_id: Mapped[UUID] = mapped_column()
    source_id: Mapped[UUID] = mapped_column()
    weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    original_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class BenchmarkSnapshotModel(SourceSnapshotFields):
    __tablename__ = "benchmark_snapshots"
    __table_args__ = (
        *snapshot_constraints(),
        series_snapshot_fk(),
        owner_fk("benchmark_version_id", "benchmark_versions"),
        CheckConstraint(
            "(snapshot_kind = 'provider_series' AND series_id IS NOT NULL AND "
            "benchmark_version_id IS NULL AND provider_id IS NOT NULL AND "
            "license_version_id IS NOT NULL AND adapter_version IS NOT NULL AND "
            "source_revision IS NOT NULL) OR (snapshot_kind = 'composite' AND "
            "series_id "
            "IS NULL AND benchmark_version_id IS NOT NULL AND provider_id IS "
            "NULL AND license_version_id IS NULL AND adapter_version IS NULL AND "
            "source_revision IS NULL)",
            name="snapshot_kind_xor",
        ),
        Index(
            "ix_benchmark_snapshot_selection",
            "owner_id",
            "series_id",
            "first_observed_at",
            "effective_at",
            "id",
        ),
    )
    # Provider provenance is absent on the derived composite branch; the XOR guard
    # requires the full provenance for every provider-series row.
    provider_id: Mapped[UUID] = mapped_column(nullable=True)
    license_version_id: Mapped[UUID] = mapped_column(nullable=True)
    adapter_version: Mapped[str] = mapped_column(String(120), nullable=True)
    source_revision: Mapped[str] = mapped_column(String(120), nullable=True)
    series_id: Mapped[UUID | None] = mapped_column()
    benchmark_version_id: Mapped[UUID | None] = mapped_column()
    snapshot_kind: Mapped[str] = mapped_column(String(20))


class SourceObservationFields(SourceOwned):
    __abstract__ = True
    snapshot_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    session_date: Mapped[date] = mapped_column(Date)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    state: Mapped[str] = mapped_column(String(20))


def observation_constraints(table: str, amount: str) -> tuple[object, ...]:
    return (
        owned(),
        owner_fk("snapshot_id", table),
        UniqueConstraint("ordinal", "snapshot_id"),
        CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bounds"),
        CheckConstraint(
            "state IN ('available','missing','unsupported','disputed')", name="state_allowed"
        ),
        CheckConstraint(
            f"(state = 'available' AND {amount} IS NOT NULL AND {amount} > 0 "
            f"AND {amount} < 'Infinity'::numeric) OR "
            f"(state <> 'available' AND {amount} IS NULL)",
            name="available_value",
        ),
    )


class PriceObservationModel(SourceObservationFields):
    __tablename__ = "price_observations"
    __table_args__ = (
        *observation_constraints("price_snapshots", "value"),
        UniqueConstraint("snapshot_id", "session_date"),
    )
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    corporate_action_revision: Mapped[str | None] = mapped_column(String(120))


class FxObservationModel(SourceObservationFields):
    __tablename__ = "fx_observations"
    __table_args__ = (
        *observation_constraints("fx_snapshots", "rate"),
        UniqueConstraint("snapshot_id", "session_date", "base", "quote"),
        CheckConstraint("base <> quote", name="distinct_currencies"),
        Index("ix_fx_observation_pairs", "owner_id", "base", "quote", "snapshot_id"),
    )
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    batch_key: Mapped[str] = mapped_column(String(120))


class BenchmarkObservationModel(SourceObservationFields):
    __tablename__ = "benchmark_observations"
    __table_args__ = (
        *observation_constraints("benchmark_snapshots", "level"),
        UniqueConstraint("snapshot_id", "session_date"),
    )
    level: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class CorporateActionObservationModel(SourceObservationFields):
    __tablename__ = "corporate_action_observations"
    __table_args__ = (
        CheckConstraint(
            "ordinal BETWEEN 0 AND 99999 AND state IN "
            "('available','missing','unsupported','disputed')",
            name="row_bounds",
        ),
        CheckConstraint(
            "(state <> 'available' AND ratio IS NULL AND amount IS NULL AND currency IS "
            "NULL AND target_instrument_id IS NULL) OR (state = 'available' AND ((kind = "
            "'cash_distribution' AND amount IS NOT NULL AND amount >= 0 AND amount < "
            "'Infinity'::numeric AND currency ~ '^[A-Z]{3}$' AND ratio IS NULL AND "
            "target_instrument_id IS NULL) OR (kind IN ('split','merger','spinoff') AND "
            "ratio IS NOT NULL AND ratio > 0 AND ratio < 'Infinity'::numeric AND amount IS "
            "NULL AND currency IS NULL AND ((kind = 'split' AND target_instrument_id IS "
            "NULL) OR (kind IN ('merger','spinoff') AND target_instrument_id IS NOT NULL)))))",
            name="action_fields",
        ),
        owned(),
        owner_fk("snapshot_id", "corporate_action_snapshots"),
        UniqueConstraint("ordinal", "snapshot_id"),
        UniqueConstraint("snapshot_id", "source_key"),
        CheckConstraint(
            "kind IN ('split','cash_distribution','merger','spinoff')", name="kind_allowed"
        ),
    )
    source_key: Mapped[str] = mapped_column(String(120))
    source_revision: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    ratio: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))
    target_instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    correction_source_key: Mapped[str | None] = mapped_column(String(120))


class SourceSnapshotReference(SourceOwned):
    __abstract__ = True
    price_snapshot_id: Mapped[UUID | None] = mapped_column()
    fx_snapshot_id: Mapped[UUID | None] = mapped_column()
    benchmark_snapshot_id: Mapped[UUID | None] = mapped_column()
    corporate_action_snapshot_id: Mapped[UUID | None] = mapped_column()


def snapshot_references() -> tuple[object, ...]:
    return (
        owned(),
        *(
            owner_fk(f"{kind}_snapshot_id", f"{kind}_snapshots")
            for kind in ("price", "fx", "benchmark", "corporate_action")
        ),
        CheckConstraint(
            "num_nonnulls(price_snapshot_id, fx_snapshot_id, benchmark_snapshot_id, "
            "corporate_action_snapshot_id) = 1",
            name="snapshot_xor",
        ),
    )


class SourceCoverageGapModel(SourceSnapshotReference):
    __tablename__ = "source_coverage_gaps"
    __table_args__ = snapshot_references()
    session_date: Mapped[date] = mapped_column(Date)
    source_key: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(40))
    ordinal: Mapped[int] = mapped_column(Integer)


class SourceRetrievalOccurrenceModel(SourceSnapshotReference):
    __tablename__ = "source_retrieval_occurrences"
    __table_args__ = (
        *snapshot_references(),
        Index("ix_source_retrieval_order", "owner_id", "retrieved_at", "id"),
    )
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime())


class SourceExpiryEventModel(SourceSnapshotReference):
    __tablename__ = "source_expiry_events"
    __table_args__ = (
        *snapshot_references(),
        *(
            UniqueConstraint(f"{kind}_snapshot_id")
            for kind in ("price", "fx", "benchmark", "corporate_action")
        ),
    )
    removed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    removed_observation_count: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(40))


class SourceCommandIdentityModel(SourceOwned):
    __tablename__ = "source_command_identities"
    __table_args__ = (
        owner_fk("response_selected_version_id", "benchmark_versions"),
        owned(),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_source_command_key"),
        CheckConstraint(
            "kind IN "
            "('provider.configure','license.register','mapping.register','calendar.reg"
            "ister','series.register','price.ingest','fx.ingest','benchmark.ingest','a"
            "ctions.ingest','definition.create','definition.version','definition.archi"
            "ve')",
            name="kind_allowed",
        ),
    )
    kind: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    request_digest: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[UUID] = mapped_column()
    result_revision: Mapped[int | None] = mapped_column(Integer)
    response_total: Mapped[int | None] = mapped_column(Integer)
    response_next_cursor: Mapped[str | None] = mapped_column(String(2048))
    response_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    response_archived: Mapped[bool | None] = mapped_column(Boolean)
    response_selected_version_id: Mapped[UUID | None] = mapped_column()
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(100))


class SourceCommandVersionModel(SourceOwned):
    __tablename__ = "source_command_versions"
    __table_args__ = (
        owned(),
        owner_fk("command_id", "source_command_identities"),
        owner_fk("version_id", "benchmark_versions"),
        UniqueConstraint("command_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 24", name="response_bound"),
    )
    command_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)


class SourceAuditEventModel(SourceOwned):
    __tablename__ = "source_audit_events"
    __table_args__ = (
        owned(),
        owner_fk("command_id", "source_command_identities"),
        UniqueConstraint("command_id"),
    )
    command_id: Mapped[UUID] = mapped_column()
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[UUID] = mapped_column()


class SourceCollectionBindingModel(SourceOwned):
    __tablename__ = "source_collection_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "collection_snapshot_id"],
            ["collection_query_snapshots.owner_id", "collection_query_snapshots.id"],
            ondelete="CASCADE",
        ),
        owned(),
        UniqueConstraint("collection_snapshot_id"),
        Index("ix_source_collection_cache", "owner_id", "cache_key"),
    )
    collection_snapshot_id: Mapped[UUID] = mapped_column()
    cache_key: Mapped[str] = mapped_column(String(64))


class SourceStatusSelectionModel(SourceOwned):
    """Frozen status references; current authorization still gates every read."""

    __tablename__ = "source_status_selections"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        owner_fk("series_id", "market_source_series"),
        owner_fk("retrieval_id", "source_retrieval_occurrences"),
        owner_fk("price_snapshot_id", "price_snapshots"),
        owner_fk("fx_snapshot_id", "fx_snapshots"),
        owner_fk("benchmark_snapshot_id", "benchmark_snapshots"),
        UniqueConstraint("owner_id", "selection_digest", name="uq_source_status_selection"),
        CheckConstraint(
            "num_nonnulls(price_snapshot_id,fx_snapshot_id,benchmark_snapshot_id) <= 1",
            name="snapshot_exclusive",
        ),
    )
    selection_reason: Mapped[str | None] = mapped_column(String(40))
    selection_digest: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[UUID] = mapped_column()
    series_id: Mapped[UUID | None] = mapped_column()
    price_snapshot_id: Mapped[UUID | None] = mapped_column()
    fx_snapshot_id: Mapped[UUID | None] = mapped_column()
    benchmark_snapshot_id: Mapped[UUID | None] = mapped_column()
    retrieval_id: Mapped[UUID | None] = mapped_column()
    base: Mapped[str | None] = mapped_column(String(3))
    quote: Mapped[str | None] = mapped_column(String(3))


SOURCE_MODELS = (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
    MarketDataInstrumentModel,
    SourceMappingCandidateModel,
    MarketSourceSeriesModel,
    PriceSnapshotModel,
    FxSnapshotModel,
    CorporateActionSnapshotModel,
    BenchmarkDefinitionModel,
    BenchmarkVersionModel,
    BenchmarkComponentModel,
    BenchmarkSnapshotModel,
    PriceObservationModel,
    FxObservationModel,
    BenchmarkObservationModel,
    CorporateActionObservationModel,
    SourceCoverageGapModel,
    SourceRetrievalOccurrenceModel,
    SourceExpiryEventModel,
    SourceCommandIdentityModel,
    SourceAuditEventModel,
    SourceCommandVersionModel,
    SourceCollectionBindingModel,
    SourceStatusSelectionModel,
)
