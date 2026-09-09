"""Closed X-ray command receipts and licensed enrichment expiry identities."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .source_models import SourceOwned, owned
from .source_models import owner_fk as source_owner_fk
from .types import UTCDateTime


def owner_fk(column: str, table: str) -> ForeignKeyConstraint:
    constraint = source_owner_fk(column, table)
    constraint.name = f"xray_{column}_{table}_fk"
    return constraint


COMMAND_KINDS = (
    "'policy.register','entity.register','fund.register','fund_mappin"
    "g.register','classification.ingest','constituent.ingest'"
)


class XrayCommandIdentityModel(SourceOwned):
    __tablename__ = "xray_command_identities"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_xray_command_identities_owner_id_idempotency_key",
        ),
        CheckConstraint(f"kind IN ({COMMAND_KINDS})", name="kind_allowed"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    kind: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_digest: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[UUID] = mapped_column()
    actor_principal_id: Mapped[str] = mapped_column(String(120))
    correlation_id: Mapped[str] = mapped_column(String(100))


class XrayAuditEventModel(SourceOwned):
    __tablename__ = "xray_audit_events"
    __table_args__ = (
        owned(),
        owner_fk("command_id", "xray_command_identities"),
        UniqueConstraint("command_id", name="uq_xray_audit_events_command_id"),
        CheckConstraint(f"kind IN ({COMMAND_KINDS})", name="kind_allowed"),
    )
    command_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[UUID] = mapped_column()
    actor_principal_id: Mapped[str] = mapped_column(String(120))
    correlation_id: Mapped[str] = mapped_column(String(100))


class EnrichmentReference(SourceOwned):
    __abstract__ = True
    entity_evidence_version_id: Mapped[UUID | None] = mapped_column()
    classification_snapshot_id: Mapped[UUID | None] = mapped_column()
    fund_definition_id: Mapped[UUID | None] = mapped_column()
    fund_mapping_id: Mapped[UUID | None] = mapped_column()


def enrichment_references() -> tuple[object, ...]:
    return (
        owned(),
        owner_fk("entity_evidence_version_id", "entity_evidence_versions"),
        owner_fk("classification_snapshot_id", "classification_snapshots"),
        owner_fk("fund_definition_id", "fund_definitions"),
        owner_fk("fund_mapping_id", "fund_source_mappings"),
        CheckConstraint(
            "num_nonnulls(entity_evidence_version_id,classification_snapshot_id,"
            "fund_definition_id,fund_mapping_id) = 1",
            name="one_source",
        ),
    )


class EnrichmentRetrievalOccurrenceModel(EnrichmentReference):
    __tablename__ = "enrichment_retrieval_occurrences"
    __table_args__ = (
        *enrichment_references(),
        Index("ix_enrichment_receipt_entity", "entity_evidence_version_id", "retrieved_at", "id"),
        Index(
            "ix_enrichment_receipt_classification",
            "classification_snapshot_id",
            "retrieved_at",
            "id",
        ),
        Index("ix_enrichment_receipt_definition", "fund_definition_id", "retrieved_at", "id"),
        Index("ix_enrichment_receipt_mapping", "fund_mapping_id", "retrieved_at", "id"),
    )
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime())


class EnrichmentRetentionWorkModel(EnrichmentReference):
    __tablename__ = "enrichment_retention_work"
    __table_args__ = (
        *enrichment_references(),
        *(
            UniqueConstraint(name)
            for name in (
                "entity_evidence_version_id",
                "classification_snapshot_id",
                "fund_definition_id",
                "fund_mapping_id",
            )
        ),
        CheckConstraint("phase IN ('copies','payloads','complete')", name="phase_allowed"),
        CheckConstraint(
            "(phase = 'complete') = (completed_at IS NOT NULL)", name="completion_shape"
        ),
        CheckConstraint("removed_row_count BETWEEN 0 AND 1000000", name="removed_count_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_enrichment_retention_pending", "owner_id", "phase", "id"),
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(20), default="copies")
    removed_row_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EnrichmentExpiryEventModel(EnrichmentReference):
    __tablename__ = "enrichment_expiry_events"
    __table_args__ = (
        *enrichment_references(),
        *(
            UniqueConstraint(name)
            for name in (
                "entity_evidence_version_id",
                "classification_snapshot_id",
                "fund_definition_id",
                "fund_mapping_id",
            )
        ),
        CheckConstraint("removed_row_count BETWEEN 0 AND 1000000", name="removed_count_bound"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )
    expired_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))
    removed_row_count: Mapped[int] = mapped_column(Integer)


XRAY_LIFECYCLE_MODELS = (
    XrayCommandIdentityModel,
    XrayAuditEventModel,
    EnrichmentRetrievalOccurrenceModel,
    EnrichmentRetentionWorkModel,
    EnrichmentExpiryEventModel,
)
