"""Temporary typed identities; no licensed payloads and no source-retention extension."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDPrimaryKeyMixin
from .types import UTCDateTime


class IntelligenceQualityCollectionBindingModel(Base):
    __tablename__ = "intelligence_quality_collection_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "collection_id"],
            ["collection_query_snapshots.owner_id", "collection_query_snapshots.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "analytics_run_id"],
            ["analytics_runs.owner_id", "analytics_runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "historical_input_id"],
            ["historical_input_snapshots.owner_id", "historical_input_snapshots.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "xray_input_id"],
            ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "analytics_kind IN ('valuation','actual_vs_target','drift','performance',"
            "'benchmark','income','attribution','cash_flow','xray')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "(analytics_kind='valuation' AND valuation_snapshot_id IS NOT NULL AND "
            "analytics_run_id IS NULL) OR (analytics_kind<>'valuation' AND "
            "valuation_snapshot_id IS NULL AND analytics_run_id IS NOT NULL)",
            name="selected_parent",
        ),
        CheckConstraint(
            "(analytics_kind IN ('performance','benchmark','income','attribution',"
            "'cash_flow') AND historical_input_id IS NOT NULL AND xray_input_id IS NULL) OR "
            "(analytics_kind='xray' AND historical_input_id IS NULL AND xray_input_id IS NOT "
            "NULL) OR (analytics_kind IN ('valuation','actual_vs_target','drift') AND "
            "historical_input_id IS NULL AND xray_input_id IS NULL)",
            name="input_parent",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        UniqueConstraint("owner_id", "collection_id"),
    )
    collection_id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    account_id: Mapped[UUID] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"))
    analytics_kind: Mapped[str] = mapped_column(String(30))
    valuation_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="CASCADE")
    )
    analytics_run_id: Mapped[UUID | None] = mapped_column()
    historical_input_id: Mapped[UUID | None] = mapped_column()
    xray_input_id: Mapped[UUID | None] = mapped_column()
    selection_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_digest: Mapped[str] = mapped_column(String(64))


class IntelligenceQualityCollectionSourceModel(UUIDPrimaryKeyMixin, Base):
    """Identity tombstone only. Current source ownership/permissions are always reloaded.

    The fixed kind/id/parent union deliberately has no FK to a financial source:
    source purge cannot be prevented by this temporary traversal. Missing/foreign
    members invalidate the cursor; collection deletion cascades these identities.
    """

    __tablename__ = "intelligence_quality_collection_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "collection_id"],
            [
                "intelligence_quality_collection_bindings.owner_id",
                "intelligence_quality_collection_bindings.collection_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("collection_id", "ordinal"),
        CheckConstraint("ordinal BETWEEN 1 AND 8192", name="ordinal_bound"),
        CheckConstraint(
            "source_kind IN ('portfolio_snapshot','snapshot_position','snapshot_cash',"
            "'calculation_run','ingestion_run','broker_source_record',"
            "'broker_source_occurrence','reconciliation_run','price_snapshot','fx_snapshot',"
            "'provider_benchmark_snapshot','corporate_action_snapshot','instrument_mapping',"
            "'calendar_version','provider_license_version','benchmark_version',"
            "'target_version','classification_evidence','historical_evidence',"
            "'activity_revision_evidence','entity_evidence_version',"
            "'classification_snapshot','fund_definition','fund_mapping',"
            "'constituent_snapshot','xray_policy')",
            name="source_kind_allowed",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    collection_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[UUID] = mapped_column()
    parent_id: Mapped[UUID | None] = mapped_column()


INTELLIGENCE_QUALITY_MODELS = (
    IntelligenceQualityCollectionBindingModel,
    IntelligenceQualityCollectionSourceModel,
)
