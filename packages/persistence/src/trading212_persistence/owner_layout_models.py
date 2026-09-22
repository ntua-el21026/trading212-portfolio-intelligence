"""Owner-private layout metadata, immutable typed versions and original command receipts."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import UTCDateTime


class LayoutOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


class OwnerLayoutModel(LayoutOwned):
    __tablename__ = "owner_layouts"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "id", "current_version_id"],
            [
                "saved_view_versions.owner_id",
                "saved_view_versions.layout_id",
                "saved_view_versions.id",
            ],
            name="fk_owner_layout_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(["owner_id", "actor_id"], ["principals.owner_id", "principals.id"]),
        CheckConstraint("revision BETWEEN 1 AND 129", name="revision_bound"),
        CheckConstraint(
            (
                "(state='active' AND archived_at IS NULL AND current_version_id "
                "IS NOT NULL) OR (state='archived' AND archived_at IS NOT NULL "
                "AND current_version_id IS NOT NULL) OR (state='erasing' AND "
                "current_version_id IS NULL)"
            ),
            name="state_shape",
        ),
        Index("ix_owner_layout_current_version", "current_version_id"),
        Index("ix_owner_layouts_owner_created", "owner_id", "created_at", "id"),
    )
    current_version_id: Mapped[UUID | None] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[UUID] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SavedViewVersionModel(LayoutOwned):
    __tablename__ = "saved_view_versions"
    __table_args__ = (
        UniqueConstraint("owner_id", "layout_id", "id"),
        UniqueConstraint("layout_id", "version_number"),
        ForeignKeyConstraint(
            ["owner_id", "layout_id"],
            ["owner_layouts.owner_id", "owner_layouts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["owner_id", "layout_id", "parent_version_id"],
            [
                "saved_view_versions.owner_id",
                "saved_view_versions.layout_id",
                "saved_view_versions.id",
            ],
        ),
        ForeignKeyConstraint(["owner_id", "actor_id"], ["principals.owner_id", "principals.id"]),
        CheckConstraint(
            "version_number BETWEEN 1 AND 128 AND schema_version=1", name="version_bound"
        ),
        CheckConstraint(
            "columns BETWEEN 1 AND 3 AND density IN ('comfortable','compact')", name="presentation"
        ),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 80 AND length(description)<=400", name="text_bound"
        ),
        CheckConstraint(
            (
                "octet_length(canonical_content) BETWEEN 1 AND 16384 AND "
                "content_digest ~ '^[0-9a-f]{64}$'"
            ),
            name="content_bound",
        ),
        Index("ix_saved_view_version_parent", "parent_version_id"),
        Index(
            "ix_saved_view_version_cutoff", "owner_id", "layout_id", "created_at", "version_number"
        ),
    )
    layout_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[UUID | None] = mapped_column()
    schema_version: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[UUID] = mapped_column()
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(400))
    columns: Mapped[int] = mapped_column(Integer)
    density: Mapped[str] = mapped_column(String(12))
    content_digest: Mapped[str] = mapped_column(String(64))
    canonical_content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class SavedLayoutWidgetModel(LayoutOwned):
    __tablename__ = "saved_layout_widgets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "layout_id", "version_id"],
            [
                "saved_view_versions.owner_id",
                "saved_view_versions.layout_id",
                "saved_view_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("version_id", "widget_id", name="uq_saved_layout_widget_identity"),
        UniqueConstraint("version_id", "ordinal", name="uq_saved_layout_widget_ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 23", name="ordinal_bound"),
        CheckConstraint(
            (
                "kind IN "
                "('portfolio_summary','direct_allocation','holdings_preview','data"
                "_quality','saved_view')"
            ),
            name="kind_allowed",
        ),
        CheckConstraint(
            (
                "(kind='saved_view' AND selection_kind IN "
                "('workspace','historical','saved_run','research')) OR "
                "(kind<>'saved_view' AND selection_kind IS NULL)"
            ),
            name="selection_kind",
        ),
        CheckConstraint(
            "num_nonnulls(risk_run_id,scenario_run_id,projection_run_id,xray_run_id)<=1",
            name="one_run",
        ),
        Index(
            "ix_saved_layout_widgets_owner_layout", "owner_id", "layout_id", "version_id", "ordinal"
        ),
        Index("ix_saved_layout_widgets_owner_version", "owner_id", "version_id", "ordinal"),
    )
    layout_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    widget_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(80))
    selection_kind: Mapped[str | None] = mapped_column(String(12))
    route: Mapped[str | None] = mapped_column(String(20))
    pane: Mapped[str | None] = mapped_column(String(12))
    run_family: Mapped[str | None] = mapped_column(String(12))
    risk_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("risk_runs.id", ondelete="RESTRICT")
    )
    scenario_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scenario_runs.id", ondelete="RESTRICT")
    )
    projection_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projection_runs.id", ondelete="RESTRICT")
    )
    xray_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("xray_runs.id", ondelete="RESTRICT")
    )
    snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    capture_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_input_snapshots.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("economic_entities.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date | None] = mapped_column()
    end_date: Mapped[date | None] = mapped_column()
    source_cutoff_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reporting_currency: Mapped[str | None] = mapped_column(String(3))
    method: Mapped[str | None] = mapped_column(String(20))
    frequency: Mapped[str | None] = mapped_column(String(8))
    knowledge: Mapped[str | None] = mapped_column(String(16))
    coverage: Mapped[str | None] = mapped_column(String(20))
    view: Mapped[str | None] = mapped_column(String(16))
    grouping: Mapped[str | None] = mapped_column(String(12))
    flow_kind: Mapped[str | None] = mapped_column(String(20))
    rolling: Mapped[str | None] = mapped_column(String(20))
    calendar: Mapped[str | None] = mapped_column(String(8))
    event_kind: Mapped[str | None] = mapped_column(String(24))
    review_state: Mapped[str | None] = mapped_column(String(16))


class OwnerLayoutCommandModel(LayoutOwned):
    __tablename__ = "owner_layout_command_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "layout_id", "version_id"],
            [
                "saved_view_versions.owner_id",
                "saved_view_versions.layout_id",
                "saved_view_versions.id",
            ],
        ),
        ForeignKeyConstraint(["owner_id", "actor_id"], ["principals.owner_id", "principals.id"]),
        UniqueConstraint("owner_id", "command", "idempotency_key"),
        UniqueConstraint("layout_id", "result_revision"),
        CheckConstraint(
            (
                "command IN "
                "('preferences.layout.create.v1','preferences.layout.update.v1','p"
                "references.layout.archive.v1')"
            ),
            name="command_allowed",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,180}$' AND command_digest ~ '^[0-9a-f]{64}$'",
            name="identity_format",
        ),
        CheckConstraint("result_revision BETWEEN 1 AND 129", name="revision_bound"),
        Index("ix_layout_commands_owner_version", "owner_id", "version_id", "result_revision"),
        Index("ix_layout_commands_owner_layout", "owner_id", "layout_id", "result_revision"),
    )
    layout_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column()
    command: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    command_digest: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column()
    correlation_id: Mapped[str] = mapped_column(String(120))
    result_revision: Mapped[int] = mapped_column(Integer)
    audit_id: Mapped[UUID] = mapped_column(ForeignKey("audit_events.id", ondelete="RESTRICT"))


class OwnerLayoutErasureModel(Base):
    __tablename__ = "owner_layout_erasure"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NULL OR completed_at>=created_at", name="completion_order"
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


OWNER_LAYOUT_MODELS = (
    OwnerLayoutModel,
    SavedViewVersionModel,
    SavedLayoutWidgetModel,
    OwnerLayoutCommandModel,
    OwnerLayoutErasureModel,
)


def register_owner_layout_indexes(metadata: MetaData) -> None:
    """Register the bounded inactive-owner precondition probe on the existing table."""
    table = metadata.tables["broker_connections"]
    name = "ix_broker_connections_layout_active_owner"
    if not any(index.name == name for index in table.indexes):
        Index(name, table.c.owner_id, postgresql_where=text("status='active'"))
