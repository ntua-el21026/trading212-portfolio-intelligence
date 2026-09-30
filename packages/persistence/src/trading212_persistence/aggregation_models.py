"""Owner-scoped aggregate roots with scoped members and purgeable complete projections."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from .base import Base
from .source_models import SourceOwned, owned, owner_fk
from .types import ExactNumeric, UTCDateTime


def _check(name: str, value: str) -> CheckConstraint:
    return CheckConstraint(value, name=conv("ck_aggregate_" + name))


class AggregateSelectionModel(SourceOwned):
    __tablename__ = "aggregate_selections"
    __table_args__ = (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "actor_id"], ["principals.owner_id", "principals.id"], ondelete="RESTRICT"
        ),
        _check("selection_revision", "revision BETWEEN 1 AND 2147483647"),
        _check("selection_members", "member_count BETWEEN 1 AND 8"),
        _check("selection_digest", "content_digest ~ '^[0-9a-f]{64}$'"),
        _check("selection_currency", "reporting_currency ~ '^[A-Z]{3}$'"),
        _check("selection_policy", "identity_policy='canonical_instrument_v1'"),
        Index("ix_aggregate_selections_owner_created", "owner_id", "created_at", "id"),
    )
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_command_identities.id", ondelete="RESTRICT"), unique=True
    )
    actor_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    member_count: Mapped[int] = mapped_column(Integer)
    reporting_currency: Mapped[str] = mapped_column(String(3))
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    identity_policy: Mapped[str] = mapped_column(String(40))
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class AggregateMemberModel(SourceOwned):
    __tablename__ = "aggregate_account_members"
    __table_args__ = (
        owned(),
        owner_fk("selection_id", "aggregate_selections"),
        UniqueConstraint("selection_id", "ordinal", name="uq_aggregate_members_ordinal"),
        UniqueConstraint("selection_id", "account_id", name="uq_aggregate_members_account"),
        UniqueConstraint("selection_id", "snapshot_id", name="uq_aggregate_members_snapshot"),
        UniqueConstraint(
            "owner_id", "selection_id", "account_id", name="uq_aggregate_members_scope"
        ),
        _check("member_ordinal", "ordinal BETWEEN 0 AND 7"),
        Index("ix_aggregate_members_account", "owner_id", "account_id", "selection_id"),
    )
    selection_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )


class AggregateSelectionPayloadModel(SourceOwned):
    __tablename__ = "aggregate_selection_payloads"
    __table_args__ = (
        owned(),
        owner_fk("selection_id", "aggregate_selections"),
        UniqueConstraint("selection_id"),
        _check("selection_payload", "octet_length(payload) BETWEEN 1 AND 65536"),
    )
    selection_id: Mapped[UUID] = mapped_column()
    payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class AggregateRunModel(SourceOwned):
    __tablename__ = "aggregate_runs"
    __table_args__ = (
        owned(),
        owner_fk("selection_id", "aggregate_selections"),
        ForeignKeyConstraint(
            ["owner_id", "actor_id"], ["principals.owner_id", "principals.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("selection_id", "selection_revision"),
        _check("run_revision", "selection_revision BETWEEN 2 AND 2147483647"),
        _check(
            "run_digests",
            (
                "(holdings_input_digest IS NULL OR holdings_input_digest ~ "
                "'^[0-9a-f]{64}$') AND (holdings_result_digest IS NULL OR "
                "holdings_result_digest ~ '^[0-9a-f]{64}$') AND "
                "(activity_input_digest IS NULL OR activity_input_digest ~ "
                "'^[0-9a-f]{64}$') AND (activity_result_digest IS NULL OR "
                "activity_result_digest ~ '^[0-9a-f]{64}$')"
            ),
        ),
        _check(
            "run_retention", "expires_at>created_at AND expires_at<=created_at+interval '30 days'"
        ),
        _check(
            "run_capacity",
            (
                "reserved_bytes>=0 AND retained_bytes>=0 AND "
                "reserved_bytes+retained_bytes<=33554432 AND financial_rows>=0"
            ),
        ),
        _check(
            "run_publication",
            (
                "(sealed AND reserved_bytes=0 AND completed_at IS NOT NULL AND "
                "holdings_input_digest IS NOT NULL AND holdings_result_digest IS "
                "NOT NULL) OR (NOT sealed AND completed_at IS NULL)"
            ),
        ),
        _check(
            "run_activity",
            (
                "(activity_requested AND activity_start_at IS NOT NULL AND "
                "activity_end_at IS NOT NULL AND "
                "activity_end_at>activity_start_at AND "
                "activity_end_at<=activity_start_at+interval '3660 days') OR (NOT "
                "activity_requested AND activity_start_at IS NULL AND "
                "activity_end_at IS NULL AND activity_input_digest IS NULL AND "
                "activity_result_digest IS NULL)"
            ),
        ),
        Index(
            "ix_aggregate_runs_selection_created", "owner_id", "selection_id", "created_at", "id"
        ),
        Index("ix_aggregate_runs_owner_expiry", "owner_id", "expires_at", "id"),
        Index(
            "ix_aggregate_runs_retained",
            "owner_id",
            "id",
            postgresql_where=text("retained_bytes>0"),
        ),
        Index(
            "ix_aggregate_runs_selection_retained",
            "owner_id",
            "selection_id",
            "id",
            postgresql_where=text("retained_bytes>0"),
        ),
        Index(
            "ix_aggregate_runs_owner_copies",
            "owner_id",
            "id",
            postgresql_where=text("retained_bytes+reserved_bytes>0"),
        ),
    )
    selection_id: Mapped[UUID] = mapped_column()
    selection_revision: Mapped[int] = mapped_column(Integer)
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_command_identities.id", ondelete="RESTRICT"), unique=True
    )
    actor_id: Mapped[UUID] = mapped_column()
    holdings_input_digest: Mapped[str | None] = mapped_column(String(64))
    holdings_result_digest: Mapped[str | None] = mapped_column(String(64))
    activity_input_digest: Mapped[str | None] = mapped_column(String(64))
    activity_result_digest: Mapped[str | None] = mapped_column(String(64))
    activity_requested: Mapped[bool] = mapped_column(Boolean)
    activity_start_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    activity_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger)
    retained_bytes: Mapped[int] = mapped_column(BigInteger)
    financial_rows: Mapped[int] = mapped_column(Integer)


class AggregateRunChild(SourceOwned):
    __abstract__ = True
    run_id: Mapped[UUID] = mapped_column()


def _run_constraints(table: str) -> tuple[object, ...]:
    return (
        owned(),
        owner_fk("run_id", "aggregate_runs"),
        Index("ix_" + table + "_run", "owner_id", "run_id", "id"),
    )


class AggregateHoldingsPayloadModel(AggregateRunChild):
    __tablename__ = "aggregate_holdings_payloads"
    __table_args__ = (
        *_run_constraints(__tablename__),
        UniqueConstraint("run_id"),
        _check(
            "holdings_payload_bytes",
            (
                "octet_length(input_payload)>0 AND octet_length(result_payload)>0 "
                "AND octet_length(summary_payload)>0 AND "
                "octet_length(input_payload)+octet_length(result_payload)+octet_l"
                "ength(summary_payload)<=33554432"
            ),
        ),
    )
    input_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    result_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    summary_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    summary_digest: Mapped[str] = mapped_column(String(64))


class AggregateActivityPayloadModel(AggregateRunChild):
    __tablename__ = "aggregate_activity_payloads"
    __table_args__ = (
        *_run_constraints(__tablename__),
        UniqueConstraint("run_id"),
        _check(
            "activity_payload_bytes",
            (
                "octet_length(input_payload)>0 AND octet_length(result_payload)>0 "
                "AND octet_length(summary_payload)>0 AND "
                "octet_length(input_payload)+octet_length(result_payload)+octet_l"
                "ength(summary_payload)<=33554432"
            ),
        ),
    )
    input_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    result_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    summary_payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    summary_digest: Mapped[str] = mapped_column(String(64))


class AggregateProjectionRow(AggregateRunChild):
    __abstract__ = True
    ordinal: Mapped[int] = mapped_column(Integer)
    payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    content_digest: Mapped[str] = mapped_column(String(64))


def _projection_constraints(table: str, limit: int = 10256) -> tuple[object, ...]:
    return (
        *_run_constraints(table),
        UniqueConstraint("run_id", "ordinal", name="uq_" + table + "_ordinal"),
        CheckConstraint(f"ordinal BETWEEN 0 AND {limit - 1}", name="ordinal_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("octet_length(payload) BETWEEN 1 AND 2097152", name="payload_bound"),
        Index("ix_" + table + "_page", "owner_id", "run_id", "ordinal"),
    )


class AggregateSnapshotModel(AggregateProjectionRow):
    __tablename__ = "aggregate_input_members"
    __table_args__ = (
        *_projection_constraints(__tablename__, 8),
        UniqueConstraint("run_id", "account_id", name="uq_aggregate_input_account"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    calculation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )


class AggregateFxModel(AggregateProjectionRow):
    __tablename__ = "aggregate_fx_uses"
    __table_args__ = (
        *_projection_constraints(__tablename__, 256),
        UniqueConstraint("run_id", "account_id", "source_currency", name="uq_aggregate_fx_pair"),
        owner_fk("fx_snapshot_id", "fx_snapshots"),
        owner_fk("fx_observation_id", "fx_observations"),
        owner_fk("license_version_id", "provider_license_versions"),
        Index("ix_aggregate_fx_observation_reverse", "owner_id", "fx_observation_id"),
        _check(
            "fx_rate",
            (
                "(state='available' AND original_rate IS NOT NULL AND "
                "original_rate>0) OR (state IN "
                "('missing','unsupported','disputed') AND original_rate IS NULL)"
            ),
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    source_currency: Mapped[str] = mapped_column(String(3))
    target_currency: Mapped[str] = mapped_column(String(3))
    fx_snapshot_id: Mapped[UUID] = mapped_column()
    fx_observation_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    original_rate: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    state: Mapped[str] = mapped_column(String(20))
    inverted: Mapped[bool] = mapped_column(Boolean)


class AggregateComponentModel(AggregateProjectionRow):
    __tablename__ = "aggregate_components"
    __table_args__ = (
        *_projection_constraints(__tablename__),
        UniqueConstraint("run_id", "component_id", name="uq_aggregate_component_identity"),
        _check(
            "component_kind",
            (
                "(kind='position' AND position_id IS NOT NULL AND cash_id IS NULL "
                "AND listing_id IS NOT NULL AND instrument_id IS NOT NULL AND "
                "quantity IS NOT NULL) OR (kind='cash' AND cash_id IS NOT NULL "
                "AND position_id IS NULL AND listing_id IS NULL AND instrument_id "
                "IS NULL AND quantity IS NULL)"
            ),
        ),
        _check("component_availability", "(converted_value IS NULL)=(reason IS NOT NULL)"),
        Index("ix_aggregate_component_fx_reverse", "fx_observation_id"),
    )
    component_id: Mapped[UUID] = mapped_column()
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(10))
    position_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("snapshot_positions.id", ondelete="RESTRICT")
    )
    cash_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("snapshot_cash.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    native_currency: Mapped[str] = mapped_column(String(3))
    native_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    converted_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    fx_observation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fx_observations.id", ondelete="RESTRICT")
    )
    quality: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(String(40))


class AggregateHoldingModel(AggregateProjectionRow):
    __tablename__ = "aggregate_holdings"
    __table_args__ = (
        *_projection_constraints(__tablename__, 10000),
        UniqueConstraint("run_id", "instrument_id", name="uq_aggregate_holding_identity"),
    )
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(ExactNumeric())
    currency: Mapped[str] = mapped_column(String(3))
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    known_value: Mapped[Decimal] = mapped_column(ExactNumeric())
    known_count: Mapped[int] = mapped_column(Integer)
    total_count: Mapped[int] = mapped_column(Integer)


class AggregateAccountTotalModel(AggregateProjectionRow):
    __tablename__ = "aggregate_account_totals"
    __table_args__ = (
        *_projection_constraints(__tablename__, 8),
        UniqueConstraint("run_id", "account_id", name="uq_aggregate_account_total"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    currency: Mapped[str] = mapped_column(String(3))
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    known_value: Mapped[Decimal] = mapped_column(ExactNumeric())
    known_count: Mapped[int] = mapped_column(Integer)
    total_count: Mapped[int] = mapped_column(Integer)


class AggregateActivityEvidenceModel(AggregateProjectionRow):
    __tablename__ = "aggregate_transfer_evidence"
    __table_args__ = (
        *_projection_constraints(__tablename__, 10000),
        UniqueConstraint(
            "owner_id", "run_id", "source_record_id", name="uq_aggregate_evidence_source"
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    selected: Mapped[bool] = mapped_column(Boolean)
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))


class AggregateCoverageModel(AggregateProjectionRow):
    __tablename__ = "aggregate_activity_coverage"
    __table_args__ = (
        *_projection_constraints(__tablename__, 10000),
        UniqueConstraint("run_id", "coverage_id", name="uq_aggregate_coverage_identity"),
        owner_fk("coverage_id", "historical_activity_coverage"),
        owner_fk("evidence_id", "historical_evidence_sets"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    coverage_id: Mapped[UUID] = mapped_column()
    evidence_id: Mapped[UUID] = mapped_column()
    evidence_digest: Mapped[str] = mapped_column(String(64))
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT")
    )
    capability: Mapped[str] = mapped_column(String(100))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    complete: Mapped[bool] = mapped_column(Boolean)


class AggregateRevisionModel(AggregateProjectionRow):
    __tablename__ = "aggregate_activity_revisions"
    __table_args__ = (
        *_projection_constraints(__tablename__, 10000),
        UniqueConstraint("run_id", "evidence_id", name="uq_aggregate_revision_identity"),
        owner_fk("evidence_id", "activity_revision_evidence"),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    evidence_id: Mapped[UUID] = mapped_column()
    new_source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    superseded_source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )


class AggregateFlowModel(AggregateProjectionRow):
    __tablename__ = "aggregate_flow_legs"
    __table_args__ = (
        *_projection_constraints(__tablename__, 10000),
        UniqueConstraint("owner_id", "run_id", "source_record_id", name="uq_aggregate_flow_source"),
        ForeignKeyConstraint(
            ["owner_id", "run_id", "source_record_id"],
            [
                "aggregate_transfer_evidence.owner_id",
                "aggregate_transfer_evidence.run_id",
                "aggregate_transfer_evidence.source_record_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    source_record_id: Mapped[UUID] = mapped_column()
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))
    classification: Mapped[str] = mapped_column(String(30))
    counterpart_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )


class AggregateTransferModel(AggregateProjectionRow):
    __tablename__ = "aggregate_transfer_matches"
    __table_args__ = (
        *_projection_constraints(__tablename__, 5000),
        UniqueConstraint("run_id", "outgoing_record_id", name="uq_aggregate_transfer_out"),
        UniqueConstraint("run_id", "incoming_record_id", name="uq_aggregate_transfer_in"),
        ForeignKeyConstraint(
            ["owner_id", "run_id", "outgoing_record_id"],
            [
                "aggregate_flow_legs.owner_id",
                "aggregate_flow_legs.run_id",
                "aggregate_flow_legs.source_record_id",
            ],
            name="fk_aggregate_transfer_out_flow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "run_id", "incoming_record_id"],
            [
                "aggregate_flow_legs.owner_id",
                "aggregate_flow_legs.run_id",
                "aggregate_flow_legs.source_record_id",
            ],
            name="fk_aggregate_transfer_in_flow",
            ondelete="RESTRICT",
        ),
        _check(
            "transfer_principals",
            (
                "outgoing_principal<0 AND incoming_principal>0 AND "
                "outgoing_account_id<>incoming_account_id"
            ),
        ),
    )
    outgoing_record_id: Mapped[UUID] = mapped_column()
    incoming_record_id: Mapped[UUID] = mapped_column()
    outgoing_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    incoming_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    outgoing_principal: Mapped[Decimal] = mapped_column(ExactNumeric())
    incoming_principal: Mapped[Decimal] = mapped_column(ExactNumeric())
    outgoing_currency: Mapped[str] = mapped_column(String(3))
    incoming_currency: Mapped[str] = mapped_column(String(3))
    fx_rate: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class AggregateSourceModel(AggregateRunChild):
    __tablename__ = "aggregate_sources"
    __table_args__ = (
        *_run_constraints(__tablename__),
        UniqueConstraint("run_id", "view_kind", "source_kind", "source_id"),
        _check("source_view", "view_kind IN ('holdings','activity')"),
        _check(
            "source_binding",
            (
                "(source_kind='snapshot' AND source_id IS NOT DISTINCT FROM "
                "snapshot_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='calculation' AND source_id IS NOT "
                "DISTINCT FROM calculation_run_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='broker_record' AND source_id IS NOT "
                "DISTINCT FROM source_record_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='fx' AND source_id IS NOT DISTINCT FROM "
                "fx_snapshot_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='fx_observation' AND source_id IS NOT "
                "DISTINCT FROM fx_observation_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='coverage' AND source_id IS NOT DISTINCT "
                "FROM coverage_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='coverage_parent' AND source_id IS NOT "
                "DISTINCT FROM evidence_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1) OR (source_kind='revision' AND source_id IS NOT DISTINCT "
                "FROM revision_id AND "
                "num_nonnulls(snapshot_id,calculation_run_id,source_record_id,fx_"
                "snapshot_id,fx_observation_id,coverage_id,evidence_id,revision_i"
                "d)=1)"
            ),
        ),
        Index("ix_aggregate_sources_pending", "owner_id", "source_kind", "source_id", "run_id"),
        Index(
            "ix_aggregate_sources_fx_progress",
            "owner_id",
            "run_id",
            "id",
            postgresql_where=text("source_kind='fx'"),
        ),
    )
    view_kind: Mapped[str] = mapped_column(String(10))
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID] = mapped_column()
    snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    calculation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )
    source_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    fx_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fx_snapshots.id", ondelete="RESTRICT")
    )
    fx_observation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fx_observations.id", ondelete="RESTRICT")
    )
    coverage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_activity_coverage.id", ondelete="RESTRICT")
    )
    evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_evidence_sets.id", ondelete="RESTRICT")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("activity_revision_evidence.id", ondelete="RESTRICT")
    )


class AggregateRetentionModel(AggregateRunChild):
    __tablename__ = "aggregate_retention_work"
    __table_args__ = (
        *_run_constraints(__tablename__),
        UniqueConstraint("run_id"),
        _check("retention_reason", "reason IN ('expired','source','owner_erasure')"),
        _check("retention_time", "completed_at IS NULL OR completed_at>=created_at"),
        Index(
            "ix_aggregate_retention_pending",
            "owner_id",
            "id",
            postgresql_where=text("completed_at IS NULL"),
        ),
    )
    reason: Mapped[str] = mapped_column(String(20))
    source_fx_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fx_snapshots.id", ondelete="RESTRICT")
    )
    source_evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_evidence_sets.id", ondelete="RESTRICT")
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AggregateOwnerErasureModel(Base):
    __tablename__ = "aggregate_owner_erasure"
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AggregateRetentionCursorModel(Base):
    __tablename__ = "aggregate_retention_cursor"
    __table_args__ = (
        _check(
            "cursor_scope",
            "(key='aggregate' AND owner_id IS NULL) OR key='aggregate:'||owner_id::text",
        ),
        _check("cursor_pair", "(last_owner_id IS NULL)=(last_run_id IS NULL)"),
    )
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    last_owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    last_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("aggregate_runs.id", ondelete="RESTRICT")
    )
    # A physical keyset cursor intentionally outlives the deleted source row.
    last_source_id: Mapped[UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


AGGREGATION_MODELS = (
    AggregateSelectionModel,
    AggregateMemberModel,
    AggregateSelectionPayloadModel,
    AggregateRunModel,
    AggregateHoldingsPayloadModel,
    AggregateActivityPayloadModel,
    AggregateSnapshotModel,
    AggregateFxModel,
    AggregateComponentModel,
    AggregateHoldingModel,
    AggregateAccountTotalModel,
    AggregateActivityEvidenceModel,
    AggregateCoverageModel,
    AggregateRevisionModel,
    AggregateFlowModel,
    AggregateTransferModel,
    AggregateSourceModel,
    AggregateRetentionModel,
    AggregateOwnerErasureModel,
    AggregateRetentionCursorModel,
)

# Exact reverse probes used by scoped erasure and immutable-parent FK guards.
for _number, (_model, _columns) in enumerate(
    (
        (AggregateFlowModel, ("owner_id", "run_id", "source_record_id")),
        (AggregateTransferModel, ("owner_id", "run_id", "outgoing_record_id")),
        (AggregateTransferModel, ("owner_id", "run_id", "incoming_record_id")),
        (AggregateSourceModel, ("snapshot_id",)),
        (AggregateSourceModel, ("calculation_run_id",)),
        (AggregateSourceModel, ("source_record_id",)),
        (AggregateSourceModel, ("fx_snapshot_id",)),
        (AggregateSourceModel, ("fx_observation_id",)),
        (AggregateSourceModel, ("coverage_id",)),
        (AggregateSourceModel, ("evidence_id",)),
        (AggregateSourceModel, ("revision_id",)),
    )
):
    Index(f"ix_aggregate_reverse_{_number}", *(_model.__table__.c[name] for name in _columns))
