"""Small protected cleanup state; original financial/source rows remain authoritative."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import UTCDateTime


class PremiumRetentionStateModel(Base):
    __tablename__ = "premium_retention_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            name="fk_premium_retention_state_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('risk','scenario')", name="kind_bound"),
        CheckConstraint(
            (
                "financial_rows>=0 AND stored_bytes BETWEEN 0 AND 33554432 "
                "AND metadata_bytes>=0 AND (kind='scenario' OR "
                "(stored_bytes=0 AND metadata_bytes=0))"
            ),
            name="counter_bound",
        ),
        Index("ix_premium_cleanup_roots", "kind", "closed", "run_id"),
        Index("ix_premium_cleanup_owner", "owner_id", "kind", "closed", "run_id"),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    account_id: Mapped[UUID] = mapped_column(Uuid())
    kind: Mapped[str] = mapped_column(String(10))
    financial_rows: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    stored_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    metadata_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    closed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class PremiumRetainedParentModel(Base):
    __tablename__ = "premium_retained_parents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "run_id"],
            ["premium_runs.owner_id", "premium_runs.account_id", "premium_runs.id"],
            name="fk_premium_retained_parent_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "parent_kind IN ('historical','xray_input','xray_run','sensitivity')", name="kind_bound"
        ),
        Index("uq_premium_retained_parent", "run_id", "parent_kind", "parent_id", unique=True),
        Index("ix_premium_retained_source", "owner_id", "parent_kind", "parent_id", "run_id"),
        Index("ix_premium_retained_cleanup", "owner_id", "run_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    account_id: Mapped[UUID] = mapped_column(Uuid())
    run_id: Mapped[UUID] = mapped_column(Uuid())
    parent_kind: Mapped[str] = mapped_column(String(16))
    parent_id: Mapped[UUID] = mapped_column(Uuid())


class PremiumRetentionSweepModel(Base):
    __tablename__ = "premium_retention_sweeps"
    __table_args__ = (
        CheckConstraint(
            (
                "family IN "
                "('risk','scenario','sensitivity','entity_evidence','classification','fund_mapping','fund_definition')"
            ),
            name="family_bound",
        ),
    )
    # Zero UUID denotes the global sweep; an exact owner scopes targeted expiry.
    scope_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    family: Mapped[str] = mapped_column(String(20), primary_key=True)
    after_id: Mapped[UUID | None] = mapped_column(Uuid())
    deferred: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    policy_epoch: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    earliest_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_policy_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PremiumRetentionScanModel(Base):
    __tablename__ = "premium_retention_scans"
    __table_args__ = (
        CheckConstraint(
            (
                "family IN ('risk','scenario','sensitivity') AND phase "
                "BETWEEN 0 AND 9 AND policy_epoch>=0"
            ),
            name="phase_bound",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    family: Mapped[str] = mapped_column(String(12), primary_key=True)
    subject_id: Mapped[UUID] = mapped_column(Uuid())
    phase: Mapped[int] = mapped_column(SmallInteger)
    cursor: Mapped[UUID | None] = mapped_column(Uuid())
    version_id: Mapped[UUID | None] = mapped_column(Uuid())
    child_cursor: Mapped[UUID | None] = mapped_column(Uuid())
    policy_epoch: Mapped[int] = mapped_column(BigInteger)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    earliest_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_policy_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


PREMIUM_RETENTION_MODELS = (
    PremiumRetentionStateModel,
    PremiumRetainedParentModel,
    PremiumRetentionSweepModel,
    PremiumRetentionScanModel,
)
