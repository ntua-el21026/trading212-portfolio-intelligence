"""Protected physical copy facts; none of these rows grants source-read authority."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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


class XrayPhysicalStateModel(Base):
    __tablename__ = "xray_physical_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "input_id"],
            ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"],
            name="fk_xray_physical_input",
            ondelete="RESTRICT",
        ),
        CheckConstraint("payload_rows>=0", name="rows_bound"),
    )
    input_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    input_pending: Mapped[bool] = mapped_column(Boolean)
    payload_rows: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class HistoricalPhysicalRunModel(Base):
    __tablename__ = "historical_physical_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["historical_analytics_runs.owner_id", "historical_analytics_runs.id"],
            name="fk_historical_physical_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "input_id"],
            ["historical_input_snapshots.owner_id", "historical_input_snapshots.id"],
            name="fk_historical_physical_input",
            ondelete="RESTRICT",
        ),
        CheckConstraint("child_rows>=0", name="rows_bound"),
        Index(
            "ix_historical_physical_pending",
            "owner_id",
            "input_id",
            "run_id",
            postgresql_where=text("child_rows>0 OR analytics_pending"),
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    child_rows: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    analytics_pending: Mapped[bool] = mapped_column(Boolean)


class HistoricalCompositePhysicalModel(Base):
    __tablename__ = "historical_composite_physical"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "snapshot_id"],
            ["benchmark_snapshots.owner_id", "benchmark_snapshots.id"],
            name="fk_historical_composite_physical",
            ondelete="RESTRICT",
        ),
        CheckConstraint("point_rows>=0", name="rows_bound"),
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    point_rows: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class HistoricalCompositeErasureModel(Base):
    __tablename__ = "historical_composite_erasures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "snapshot_id"],
            ["benchmark_snapshots.owner_id", "benchmark_snapshots.id"],
            name="fk_historical_erasure_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["historical_analytics_runs.owner_id", "historical_analytics_runs.id"],
            name="fk_historical_erasure_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "event_id"],
            ["historical_retention_events.owner_id", "historical_retention_events.id"],
            name="fk_historical_erasure_event",
            ondelete="RESTRICT",
        ),
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    run_id: Mapped[UUID] = mapped_column(Uuid())
    event_id: Mapped[UUID] = mapped_column(Uuid())


class XrayRetainedSourceModel(Base):
    __tablename__ = "xray_retained_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "input_id"],
            ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"],
            name="fk_xray_retained_input",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "dependency_id"],
            ["xray_input_dependencies.owner_id", "xray_input_dependencies.id"],
            name="fk_xray_retained_dependency",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            (
                "source_kind IN ('fx','entity_evidence','classification'"
                ",'fund_definition','fund_mapping','constituent')"
            ),
            name="kind_bound",
        ),
        Index(
            "ix_xray_retained_source",
            "owner_id",
            "source_kind",
            "source_id",
            "input_id",
            "dependency_id",
        ),
        Index("ix_xray_retained_input", "owner_id", "input_id", "dependency_id"),
    )
    dependency_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[UUID] = mapped_column(Uuid())


class HistoricalRetainedSourceModel(Base):
    __tablename__ = "historical_retained_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "input_id"],
            ["historical_input_snapshots.owner_id", "historical_input_snapshots.id"],
            name="fk_historical_retained_input",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "dependency_id"],
            ["historical_dependencies.owner_id", "historical_dependencies.id"],
            name="fk_historical_retained_dependency",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "leaf_id"],
            ["historical_dependencies.owner_id", "historical_dependencies.id"],
            name="fk_historical_retained_leaf",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_kind IN ('price','fx','corporate_action','benchmark')", name="kind_bound"
        ),
        Index(
            "ix_historical_retained_source",
            "owner_id",
            "source_kind",
            "source_id",
            "input_id",
            "dependency_id",
            "leaf_id",
        ),
        Index("ix_historical_retained_input", "owner_id", "input_id", "dependency_id", "leaf_id"),
    )
    dependency_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    leaf_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[UUID] = mapped_column(Uuid())


class Phase2RetentionSweepModel(Base):
    __tablename__ = "phase2_retention_sweeps"
    __table_args__ = (
        CheckConstraint(
            (
                "family IN ('price','fx','benchmark','corporate_action',"
                "'constituent','xray_collection','entity_evidence','clas"
                "sification','fund_definition','fund_mapping')"
            ),
            name="family_bound",
        ),
    )
    family: Mapped[str] = mapped_column(String(24), primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    after_id: Mapped[UUID | None] = mapped_column(Uuid())
    pending_id: Mapped[UUID | None] = mapped_column(Uuid())
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SourceRetentionDispatchModel(Base):
    __tablename__ = "source_retention_dispatch"
    __table_args__ = (
        CheckConstraint(
            (
                "(family='dispatch' AND next_family BETWEEN 0 AND 7) OR "
                "(family='source' AND next_family BETWEEN 0 AND 4) OR (f"
                "amily='enrichment' AND next_family BETWEEN 0 AND 3)"
            ),
            name="family_bound",
        ),
    )
    family: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_family: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


PHASE2_RETENTION_MODELS = (
    XrayPhysicalStateModel,
    HistoricalPhysicalRunModel,
    HistoricalCompositePhysicalModel,
    HistoricalCompositeErasureModel,
    XrayRetainedSourceModel,
    HistoricalRetainedSourceModel,
    Phase2RetentionSweepModel,
    SourceRetentionDispatchModel,
)
