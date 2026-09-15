"""Small owned continuation records for budgeted projection cleanup only.

These operational rows contain identities and clocks, never financial documents.
They do not authorize private reads or replace original source integrity guards.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
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
from .premium_models import PremiumOwned
from .types import UTCDateTime


class ProjectionRetentionEpochModel(Base):
    __tablename__ = "projection_retention_epochs"
    __table_args__ = (CheckConstraint("epoch>=0 AND roots_epoch>=0", name="epoch_bound"),)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    epoch: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    roots_epoch: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class ProjectionRetentionScanModel(PremiumOwned):
    __tablename__ = "projection_retention_scans"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "account_id", "id", name="uq_projection_retention_scans_scope"
        ),
        UniqueConstraint("run_id", "purpose", name="uq_projection_retention_scans_run_purpose"),
        CheckConstraint(
            "purpose IN ('expiry','report_expiry','source_match') AND phase IN ('source','walk"
            "','clear','restart','clean','matched')",
            name="phase_bound",
        ),
        CheckConstraint(
            "(purpose IN ('expiry','report_expiry') AND target_kind IS NULL AND target_id IS NULL) "
            "OR (purpose='source_match' AND target_kind IN ('price','fx','corp"
            "orate_action','benchmark','historical') AND target_id IS NOT NULL"
            ")",
            name="target_bound",
        ),
        CheckConstraint(
            "(restriction_kind IS NULL AND restriction_id IS NULL) OR (pu"
            "rpose='report_expiry' AND restriction_kind IN ('price','fx',"
            "'corporate_action','benchmark','historical','license','class"
            "ification') AND restriction_id IS NOT NULL)",
            name="witness_bound",
        ),
        CheckConstraint(
            "policy_epoch>=0 AND source_count BETWEEN 0 AND 257 AND dependenci"
            "es_seen BETWEEN 0 AND 100001 AND node_count BETWEEN 0 AND 100001",
            name="count_bound",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_retention_scans_run",
        ),
        Index("ix_projection_retention_scans_owner_run", "owner_id", "account_id", "run_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    purpose: Mapped[str] = mapped_column(String(16))
    target_kind: Mapped[str | None] = mapped_column(String(24))
    target_id: Mapped[UUID | None] = mapped_column(Uuid())
    phase: Mapped[str] = mapped_column(String(12))
    policy_epoch: Mapped[int] = mapped_column(BigInteger)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    next_policy_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    earliest_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    restriction_kind: Mapped[str | None] = mapped_column(String(20))
    restriction_id: Mapped[UUID | None] = mapped_column(Uuid())
    source_cursor: Mapped[UUID | None] = mapped_column(Uuid())
    current_source_id: Mapped[UUID | None] = mapped_column(Uuid())
    history_input_id: Mapped[UUID | None] = mapped_column(Uuid())
    history_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_count: Mapped[int] = mapped_column(Integer)
    dependencies_seen: Mapped[int] = mapped_column(Integer)
    node_count: Mapped[int] = mapped_column(Integer)


class ProjectionRetentionFrontierModel(PremiumOwned):
    __tablename__ = "projection_retention_frontier"
    __table_args__ = (
        UniqueConstraint(
            "scan_id", "subject_id", "is_evidence", name="uq_projection_retention_frontier_visit"
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "scan_id"],
            [
                "projection_retention_scans.owner_id",
                "projection_retention_scans.account_id",
                "projection_retention_scans.id",
            ],
            ondelete="RESTRICT",
            name="fk_projection_retention_frontier_scan",
        ),
        Index(
            "ix_projection_retention_frontier_pending",
            "owner_id",
            "account_id",
            "scan_id",
            "complete",
            "id",
        ),
        Index(
            "ix_projection_retention_frontier_cleanup", "owner_id", "account_id", "scan_id", "id"
        ),
    )
    scan_id: Mapped[UUID] = mapped_column(Uuid())
    subject_id: Mapped[UUID] = mapped_column(Uuid())
    is_evidence: Mapped[bool] = mapped_column(Boolean)
    dependency_cursor: Mapped[UUID | None] = mapped_column(Uuid())
    complete: Mapped[bool] = mapped_column(Boolean)


class ProjectionRetentionTargetModel(PremiumOwned):
    """At most 32 completed target outcomes; never evicts an unfinished graph."""

    __tablename__ = "projection_retention_targets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["projection_runs.owner_id", "projection_runs.account_id", "projection_runs.id"],
            ondelete="RESTRICT",
            name="fk_projection_retention_targets_run",
        ),
        UniqueConstraint(
            "run_id", "target_kind", "target_id", name="uq_projection_retention_targets_identity"
        ),
        CheckConstraint(
            "target_kind IN ('price','fx','corporate_action','benchmark','historical')",
            name="kind_bound",
        ),
        Index("ix_projection_retention_targets_cleanup", "owner_id", "account_id", "run_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid())
    target_kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[UUID] = mapped_column(Uuid())
    matched: Mapped[bool] = mapped_column(Boolean)


class ProjectionRetentionSweepModel(Base):
    """One bounded root cursor per active exact sweep; removed at end of pass."""

    __tablename__ = "projection_retention_sweeps"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('expiry','report_expiry','source_match','owner_erasure')",
            name="purpose_bound",
        ),
        CheckConstraint(
            "(purpose IN ('expiry','report_expiry') AND target_kind IS NULL AND target_id IS NULL) "
            "OR (purpose='owner_erasure' AND owner_id IS NOT NULL AND target_k"
            "ind IS NULL AND target_id IS NULL) OR (purpose='source_match' AND"
            " owner_id IS NOT NULL AND target_kind IN ('price','fx','corporate"
            "_action','benchmark','historical') AND target_id IS NOT NULL)",
            name="scope_bound",
        ),
        CheckConstraint("policy_epoch>=0", name="epoch_bound"),
        Index("ix_projection_retention_sweeps_owner", "owner_id", "key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    purpose: Mapped[str] = mapped_column(String(16))
    target_kind: Mapped[str | None] = mapped_column(String(24))
    target_id: Mapped[UUID | None] = mapped_column(Uuid())
    after_id: Mapped[UUID | None] = mapped_column(Uuid())
    deferred: Mapped[bool] = mapped_column(Boolean)
    policy_epoch: Mapped[int] = mapped_column(BigInteger)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())


PROJECTION_RETENTION_MODELS = (
    ProjectionRetentionEpochModel,
    ProjectionRetentionScanModel,
    ProjectionRetentionFrontierModel,
    ProjectionRetentionTargetModel,
    ProjectionRetentionSweepModel,
)
