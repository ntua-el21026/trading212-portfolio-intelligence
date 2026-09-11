"""Actual owner-attested source revision edges, append-only after registration."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import UTCDateTime


class ActivityRevisionEvidenceModel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "activity_revision_evidence"
    __table_args__ = (
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
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id", ondelete="RESTRICT"))
    new_source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    superseded_source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    authority: Mapped[str] = mapped_column(String(30))
    evidence_key: Mapped[str] = mapped_column(String(120))
    economic_key: Mapped[str] = mapped_column(String(255))
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(180))
