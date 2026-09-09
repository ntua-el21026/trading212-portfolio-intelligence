"""Normalized retained X-ray input, calculation and collection-owned projections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .source_models import SourceOwned, owned
from .source_models import owner_fk as source_owner_fk
from .types import UTCDateTime


def owner_fk(column: str, table: str) -> ForeignKeyConstraint:
    constraint = source_owner_fk(column, table)
    constraint.name = f"xray_{column}_{table}_fk"
    return constraint


def payload_bound(column: str) -> CheckConstraint:
    return CheckConstraint(f"octet_length({column}) <= 33554432", name=f"{column}_bound")


def coefficient_bound(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR {column} ~ '^(0|[1-9][0-9]{{0,249}})$'", name=f"{column}_exact"
    )


class XrayInputSnapshotModel(SourceOwned):
    __tablename__ = "xray_input_snapshots"
    __table_args__ = (
        owned(),
        owner_fk("policy_id", "xray_policy_versions"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "input_digest",
            name="uq_xray_input_snapshots_owner_id_account_id_input_digest",
        ),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "snapshot_id",
            "id",
            name="uq_xray_input_snapshots_owner_id_account_id_snapshot_id_id",
        ),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("sealed_at IS NULL OR sealed_at >= captured_at", name="sealed_order"),
        payload_bound("canonical_input"),
        Index("ix_xray_input_snapshot", "owner_id", "account_id", "snapshot_id", "id"),
        Index(
            "ix_xray_input_pending",
            "owner_id",
            "id",
            postgresql_where=text("canonical_input <> '\\x'::bytea"),
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    valuation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )
    reconciliation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT")
    )
    policy_id: Mapped[UUID] = mapped_column()
    reporting_currency: Mapped[str] = mapped_column(String(3))
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    input_digest: Mapped[str] = mapped_column(String(64))
    canonical_input: Mapped[bytes] = mapped_column(LargeBinary)


class XrayInputPositionModel(SourceOwned):
    __tablename__ = "xray_input_positions"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "xray_input_snapshots"),
        UniqueConstraint(
            "input_id", "position_id", name="uq_xray_input_positions_input_id_position_id"
        ),
        UniqueConstraint("input_id", "ordinal", name="uq_xray_input_positions_input_id_ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 9999", name="ordinal_bound"),
        payload_bound("canonical_position"),
        Index("ix_xray_position_parent", "input_id", "id"),
        Index(
            "ix_xray_input_positions_pending",
            "input_id",
            "id",
            postgresql_where=text("canonical_position <> '\\x'::bytea"),
        ),
    )
    input_id: Mapped[UUID] = mapped_column()
    position_id: Mapped[UUID] = mapped_column(
        ForeignKey("snapshot_positions.id", ondelete="RESTRICT")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    canonical_position: Mapped[bytes] = mapped_column(LargeBinary)


class XrayInputCashModel(SourceOwned):
    __tablename__ = "xray_input_cash"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "xray_input_snapshots"),
        UniqueConstraint("input_id", "cash_id", name="uq_xray_input_cash_input_id_cash_id"),
        UniqueConstraint("input_id", "ordinal", name="uq_xray_input_cash_input_id_ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 31", name="ordinal_bound"),
        payload_bound("canonical_cash"),
        Index("ix_xray_cash_parent", "input_id", "id"),
        Index(
            "ix_xray_input_cash_pending",
            "input_id",
            "id",
            postgresql_where=text("canonical_cash <> '\\x'::bytea"),
        ),
    )
    input_id: Mapped[UUID] = mapped_column()
    cash_id: Mapped[UUID] = mapped_column(ForeignKey("snapshot_cash.id", ondelete="RESTRICT"))
    ordinal: Mapped[int] = mapped_column(Integer)
    canonical_cash: Mapped[bytes] = mapped_column(LargeBinary)


class XrayInputDependencyModel(SourceOwned):
    __tablename__ = "xray_input_dependencies"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "xray_input_snapshots"),
        UniqueConstraint(
            "input_id", "reference_id", name="uq_xray_input_dependencies_input_id_reference_id"
        ),
        owner_fk("fx_snapshot_id", "fx_snapshots"),
        owner_fk("entity_evidence_version_id", "entity_evidence_versions"),
        owner_fk("classification_snapshot_id", "classification_snapshots"),
        owner_fk("fund_definition_id", "fund_definitions"),
        owner_fk("fund_mapping_id", "fund_source_mappings"),
        owner_fk("constituent_snapshot_id", "constituent_snapshots"),
        owner_fk("threshold_policy_id", "xray_policy_versions"),
        CheckConstraint(
            "num_nonnulls(valuation_run_id,reconciliation_run_id,broker_sourc"
            "e_record_id,threshold_policy_id,fx_snapshot_id,"
            "entity_evidence_version_id,classification_snapshot_id,fund_defin"
            "ition_id,fund_mapping_id,constituent_snapshot_id)=1",
            name="one_source",
        ),
        CheckConstraint(
            "(provider_id IS NULL) = (license_version_id IS NULL)", name="license_pair"
        ),
        CheckConstraint(
            "(provider_id IS NULL) = (valuation_run_id IS NOT NULL OR reconci"
            "liation_run_id IS NOT NULL OR broker_source_record_id IS NOT NUL"
            "L OR threshold_policy_id IS NOT NULL)",
            name="internal_license_shape",
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        payload_bound("canonical_reference"),
        Index("ix_xray_dependency_parent", "input_id", "id"),
        Index("ix_xray_dependency_fx", "fx_snapshot_id", "input_id", "id"),
        Index("ix_xray_dependency_entity", "entity_evidence_version_id", "input_id", "id"),
        Index("ix_xray_dependency_classification", "classification_snapshot_id", "input_id", "id"),
        Index("ix_xray_dependency_definition", "fund_definition_id", "input_id", "id"),
        Index("ix_xray_dependency_mapping", "fund_mapping_id", "input_id", "id"),
        Index("ix_xray_dependency_constituents", "constituent_snapshot_id", "input_id", "id"),
        Index(
            "ix_xray_input_dependencies_pending",
            "input_id",
            "id",
            postgresql_where=text("canonical_reference <> '\\x'::bytea"),
        ),
    )
    input_id: Mapped[UUID] = mapped_column()
    reference_id: Mapped[UUID] = mapped_column()
    valuation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )
    reconciliation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT")
    )
    broker_source_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    threshold_policy_id: Mapped[UUID | None] = mapped_column()
    fx_snapshot_id: Mapped[UUID | None] = mapped_column()
    entity_evidence_version_id: Mapped[UUID | None] = mapped_column()
    classification_snapshot_id: Mapped[UUID | None] = mapped_column()
    fund_definition_id: Mapped[UUID | None] = mapped_column()
    fund_mapping_id: Mapped[UUID | None] = mapped_column()
    constituent_snapshot_id: Mapped[UUID | None] = mapped_column()
    provider_id: Mapped[UUID | None] = mapped_column()
    license_version_id: Mapped[UUID | None] = mapped_column()
    canonical_reference: Mapped[bytes] = mapped_column(LargeBinary)


class XrayRunModel(SourceOwned):
    __tablename__ = "xray_runs"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "xray_input_snapshots"),
        owner_fk("analytics_run_id", "analytics_runs"),
        UniqueConstraint("input_id", name="uq_xray_runs_input_id"),
        UniqueConstraint("analytics_run_id", name="uq_xray_runs_analytics_run_id"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("sealed_at IS NULL OR sealed_at >= calculated_at", name="sealed_order"),
        payload_bound("canonical_summary"),
        payload_bound("canonical_reconciliation"),
        payload_bound("canonical_exact_state"),
        Index("ix_xray_run_parent", "input_id", "id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    analytics_run_id: Mapped[UUID] = mapped_column()
    calculated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))
    canonical_summary: Mapped[bytes] = mapped_column(LargeBinary)
    canonical_reconciliation: Mapped[bytes] = mapped_column(LargeBinary)
    canonical_exact_state: Mapped[bytes] = mapped_column(LargeBinary)


class XrayInputSourceSelectionModel(SourceOwned):
    __tablename__ = "xray_input_source_selections"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "xray_input_snapshots"),
        UniqueConstraint("input_id", "key", name="uq_xray_input_source_selections_input_id_key"),
        payload_bound("canonical_selection"),
        Index("ix_xray_selection_parent", "input_id", "id"),
        Index(
            "ix_xray_input_source_selections_pending",
            "input_id",
            "id",
            postgresql_where=text("canonical_selection <> '\\x'::bytea"),
        ),
    )
    input_id: Mapped[UUID] = mapped_column()
    key: Mapped[str] = mapped_column(String(1024))
    canonical_selection: Mapped[bytes] = mapped_column(LargeBinary)


class XraySelectionCandidateModel(SourceOwned):
    __tablename__ = "xray_selection_candidates"
    __table_args__ = (
        owned(),
        owner_fk("selection_id", "xray_input_source_selections"),
        owner_fk("dependency_id", "xray_input_dependencies"),
        UniqueConstraint(
            "selection_id",
            "evidence_id",
            name="uq_xray_selection_candidates_selection_id_evidence_id",
        ),
        Index("ix_xray_selection_candidate_parent", "selection_id", "id"),
    )
    selection_id: Mapped[UUID] = mapped_column()
    dependency_id: Mapped[UUID] = mapped_column()
    evidence_id: Mapped[UUID] = mapped_column()
    selected: Mapped[bool] = mapped_column(Boolean)


class XrayRunSourceModel(SourceOwned):
    __tablename__ = "xray_run_sources"
    __table_args__ = (
        owned(),
        owner_fk("run_id", "xray_runs"),
        owner_fk("dependency_id", "xray_input_dependencies"),
        UniqueConstraint("run_id", "ordinal", name="uq_xray_run_sources_run_id_ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        payload_bound("canonical_use"),
        Index("ix_xray_run_source_parent", "run_id", "id"),
        Index(
            "ix_xray_run_sources_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_use <> '\\x'::bytea"),
        ),
    )
    run_id: Mapped[UUID] = mapped_column()
    dependency_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    canonical_use: Mapped[bytes] = mapped_column(LargeBinary)


class XrayRunPayloadFields(SourceOwned):
    __abstract__ = True
    run_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary)


def run_payload_constraints() -> tuple[object, ...]:
    return (
        owned(),
        owner_fk("run_id", "xray_runs"),
        UniqueConstraint("run_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        payload_bound("canonical_payload"),
    )


class XrayDimensionModel(XrayRunPayloadFields):
    __tablename__ = "xray_dimensions"
    __table_args__ = (
        *run_payload_constraints(),
        Index("ix_xray_dimensions_parent", "run_id", "id"),
        Index(
            "ix_xray_dimensions_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    dimension: Mapped[str] = mapped_column(String(20))


class XrayWarningModel(XrayRunPayloadFields):
    __tablename__ = "xray_warnings"
    __table_args__ = (
        *run_payload_constraints(),
        Index("ix_xray_warnings_parent", "run_id", "id"),
        Index(
            "ix_xray_warnings_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )


class XrayResidualModel(XrayRunPayloadFields):
    __tablename__ = "xray_residuals"
    __table_args__ = (
        *run_payload_constraints(),
        Index("ix_xray_residuals_parent", "run_id", "id"),
        Index(
            "ix_xray_residuals_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    consumer_key: Mapped[str] = mapped_column(String(2048))


class XrayClassificationDecisionModel(XrayRunPayloadFields):
    __tablename__ = "xray_classification_decisions"
    __table_args__ = (
        *run_payload_constraints(),
        Index("ix_xray_classification_decisions_parent", "run_id", "id"),
        Index(
            "ix_xray_classification_decisions_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    key: Mapped[str] = mapped_column(String(2048))


class XrayDirectPositionModel(XrayRunPayloadFields):
    __tablename__ = "xray_direct_positions"
    __table_args__ = (
        *run_payload_constraints(),
        Index("ix_xray_direct_positions_parent", "run_id", "id"),
        Index(
            "ix_xray_direct_positions_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    position_id: Mapped[UUID] = mapped_column(
        ForeignKey("snapshot_positions.id", ondelete="RESTRICT")
    )


class XrayHeldFundModel(XrayRunPayloadFields):
    __tablename__ = "xray_held_funds"
    __table_args__ = (
        *run_payload_constraints(),
        Index("ix_xray_held_funds_parent", "run_id", "id"),
        Index(
            "ix_xray_held_funds_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))


class XrayExposureModel(XrayRunPayloadFields):
    __tablename__ = "xray_exposures"
    __table_args__ = (
        *run_payload_constraints(),
        UniqueConstraint(
            "run_id",
            "dimension",
            "bucket_key",
            name="uq_xray_exposures_run_id_dimension_bucket_key",
        ),
        Index("ix_xray_exposure_page", "run_id", "dimension", "ordinal", "id"),
        Index("ix_xray_exposure_parent", "run_id", "id"),
        Index(
            "ix_xray_exposures_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    dimension: Mapped[str] = mapped_column(String(20))
    bucket_key: Mapped[str | None] = mapped_column(String(120))


class XrayExposurePathModel(XrayRunPayloadFields):
    __tablename__ = "xray_exposure_paths"
    __table_args__ = (
        *run_payload_constraints(),
        UniqueConstraint("run_id", "path_key", name="uq_xray_exposure_paths_run_id_path_key"),
        CheckConstraint(
            "cardinality(identity_decision_ids) <= 256 AND cardinality(source"
            "_reference_ids) <= 256",
            name="proof_bound",
        ),
        CheckConstraint("root_key ~ '^(position|cash):[0-9a-f-]{36}$'", name="root_key_format"),
        Index("ix_xray_path_parent", "run_id", "id"),
        Index(
            "ix_xray_exposure_paths_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    path_key: Mapped[str] = mapped_column(String(2048))
    root_key: Mapped[str] = mapped_column(String(45))
    identity_decision_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid()))
    source_reference_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid()))


class XrayPathEdgeModel(SourceOwned):
    __tablename__ = "xray_path_edges"
    __table_args__ = (
        owned(),
        owner_fk("path_id", "xray_exposure_paths"),
        owner_fk("fund_mapping_id", "fund_source_mappings"),
        owner_fk("constituent_snapshot_id", "constituent_snapshots"),
        owner_fk("holding_id", "constituent_holdings"),
        UniqueConstraint("path_id", "ordinal", name="uq_xray_path_edges_path_id_ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 3", name="ordinal_bound"),
        payload_bound("canonical_edge"),
        Index("ix_xray_edge_parent", "path_id", "id"),
        Index(
            "ix_xray_path_edges_pending",
            "path_id",
            "id",
            postgresql_where=text("canonical_edge <> '\\x'::bytea"),
        ),
    )
    path_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    fund_mapping_id: Mapped[UUID] = mapped_column()
    constituent_snapshot_id: Mapped[UUID] = mapped_column()
    holding_id: Mapped[UUID | None] = mapped_column()
    canonical_edge: Mapped[bytes] = mapped_column(LargeBinary)


class XrayExposurePathBucketModel(SourceOwned):
    __tablename__ = "xray_exposure_path_buckets"
    __table_args__ = (
        owned(),
        owner_fk("path_id", "xray_exposure_paths"),
        owner_fk("exposure_id", "xray_exposures"),
        UniqueConstraint(
            "path_id", "dimension", name="uq_xray_exposure_path_buckets_path_id_dimension"
        ),
        Index("ix_xray_path_bucket_parent", "path_id", "id"),
        Index("ix_xray_path_bucket_page", "exposure_id", "ordinal", "id"),
    )
    path_id: Mapped[UUID] = mapped_column()
    exposure_id: Mapped[UUID] = mapped_column()
    dimension: Mapped[str] = mapped_column(String(20))
    ordinal: Mapped[int] = mapped_column(Integer)


class XrayFundCompositionModel(XrayRunPayloadFields):
    __tablename__ = "xray_fund_compositions"
    __table_args__ = (
        *run_payload_constraints(),
        UniqueConstraint(
            "run_id", "instrument_id", name="uq_xray_fund_compositions_run_id_instrument_id"
        ),
        CheckConstraint("position_count BETWEEN 1 AND 10000", name="position_count_bound"),
        Index("ix_xray_fund_parent", "run_id", "id"),
        Index(
            "ix_xray_fund_compositions_pending",
            "run_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    composition_root_key: Mapped[str] = mapped_column(String(45))
    position_count: Mapped[int] = mapped_column(Integer)


class XrayFundEntityModel(SourceOwned):
    __tablename__ = "xray_fund_entities"
    __table_args__ = (
        owned(),
        owner_fk("composition_id", "xray_fund_compositions"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint(
            "composition_id", "entity_id", name="uq_xray_fund_entities_composition_id_entity_id"
        ),
        UniqueConstraint(
            "composition_id", "ordinal", name="uq_xray_fund_entities_composition_id_ordinal"
        ),
        coefficient_bound("relative_coefficient"),
        payload_bound("canonical_payload"),
        Index("ix_xray_fund_entity_parent", "composition_id", "id"),
        Index(
            "ix_xray_fund_entities_pending",
            "composition_id",
            "id",
            postgresql_where=text("canonical_payload <> '\\x'::bytea"),
        ),
    )
    composition_id: Mapped[UUID] = mapped_column()
    entity_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    relative_coefficient: Mapped[str | None] = mapped_column(String(250))
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary)


class XrayCollectionBindingModel(SourceOwned):
    __tablename__ = "xray_collection_bindings"
    __table_args__ = (
        owned(),
        owner_fk("collection_id", "collection_query_snapshots"),
        owner_fk("run_id", "xray_runs"),
        owner_fk("constituent_snapshot_id", "constituent_snapshots"),
        UniqueConstraint("collection_id", name="uq_xray_collection_bindings_collection_id"),
        CheckConstraint("num_nonnulls(run_id,constituent_snapshot_id)=1", name="one_parent"),
        Index("ix_xray_collection_run", "run_id", "id"),
        Index("ix_xray_collection_source", "constituent_snapshot_id", "id"),
    )
    collection_id: Mapped[UUID] = mapped_column()
    run_id: Mapped[UUID | None] = mapped_column()
    constituent_snapshot_id: Mapped[UUID | None] = mapped_column()


class EtfOverlapPairModel(SourceOwned):
    __tablename__ = "etf_overlap_pairs"
    __table_args__ = (
        owned(),
        owner_fk("collection_id", "collection_query_snapshots"),
        owner_fk("run_id", "xray_runs"),
        owner_fk("left_composition_id", "xray_fund_compositions"),
        owner_fk("right_composition_id", "xray_fund_compositions"),
        UniqueConstraint(
            "collection_id",
            "left_composition_id",
            "right_composition_id",
            name="uq_etf_overlap_pairs_collection_id_left_composition_id_c0d32d48",
        ),
        UniqueConstraint(
            "collection_id", "ordinal", name="uq_etf_overlap_pairs_collection_id_ordinal"
        ),
        CheckConstraint("left_composition_id <> right_composition_id", name="distinct_pair"),
        payload_bound("canonical_payload"),
        Index("ix_xray_pair_collection", "collection_id", "id"),
        Index("ix_xray_pair_run", "run_id", "id"),
    )
    collection_id: Mapped[UUID] = mapped_column()
    run_id: Mapped[UUID] = mapped_column()
    left_composition_id: Mapped[UUID] = mapped_column()
    right_composition_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary)


class EtfOverlapEntityModel(SourceOwned):
    __tablename__ = "etf_overlap_entities"
    __table_args__ = (
        owned(),
        owner_fk("collection_id", "collection_query_snapshots"),
        owner_fk("pair_id", "etf_overlap_pairs"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint("pair_id", "entity_id", name="uq_etf_overlap_entities_pair_id_entity_id"),
        UniqueConstraint("pair_id", "ordinal", name="uq_etf_overlap_entities_pair_id_ordinal"),
        payload_bound("canonical_payload"),
        Index("ix_xray_common_collection", "collection_id", "id"),
        Index("ix_xray_common_parent", "pair_id", "id"),
    )
    collection_id: Mapped[UUID] = mapped_column()
    pair_id: Mapped[UUID] = mapped_column()
    entity_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    canonical_payload: Mapped[bytes] = mapped_column(LargeBinary)


class XrayRetentionEventModel(SourceOwned):
    __tablename__ = "xray_retention_events"
    __table_args__ = (
        owned(),
        owner_fk("input_id", "xray_input_snapshots"),
        owner_fk("dependency_id", "xray_input_dependencies"),
        UniqueConstraint(
            "input_id", "dependency_id", name="uq_xray_retention_events_input_id_dependency_id"
        ),
        Index("ix_xray_retention_input", "input_id", "id"),
    )
    input_id: Mapped[UUID] = mapped_column()
    dependency_id: Mapped[UUID] = mapped_column()
    expired_at: Mapped[datetime] = mapped_column(UTCDateTime())


XRAY_RUN_MODELS = (
    XrayInputSnapshotModel,
    XrayInputPositionModel,
    XrayInputCashModel,
    XrayInputDependencyModel,
    XrayRunModel,
    XrayInputSourceSelectionModel,
    XraySelectionCandidateModel,
    XrayRunSourceModel,
    XrayDimensionModel,
    XrayWarningModel,
    XrayResidualModel,
    XrayClassificationDecisionModel,
    XrayDirectPositionModel,
    XrayHeldFundModel,
    XrayExposureModel,
    XrayExposurePathModel,
    XrayPathEdgeModel,
    XrayExposurePathBucketModel,
    XrayFundCompositionModel,
    XrayFundEntityModel,
    XrayCollectionBindingModel,
    EtfOverlapPairModel,
    EtfOverlapEntityModel,
    XrayRetentionEventModel,
)
