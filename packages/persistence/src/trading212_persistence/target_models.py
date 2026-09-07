"""Owner-scoped normalized virtual-target persistence; no broker mutations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from trading212_domain.targets import TARGET_VALIDATION_VERSION

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import ExactNumeric, UTCDateTime


class TargetOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


def owned() -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id")


def version_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "target_version_id"],
        ["target_versions.owner_id", "target_versions.id"],
        ondelete="RESTRICT",
    )


class VirtualPortfolioModel(TargetOwned):
    __tablename__ = "virtual_portfolios"
    __table_args__ = (
        owned(),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("reporting_currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_virtual_portfolios_owner_updated", "owner_id", "updated_at", "id"),
    )
    broker_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000))
    reporting_currency: Mapped[str] = mapped_column(String(3))
    revision: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor_principal_id: Mapped[str] = mapped_column(String(255))


class TargetVersionModel(TargetOwned):
    __tablename__ = "target_versions"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id",
            "virtual_portfolio_id",
            "id",
            name="uq_target_versions_owner_portfolio_identity",
        ),
        UniqueConstraint("virtual_portfolio_id", "version_number"),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id", "parent_version_id"],
            [
                "target_versions.owner_id",
                "target_versions.virtual_portfolio_id",
                "target_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_target_version_parent",
        ),
        ForeignKeyConstraint(
            ["owner_id", "source_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('draft','scheduled','active','superseded','archived')", name="state_allowed"
        ),
        CheckConstraint("revision >= 1 AND version_number >= 1", name="revisions_positive"),
        CheckConstraint("schema_version = 1", name="schema_version_supported"),
        CheckConstraint(
            "(published_at IS NULL AND content_digest IS NULL AND state IN ('draft','archived')) "
            "OR (published_at IS NOT NULL AND content_digest IS NOT NULL "
            "AND content_digest ~ '^[0-9a-f]{64}$' "
            "AND state IN ('scheduled','active','superseded','archived'))",
            name="publication_fields",
        ),
        Index("ix_target_versions_due", "state", "effective_at", "id"),
        Index(
            "uq_target_versions_one_active",
            "virtual_portfolio_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )
    virtual_portfolio_id: Mapped[UUID] = mapped_column()
    source_version_id: Mapped[UUID | None] = mapped_column()
    parent_version_id: Mapped[UUID | None] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    method_version: Mapped[str] = mapped_column(String(80), default=TARGET_VALIDATION_VERSION)
    reporting_currency: Mapped[str] = mapped_column(String(3))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    state: Mapped[str] = mapped_column(String(20))
    content_digest: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor_principal_id: Mapped[str] = mapped_column(String(255))


class TargetNodeModel(TargetOwned):
    __tablename__ = "target_nodes"
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint(
            "owner_id", "target_version_id", "id", name="uq_target_nodes_owner_version_identity"
        ),
        UniqueConstraint("target_version_id", "key"),
        UniqueConstraint(
            "target_version_id",
            "parent_id",
            "sibling_order",
            postgresql_nulls_not_distinct=True,
            name="uq_target_nodes_sibling_order",
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "parent_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("kind IN ('group','holding','cash')", name="kind_allowed"),
        CheckConstraint(
            "weight >= 0 AND weight <= 1 AND sibling_order >= 0 AND sibling_order < 256",
            name="weight_order_bounds",
        ),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    key: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    sibling_order: Mapped[int] = mapped_column(Integer)
    weight: Mapped[Decimal] = mapped_column(ExactNumeric())


class TargetHoldingModel(TargetOwned):
    __tablename__ = "target_holdings"
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint(
            "owner_id", "target_version_id", "id", name="uq_target_holdings_owner_version_identity"
        ),
        UniqueConstraint("node_id"),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "node_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
        ),
        CheckConstraint(
            "mapping_state IN ('resolved','unresolved','ambiguous')", name="mapping_state_allowed"
        ),
        CheckConstraint(
            "mapping_state <> 'resolved' OR instrument_id IS NOT NULL", name="resolved_instrument"
        ),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    node_id: Mapped[UUID] = mapped_column()
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    preferred_listing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT")
    )
    mapping_state: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000))


class TargetMappingDecisionModel(TargetOwned):
    __tablename__ = "target_mapping_decisions"
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint("holding_id"),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "holding_id"],
            ["target_holdings.owner_id", "target_holdings.target_version_id", "target_holdings.id"],
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_bounds"
        ),
        CheckConstraint("source_kind = 'owner'", name="source_allowed"),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    holding_id: Mapped[UUID] = mapped_column()
    identifier_kind: Mapped[str | None] = mapped_column(String(30))
    identifier_value: Mapped[str | None] = mapped_column(String(255))
    identifier_provider: Mapped[str | None] = mapped_column(String(80))
    method_version: Mapped[str] = mapped_column(String(80))
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    source_kind: Mapped[str] = mapped_column(String(20), default="owner")
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TargetConstraintModel(TargetOwned):
    __tablename__ = "target_constraints"
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint("target_version_id", "key"),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "node_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
        ),
        CheckConstraint(
            "kind IN ('minimum_funded_amount','amount_increment','minimum_post_weight',"
            "'maximum_post_weight','minimum_group_funding','maximum_group_funding','cash_reserve',"
            "'eligible','maximum_funded_lines','priority')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "amount IS NULL OR (amount >= 0 AND amount <> 'NaN'::numeric)",
            name="amount_nonnegative",
        ),
        CheckConstraint("weight IS NULL OR (weight >= 0 AND weight <= 1)", name="weight_bounds"),
        CheckConstraint(
            "line_count IS NULL OR (line_count >= 0 AND line_count <= 256)", name="count_bounds"
        ),
        CheckConstraint(
            "coefficient IS NULL OR (coefficient >= 0.000001 AND coefficient <= 1000)",
            name="coefficient_bounds",
        ),
        CheckConstraint(
            "(kind IN ('minimum_funded_amount','amount_increment','minimum_group_funding',"
            "'maximum_group_funding') AND amount IS NOT NULL AND currency IS NOT NULL "
            "AND num_nonnulls(weight,enabled,line_count,coefficient)=0) OR "
            "(kind IN ('minimum_post_weight','maximum_post_weight') AND weight IS NOT NULL "
            "AND num_nonnulls(amount,currency,enabled,line_count,coefficient)=0) OR "
            "(kind='cash_reserve' AND num_nonnulls(enabled,line_count,coefficient)=0 "
            "AND ((amount IS NOT NULL AND currency IS NOT NULL) "
            "OR (amount IS NULL AND currency IS NULL AND weight IS NOT NULL))) OR "
            "(kind='eligible' AND enabled IS NOT NULL "
            "AND num_nonnulls(amount,currency,weight,line_count,coefficient)=0) OR "
            "(kind='maximum_funded_lines' AND line_count IS NOT NULL "
            "AND num_nonnulls(amount,currency,weight,enabled,coefficient)=0) OR "
            "(kind='priority' AND coefficient IS NOT NULL "
            "AND num_nonnulls(amount,currency,weight,enabled,line_count)=0)",
            name="kind_fields",
        ),
        CheckConstraint("kind <> 'amount_increment' OR amount > 0", name="increment_positive"),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    key: Mapped[str] = mapped_column(String(80))
    node_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))
    weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    line_count: Mapped[int | None] = mapped_column(Integer)
    coefficient: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class TargetExclusionModel(TargetOwned):
    __tablename__ = "target_exclusions"
    key: Mapped[str] = mapped_column(String(80))
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint("target_version_id", "key"),
        UniqueConstraint(
            "target_version_id",
            "node_id",
            "instrument_id",
            "listing_id",
            postgresql_nulls_not_distinct=True,
            name="uq_target_exclusions_selector",
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "node_id"],
            ["target_nodes.owner_id", "target_nodes.target_version_id", "target_nodes.id"],
        ),
        CheckConstraint("num_nonnulls(node_id,instrument_id,listing_id) = 1", name="one_selector"),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    node_id: Mapped[UUID | None] = mapped_column()
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(String(1000))


class TargetValidationResultModel(TargetOwned):
    __tablename__ = "target_validation_results"
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint(
            "owner_id",
            "target_version_id",
            "id",
            name="uq_target_validations_owner_version_identity",
        ),
        UniqueConstraint("target_version_id", "result_revision"),
        CheckConstraint(
            "input_revision > 0 AND result_revision = input_revision + 1", name="revision_order"
        ),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    input_revision: Mapped[int] = mapped_column(Integer)
    result_revision: Mapped[int] = mapped_column(Integer)
    input_digest: Mapped[str] = mapped_column(String(64))
    result_digest: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(80))
    normalization_requested: Mapped[bool] = mapped_column(Boolean)
    normalization_applied: Mapped[bool] = mapped_column(Boolean)
    valid: Mapped[bool] = mapped_column(Boolean)
    effective_weight_rounding_residual: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    actor_principal_id: Mapped[str] = mapped_column(String(255))


class TargetValidationIssueModel(TargetOwned):
    __tablename__ = "target_validation_issues"
    __table_args__ = (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "validation_id"],
            ["target_validation_results.owner_id", "target_validation_results.id"],
        ),
        UniqueConstraint("validation_id", "ordinal"),
    )
    validation_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    node_keys: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    constraint_keys: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    message: Mapped[str] = mapped_column(String(1000))


class TargetNormalizationAdjustmentModel(TargetOwned):
    __tablename__ = "target_normalization_adjustments"
    __table_args__ = (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "validation_id"],
            ["target_validation_results.owner_id", "target_validation_results.id"],
        ),
        UniqueConstraint("validation_id", "node_key"),
    )
    validation_id: Mapped[UUID] = mapped_column()
    node_key: Mapped[str] = mapped_column(String(80))
    parent_key: Mapped[str | None] = mapped_column(String(80))
    original_weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    normalized_weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    original_sum: Mapped[Decimal] = mapped_column(ExactNumeric())
    remainder_rank: Mapped[int] = mapped_column(Integer)


class VirtualPortfolioEventModel(TargetOwned):
    __tablename__ = "virtual_portfolio_events"
    __table_args__ = (
        owned(),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
        ),
        UniqueConstraint("virtual_portfolio_id", "sequence"),
    )
    virtual_portfolio_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(120))


class TargetVersionEventModel(TargetOwned):
    __tablename__ = "target_version_events"
    __table_args__ = (
        owned(),
        version_fk(),
        UniqueConstraint("target_version_id", "sequence"),
        UniqueConstraint(
            "owner_id", "target_version_id", "id", name="uq_target_events_owner_version_identity"
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "validation_id"],
            [
                "target_validation_results.owner_id",
                "target_validation_results.target_version_id",
                "target_validation_results.id",
            ],
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "previous_event_id"],
            [
                "target_version_events.owner_id",
                "target_version_events.target_version_id",
                "target_version_events.id",
            ],
            name="fk_target_event_predecessor",
        ),
        CheckConstraint(
            "kind IN ('draft_created','draft_updated','validated','published','activated',"
            "'superseded','archived')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "(sequence=1 AND previous_event_id IS NULL) OR "
            "(sequence>1 AND previous_event_id IS NOT NULL)",
            name="predecessor_required",
        ),
        Index(
            "uq_target_version_activation",
            "target_version_id",
            unique=True,
            postgresql_where=text("kind = 'activated'"),
        ),
    )
    target_version_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(120))
    validation_id: Mapped[UUID | None] = mapped_column()
    previous_event_id: Mapped[UUID | None] = mapped_column()
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TargetCommandIdentityModel(TargetOwned):
    __tablename__ = "target_command_identities"
    __table_args__ = (
        owned(),
        UniqueConstraint(
            "owner_id",
            "broker_account_id",
            "command_kind",
            "idempotency_key",
            postgresql_nulls_not_distinct=True,
            name="uq_target_commands_scope_key",
        ),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
        ),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id", "target_version_id"],
            [
                "target_versions.owner_id",
                "target_versions.virtual_portfolio_id",
                "target_versions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id", "validation_id"],
            [
                "target_validation_results.owner_id",
                "target_validation_results.target_version_id",
                "target_validation_results.id",
            ],
        ),
        CheckConstraint(
            "command_kind IN ('create_portfolio','update_portfolio','archive_portfolio',"
            "'create_version','replace_draft','validate_version','publish_version','archive_version')",
            name="command_allowed",
        ),
    )
    broker_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    command_kind: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    request_digest: Mapped[str] = mapped_column(String(64))
    virtual_portfolio_id: Mapped[UUID] = mapped_column()
    target_version_id: Mapped[UUID | None] = mapped_column()
    validation_id: Mapped[UUID | None] = mapped_column()
    actor_principal_id: Mapped[str] = mapped_column(String(255))


class TargetCollectionReferenceModel(TargetOwned):
    __tablename__ = "target_collection_references"
    __table_args__ = (
        owned(),
        UniqueConstraint("snapshot_id", "virtual_portfolio_id"),
        ForeignKeyConstraint(
            ["owner_id", "snapshot_id"],
            ["collection_query_snapshots.owner_id", "collection_query_snapshots.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
        ),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id", "target_version_id"],
            [
                "target_versions.owner_id",
                "target_versions.virtual_portfolio_id",
                "target_versions.id",
            ],
        ),
    )
    snapshot_id: Mapped[UUID] = mapped_column()
    virtual_portfolio_id: Mapped[UUID] = mapped_column()
    target_version_id: Mapped[UUID | None] = mapped_column()


TARGET_MODELS = (
    VirtualPortfolioModel,
    TargetVersionModel,
    TargetNodeModel,
    TargetHoldingModel,
    TargetMappingDecisionModel,
    TargetConstraintModel,
    TargetExclusionModel,
    TargetValidationResultModel,
    TargetValidationIssueModel,
    TargetNormalizationAdjustmentModel,
    VirtualPortfolioEventModel,
    TargetVersionEventModel,
    TargetCommandIdentityModel,
    TargetCollectionReferenceModel,
)
