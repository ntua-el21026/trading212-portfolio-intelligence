"""Immutable research-report lineage and indexed physical-copy membership."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .report_models import ReportOwned
from .types import UTCDateTime


def _input(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "account_id", "input_id"],
        [
            "report_input_snapshots.owner_id",
            "report_input_snapshots.account_id",
            "report_input_snapshots.id",
        ],
        name=f"fk_{table}_input",
        ondelete="RESTRICT",
    )


def _member(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "account_id", "input_id"],
        [
            "report_input_research_dependencies.owner_id",
            "report_input_research_dependencies.account_id",
            "report_input_research_dependencies.input_id",
        ],
        name=f"fk_{table}_research",
        ondelete="RESTRICT",
    )


class ReportInputResearchDependencyModel(ReportOwned):
    __tablename__ = "report_input_research_dependencies"
    __table_args__ = (
        _input("report_research"),
        UniqueConstraint("input_id", name="uq_report_research_input"),
        UniqueConstraint("owner_id", "account_id", "input_id", name="uq_report_research_scope"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "item_id"],
            ["research_items.owner_id", "research_items.account_id", "research_items.id"],
            name="fk_report_research_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "event_revision_id"],
            [
                "research_event_revisions.owner_id",
                "research_event_revisions.account_id",
                "research_event_revisions.id",
            ],
            name="fk_report_research_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "review_acknowledgment_id"],
            [
                "research_review_acknowledgments.owner_id",
                "research_review_acknowledgments.account_id",
                "research_review_acknowledgments.id",
            ],
            name="fk_report_research_review",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "xray_input_id"],
            ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"],
            name="fk_report_research_xray_input",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "xray_run_id"],
            ["xray_runs.owner_id", "xray_runs.id"],
            name="fk_report_research_xray_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_count BETWEEN 1 AND 4160 AND note_count BETWEEN 0 AND 64", name="counts"
        ),
        CheckConstraint("expires_at>created_at", name="expiry"),
        CheckConstraint("copy_pending OR NOT payload_pending", name="physical_pending"),
        CheckConstraint(
            "item_selection_digest ~ '^[0-9a-f]{64}$' AND event_revision_digest ~ '^[0-9a-f]{64}$' "
            "AND xray_input_digest ~ '^[0-9a-f]{64}$' AND xray_result_digest ~ '^[0-9a-f]{64}$' "
            "AND xray_pin_digest ~ '^[0-9a-f]{64}$'",
            name="digests",
        ),
        Index("ix_report_research_owner_pending", "owner_id", "copy_pending", "input_id", "id"),
        Index(
            "ix_report_research_event_pending",
            "owner_id",
            "event_revision_id",
            "copy_pending",
            "input_id",
        ),
        Index(
            "ix_report_research_xray_pending",
            "owner_id",
            "xray_input_id",
            "copy_pending",
            "input_id",
        ),
        Index(
            "ix_report_research_run_pending", "owner_id", "xray_run_id", "copy_pending", "input_id"
        ),
        Index(
            "ix_report_research_event_payload",
            "owner_id",
            "event_revision_id",
            "payload_pending",
            "input_id",
        ),
        Index(
            "ix_report_research_xray_payload",
            "owner_id",
            "xray_input_id",
            "payload_pending",
            "input_id",
        ),
        Index(
            "ix_report_research_run_payload",
            "owner_id",
            "xray_run_id",
            "payload_pending",
            "input_id",
        ),
    )
    account_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    item_id: Mapped[UUID] = mapped_column(Uuid())
    item_selection_digest: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[UUID] = mapped_column(Uuid())
    event_id: Mapped[UUID] = mapped_column(Uuid())
    event_revision_id: Mapped[UUID] = mapped_column(Uuid())
    event_revision_digest: Mapped[str] = mapped_column(String(64))
    xray_run_id: Mapped[UUID] = mapped_column(Uuid())
    xray_input_id: Mapped[UUID] = mapped_column(Uuid())
    xray_input_digest: Mapped[str] = mapped_column(String(64))
    xray_result_digest: Mapped[str] = mapped_column(String(64))
    xray_pin_digest: Mapped[str] = mapped_column(String(64))
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_count: Mapped[int] = mapped_column(Integer)
    note_count: Mapped[int] = mapped_column(Integer)
    review_acknowledgment_id: Mapped[UUID | None] = mapped_column(Uuid())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    copy_pending: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Exact physical completion can precede bounded audit-flag draining.
    payload_pending: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ReportInputResearchSourceModel(ReportOwned):
    __tablename__ = "report_input_research_sources"
    __table_args__ = (
        _member("report_research_source"),
        UniqueConstraint("input_id", "source_version_id", name="uq_report_research_source"),
        ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["research_source_versions.owner_id", "research_source_versions.id"],
            name="fk_report_research_source_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "origin_id"],
            ["research_source_origins.owner_id", "research_source_origins.id"],
            name="fk_report_research_source_origin",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "provider_id", "license_version_id"],
            [
                "provider_license_versions.owner_id",
                "provider_license_versions.provider_id",
                "provider_license_versions.id",
            ],
            name="fk_report_research_source_license",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "capability_grant_id"],
            ["provider_capability_grants.owner_id", "provider_capability_grants.id"],
            name="fk_report_research_source_grant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("capability IN ('news','company_overview')", name="capability"),
        CheckConstraint(
            "source_version_digest ~ '^[0-9a-f]{64}$' AND license_digest ~ '^[0-9a-f]{64}$' "
            "AND capability_grant_digest ~ '^[0-9a-f]{64}$'",
            name="digests",
        ),
        CheckConstraint(
            "original_retained_at<=retained_at AND retained_at<effective_expires_at "
            "AND effective_expires_at<=original_expires_at",
            name="clocks",
        ),
        Index(
            "ix_report_research_source_pending",
            "owner_id",
            "source_version_id",
            "copy_pending",
            "input_id",
            "id",
        ),
        Index("ix_report_research_sources_input", "owner_id", "input_id", "copy_pending", "id"),
        Index("ix_report_research_sources_sweep", "copy_pending", "id"),
    )
    account_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    source_version_id: Mapped[UUID] = mapped_column(Uuid())
    source_version_digest: Mapped[str] = mapped_column(String(64))
    origin_id: Mapped[UUID] = mapped_column(Uuid())
    provider_id: Mapped[UUID] = mapped_column(Uuid())
    entity_id: Mapped[UUID] = mapped_column(Uuid())
    capability: Mapped[str] = mapped_column(String(30))
    license_version_id: Mapped[UUID] = mapped_column(Uuid())
    license_digest: Mapped[str] = mapped_column(String(64))
    capability_grant_id: Mapped[UUID] = mapped_column(Uuid())
    capability_grant_digest: Mapped[str] = mapped_column(String(64))
    original_retained_at: Mapped[datetime] = mapped_column(UTCDateTime())
    original_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    retained_at: Mapped[datetime] = mapped_column(UTCDateTime())
    effective_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    copy_pending: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ReportInputResearchNoteModel(ReportOwned):
    __tablename__ = "report_input_research_notes"
    __table_args__ = (
        _member("report_research_note"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "revision_id"],
            [
                "research_note_revisions.owner_id",
                "research_note_revisions.account_id",
                "research_note_revisions.id",
            ],
            name="fk_report_research_note_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("input_id", "ordinal", name="uq_report_research_note_ordinal"),
        UniqueConstraint("input_id", "revision_id", name="uq_report_research_note_revision"),
        CheckConstraint("ordinal BETWEEN 0 AND 63", name="ordinal"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        Index(
            "ix_report_research_note_pending",
            "owner_id",
            "revision_id",
            "copy_pending",
            "input_id",
            "id",
        ),
        Index("ix_report_research_notes_input", "owner_id", "input_id", "copy_pending", "id"),
    )
    account_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    ordinal: Mapped[int] = mapped_column(Integer)
    note_id: Mapped[UUID] = mapped_column(Uuid())
    revision_id: Mapped[UUID] = mapped_column(Uuid())
    content_digest: Mapped[str] = mapped_column(String(64))
    copy_pending: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ReportResearchRetentionSweepModel(Base):
    __tablename__ = "report_research_retention_sweep"
    __table_args__ = (CheckConstraint("id=1", name="singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    after_id: Mapped[UUID | None] = mapped_column(Uuid())
    physical_after_id: Mapped[UUID | None] = mapped_column(Uuid())


REPORT_RESEARCH_MODELS = (
    ReportInputResearchDependencyModel,
    ReportInputResearchSourceModel,
    ReportInputResearchNoteModel,
    ReportResearchRetentionSweepModel,
)
