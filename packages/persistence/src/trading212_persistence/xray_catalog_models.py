"""Typed catalog and licensed enrichment rows for Portfolio X-ray.

Constituent snapshots deliberately do not inherit daily market-series fields.
Identity tombstones survive licensed payload removal; no untyped source foreign key.
"""

from __future__ import annotations

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
)
from sqlalchemy.orm import Mapped, mapped_column

from .source_models import SourceOwned, owned
from .source_models import owner_fk as source_owner_fk
from .types import ExactNumeric, UTCDateTime


def owner_fk(column: str, table: str) -> ForeignKeyConstraint:
    constraint = source_owner_fk(column, table)
    constraint.name = f"xray_{column}_{table}_fk"
    return constraint


def licensed() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "provider_id", "license_version_id"],
        [
            "provider_license_versions.owner_id",
            "provider_license_versions.provider_id",
            "provider_license_versions.id",
        ],
        ondelete="RESTRICT",
    )


def evidence_constraints() -> tuple[object, ...]:
    return (
        owned(),
        licensed(),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("expires_at > first_observed_at", name="retention_interval"),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        CheckConstraint(
            "revision_order IS NULL OR revision_order >= 0", name="revision_nonnegative"
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
    )


class XrayEvidenceFields(SourceOwned):
    __abstract__ = True
    provider_id: Mapped[UUID] = mapped_column()
    license_version_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revision_order: Mapped[int | None] = mapped_column(BigInteger)
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class XrayTaxonomyModel(SourceOwned):
    __tablename__ = "xray_taxonomies"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id", "key", "version", name="uq_xray_taxonomies_owner_id_key_version"
        ),
        CheckConstraint(
            "dimension IN ('sector','industry','country','region','currency')",
            name="dimension_allowed",
        ),
    )
    key: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(120))
    dimension: Mapped[str] = mapped_column(String(20))


class XrayPolicyVersionModel(SourceOwned):
    __tablename__ = "xray_policy_versions"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "key",
            "version",
            name="uq_xray_policy_versions_owner_id_account_id_key_version",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "octet_length(canonical_policy) BETWEEN 1 AND 2097152", name="payload_bound"
        ),
        Index(
            "ix_xray_policy_selection",
            "owner_id",
            "account_id",
            "effective_at",
            "first_observed_at",
            "id",
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(120))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    canonical_policy: Mapped[bytes] = mapped_column(LargeBinary)
    content_digest: Mapped[str] = mapped_column(String(64))


class XrayPolicyTaxonomyModel(SourceOwned):
    __tablename__ = "xray_policy_taxonomies"
    __table_args__ = (
        owned(),
        owner_fk("policy_id", "xray_policy_versions"),
        owner_fk("taxonomy_id", "xray_taxonomies"),
        UniqueConstraint(
            "policy_id", "taxonomy_id", name="uq_xray_policy_taxonomies_policy_id_taxonomy_id"
        ),
    )
    policy_id: Mapped[UUID] = mapped_column()
    taxonomy_id: Mapped[UUID] = mapped_column()


class EntityEvidenceVersionModel(XrayEvidenceFields):
    __tablename__ = "entity_evidence_versions"
    __table_args__ = (
        *evidence_constraints(),
        UniqueConstraint(
            "owner_id",
            "provider_id",
            "key",
            "revision_order",
            name="uq_entity_evidence_versions_owner_id_provider_id_key_r_4f7e99fd",
        ),
        CheckConstraint(
            "revision_order IS NOT NULL AND revision_order >= 1", name="revision_required"
        ),
        Index("ix_entity_evidence_expiry", "expires_at", "id"),
        Index(
            "ix_entity_evidence_selection", "owner_id", "effective_at", "first_observed_at", "id"
        ),
    )
    key: Mapped[str] = mapped_column(String(120))


class EconomicEntityModel(SourceOwned):
    __tablename__ = "economic_entities"
    __table_args__ = (
        owned(),
        UniqueConstraint("owner_id", "key", name="uq_economic_entities_owner_id_key"),
    )
    key: Mapped[str] = mapped_column(String(120))


class EntityEvidenceReferenceModel(SourceOwned):
    __tablename__ = "entity_evidence_references"
    __table_args__ = (
        owned(),
        owner_fk("evidence_version_id", "entity_evidence_versions"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint(
            "evidence_version_id",
            "ordinal",
            name="uq_entity_evidence_references_evidence_version_id_ordinal",
        ),
        CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        CheckConstraint("kind IN ('entity','instrument_mapping')", name="kind_allowed"),
        CheckConstraint(
            "(kind = 'entity' AND instrument_id IS NULL AND listing_id IS NULL) OR "
            "(kind = 'instrument_mapping' AND instrument_id IS NOT NULL)",
            name="subject_shape",
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        Index("ix_entity_reference_parent", "evidence_version_id", "id"),
        Index("ix_entity_reference_subject", "owner_id", "instrument_id", "listing_id", "id"),
    )
    evidence_version_id: Mapped[UUID] = mapped_column()
    entity_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    ordinal: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    display_name: Mapped[str | None] = mapped_column(String(300))
    lei: Mapped[str | None] = mapped_column(String(20))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class ShareClassModel(SourceOwned):
    __tablename__ = "share_classes"
    __table_args__ = (
        owned(),
        owner_fk("evidence_version_id", "entity_evidence_versions"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint(
            "evidence_version_id",
            "instrument_id",
            "class_key",
            name="uq_share_classes_evidence_version_id_instrument_id_class_key",
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        Index("ix_share_class_parent", "evidence_version_id", "id"),
        Index("ix_share_class_subject", "owner_id", "instrument_id", "id"),
    )
    evidence_version_id: Mapped[UUID] = mapped_column()
    entity_id: Mapped[UUID] = mapped_column()
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    class_key: Mapped[str | None] = mapped_column(String(120))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class InstrumentEntityRelationshipModel(SourceOwned):
    __tablename__ = "instrument_entity_relationships"
    __table_args__ = (
        owned(),
        owner_fk("evidence_version_id", "entity_evidence_versions"),
        owner_fk("entity_id", "economic_entities"),
        owner_fk("parent_entity_id", "economic_entities"),
        owner_fk("share_class_id", "share_classes"),
        CheckConstraint(
            "kind IN ('listing_of','share_class_of','depositary_receipt_of','issuer_parent')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "(kind = 'listing_of' AND listing_id IS NOT NULL AND instrument_id IS NOT NULL "
            "AND share_class_id IS NULL AND entity_id IS NULL AND underlying_"
            "instrument_id IS NULL AND parent_entity_id IS NULL) OR "
            "(kind = 'share_class_of' AND instrument_id IS NOT NULL AND share"
            "_class_id IS NOT NULL AND entity_id IS NOT NULL "
            "AND listing_id IS NULL AND underlying_instrument_id IS NULL AND "
            "parent_entity_id IS NULL) OR "
            "(kind = 'depositary_receipt_of' AND instrument_id IS NOT NULL AN"
            "D underlying_instrument_id IS NOT NULL AND entity_id IS NOT NULL"
            " "
            "AND instrument_id <> underlying_instrument_id AND listing_id IS "
            "NULL AND share_class_id IS NULL AND parent_entity_id IS NULL) OR"
            " "
            "(kind = 'issuer_parent' AND entity_id IS NOT NULL AND parent_ent"
            "ity_id IS NOT NULL AND entity_id <> parent_entity_id "
            "AND instrument_id IS NULL AND underlying_instrument_id IS NULL A"
            "ND listing_id IS NULL AND share_class_id IS NULL)",
            name="endpoint_shape",
        ),
        CheckConstraint(
            "units_per_receipt IS NULL OR (kind = 'depositary_receipt_of' AND"
            " units_per_receipt > 0)",
            name="receipt_ratio",
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        Index("ix_entity_relationship_parent", "evidence_version_id", "id"),
        Index("ix_entity_relationship_subject", "owner_id", "instrument_id", "id"),
    )
    evidence_version_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    share_class_id: Mapped[UUID | None] = mapped_column()
    entity_id: Mapped[UUID | None] = mapped_column()
    underlying_instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    parent_entity_id: Mapped[UUID | None] = mapped_column()
    units_per_receipt: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class FundDefinitionModel(XrayEvidenceFields):
    __tablename__ = "fund_definitions"
    __table_args__ = (
        *evidence_constraints(),
        owner_fk("share_class_id", "share_classes"),
        UniqueConstraint(
            "owner_id",
            "key",
            "revision_order",
            name="uq_fund_definitions_owner_id_key_revision_order",
        ),
        CheckConstraint(
            "revision_order IS NOT NULL AND revision_order >= 1", name="revision_required"
        ),
        Index("ix_fund_definition_subject", "owner_id", "instrument_id", "effective_at", "id"),
        Index("ix_fund_definition_expiry", "expires_at", "id"),
    )
    key: Mapped[str] = mapped_column(String(120))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    share_class_id: Mapped[UUID | None] = mapped_column()
    fund_type: Mapped[str | None] = mapped_column(String(120))
    evidence_key: Mapped[str | None] = mapped_column(String(120))


class FundSourceMappingModel(XrayEvidenceFields):
    __tablename__ = "fund_source_mappings"
    __table_args__ = (
        *evidence_constraints(),
        owner_fk("fund_definition_id", "fund_definitions"),
        UniqueConstraint(
            "owner_id",
            "provider_id",
            "provider_fund_key",
            "revision_order",
            name="uq_fund_source_mappings_owner_id_provider_id_provider__21a67a0a",
        ),
        UniqueConstraint(
            "owner_id",
            "provider_id",
            "license_version_id",
            "id",
            name="uq_fund_source_mappings_owner_id_provider_id_license_v_bef58582",
        ),
        CheckConstraint(
            "revision_order IS NOT NULL AND revision_order >= 1", name="revision_required"
        ),
        Index("ix_fund_mapping_parent", "fund_definition_id", "effective_at", "id"),
        Index("ix_fund_mapping_expiry", "expires_at", "id"),
    )
    fund_definition_id: Mapped[UUID] = mapped_column()
    provider_fund_key: Mapped[str | None] = mapped_column(String(120))
    evidence_key: Mapped[str | None] = mapped_column(String(120))


class XrayProviderSnapshotFields(XrayEvidenceFields):
    __abstract__ = True
    adapter_version: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(120))
    source_revision: Mapped[str] = mapped_column(String(120))
    economic_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    synthetic: Mapped[bool] = mapped_column(Boolean)
    row_count: Mapped[int] = mapped_column(Integer)
    quality: Mapped[str] = mapped_column(String(20))


def provider_snapshot_constraints(table: str) -> tuple[object, ...]:
    return (
        *evidence_constraints(),
        UniqueConstraint("owner_id", "content_digest", name=f"uq_{table}_owner_content"),
        CheckConstraint(
            "economic_digest ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'",
            name="request_digest_format",
        ),
        CheckConstraint("row_count BETWEEN 0 AND 100000", name="row_count_bound"),
    )


class ClassificationSnapshotModel(XrayProviderSnapshotFields):
    __tablename__ = "classification_snapshots"
    __table_args__ = (
        *provider_snapshot_constraints("classification_snapshots"),
        owner_fk("taxonomy_id", "xray_taxonomies"),
        Index(
            "ix_classification_snapshot_selection",
            "owner_id",
            "taxonomy_id",
            "effective_at",
            "first_observed_at",
            "id",
        ),
        Index("ix_classification_snapshot_expiry", "expires_at", "id"),
    )
    taxonomy_id: Mapped[UUID] = mapped_column()


class ClassificationSnapshotInstrumentModel(SourceOwned):
    __tablename__ = "classification_snapshot_instruments"
    __table_args__ = (
        owned(),
        owner_fk("snapshot_id", "classification_snapshots"),
        UniqueConstraint(
            "snapshot_id",
            "instrument_id",
            name="uq_classification_snapshot_instruments_snapshot_id_ins_fe7b5049",
        ),
        UniqueConstraint(
            "snapshot_id",
            "ordinal",
            name="uq_classification_snapshot_instruments_snapshot_id_ordinal",
        ),
        CheckConstraint("ordinal BETWEEN 0 AND 99", name="ordinal_bound"),
        Index("ix_classification_request_subject", "owner_id", "instrument_id", "snapshot_id"),
        Index("ix_classification_instrument_parent", "snapshot_id", "id"),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    ordinal: Mapped[int] = mapped_column(Integer)


class ClassificationAssignmentModel(SourceOwned):
    __tablename__ = "classification_assignments"
    __table_args__ = (
        owned(),
        owner_fk("snapshot_id", "classification_snapshots"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint(
            "snapshot_id", "source_key", name="uq_classification_assignments_snapshot_id_source_key"
        ),
        CheckConstraint(
            "dimension IN ('sector','industry','country','region','currency')",
            name="dimension_allowed",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_at", name="validity"),
        Index("ix_classification_assignment_parent", "snapshot_id", "id"),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    entity_id: Mapped[UUID | None] = mapped_column()
    source_key: Mapped[str] = mapped_column(String(120))
    dimension: Mapped[str] = mapped_column(String(20))
    bucket_key: Mapped[str | None] = mapped_column(String(120))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    evidence_key: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20))


class ClassificationSnapshotAssignmentModel(SourceOwned):
    __tablename__ = "classification_snapshot_assignments"
    __table_args__ = (
        owned(),
        owner_fk("snapshot_id", "classification_snapshots"),
        owner_fk("assignment_id", "classification_assignments"),
        UniqueConstraint(
            "snapshot_id",
            "assignment_id",
            name="uq_classification_snapshot_assignments_snapshot_id_ass_feb45c51",
        ),
        UniqueConstraint(
            "snapshot_id",
            "ordinal",
            name="uq_classification_snapshot_assignments_snapshot_id_ordinal",
        ),
        CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        Index("ix_classification_member_parent", "snapshot_id", "id"),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    assignment_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)


class ConstituentSnapshotModel(XrayProviderSnapshotFields):
    __tablename__ = "constituent_snapshots"
    __table_args__ = (
        *provider_snapshot_constraints("constituent_snapshots"),
        owner_fk("fund_mapping_id", "fund_source_mappings"),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id", "fund_mapping_id"],
            [
                "fund_source_mappings.owner_id",
                "fund_source_mappings.provider_id",
                "fund_source_mappings.license_version_id",
                "fund_source_mappings.id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(known_weight IS NULL AND unresolved_weight IS NULL AND cash_weight IS NULL) OR "
            "(known_weight IS NOT NULL AND unresolved_weight IS NOT NULL AND "
            "cash_weight IS NOT NULL "
            "AND known_weight BETWEEN 0 AND 1 AND unresolved_weight BETWEEN 0"
            " AND 1 AND cash_weight BETWEEN 0 AND 1 "
            "AND known_weight + unresolved_weight + cash_weight <= 1)",
            name="coverage_bound",
        ),
        Index(
            "ix_constituent_snapshot_selection",
            "owner_id",
            "fund_mapping_id",
            "effective_at",
            "first_observed_at",
            "id",
        ),
        Index("ix_constituent_snapshot_expiry", "expires_at", "id"),
    )
    fund_mapping_id: Mapped[UUID] = mapped_column()
    known_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    unresolved_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    cash_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class ConstituentHoldingModel(SourceOwned):
    __tablename__ = "constituent_holdings"
    __table_args__ = (
        owned(),
        owner_fk("snapshot_id", "constituent_snapshots"),
        owner_fk("entity_id", "economic_entities"),
        UniqueConstraint(
            "snapshot_id", "source_key", name="uq_constituent_holdings_snapshot_id_source_key"
        ),
        UniqueConstraint(
            "snapshot_id", "ordinal", name="uq_constituent_holdings_snapshot_id_ordinal"
        ),
        CheckConstraint("ordinal BETWEEN 0 AND 99999", name="ordinal_bound"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight_bound"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bound"
        ),
        CheckConstraint(
            "(state = 'resolved' AND (instrument_id IS NOT NULL OR entity_id IS NOT NULL)) OR "
            "(state IN ('cash','unresolved') AND instrument_id IS NULL AND entity_id IS NULL)",
            name="holding_shape",
        ),
        Index("ix_constituent_holding_parent", "snapshot_id", "id"),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str] = mapped_column(String(120))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID | None] = mapped_column()
    state: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    name: Mapped[str | None] = mapped_column(String(300))
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    evidence_key: Mapped[str | None] = mapped_column(String(120))


XRAY_CATALOG_MODELS = (
    XrayTaxonomyModel,
    XrayPolicyVersionModel,
    XrayPolicyTaxonomyModel,
    EntityEvidenceVersionModel,
    EconomicEntityModel,
    EntityEvidenceReferenceModel,
    ShareClassModel,
    InstrumentEntityRelationshipModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    ClassificationSnapshotModel,
    ClassificationSnapshotInstrumentModel,
    ClassificationAssignmentModel,
    ClassificationSnapshotAssignmentModel,
    ConstituentSnapshotModel,
    ConstituentHoldingModel,
)
