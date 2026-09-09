"""Normalized, owner-scoped planning inputs, immutable results and durable jobs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from .types import ExactNumeric, UTCDateTime


class PlanningOwned(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __abstract__ = True
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))


def _owned() -> UniqueConstraint:
    return UniqueConstraint("owner_id", "id")


def _request_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "request_id"],
        ["contribution_plan_requests.owner_id", "contribution_plan_requests.id"],
        ondelete="RESTRICT",
    )


def _result_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", "result_id"],
        ["contribution_plan_revisions.owner_id", "contribution_plan_revisions.id"],
        ondelete="RESTRICT",
    )


class ContributionPlanModel(PlanningOwned):
    __tablename__ = "contribution_plans"
    __table_args__ = (
        _owned(),
        ForeignKeyConstraint(
            ["owner_id", "virtual_portfolio_id"],
            ["virtual_portfolios.owner_id", "virtual_portfolios.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(
            "ix_contribution_plans_owner_account_created",
            "owner_id",
            "broker_account_id",
            "created_at",
            "id",
        ),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    virtual_portfolio_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ContributionPlanRequestModel(PlanningOwned):
    __tablename__ = "contribution_plan_requests"
    __table_args__ = (
        _owned(),
        UniqueConstraint("plan_id", "revision_number"),
        ForeignKeyConstraint(
            ["owner_id", "plan_id"],
            ["contribution_plans.owner_id", "contribution_plans.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        CheckConstraint(
            "contribution >= 0 AND (monetary_quantum IS NULL OR monetary_quantum > 0)",
            name="amount_bounds",
        ),
        CheckConstraint(
            "mode IN ('global','hierarchical','restricted','cash_only')", name="mode_allowed"
        ),
        CheckConstraint(
            "coverage_policy IN ('require_complete','allow_degraded')",
            name="coverage_policy_allowed",
        ),
        CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$' AND command_digest ~ '^[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint("source_cutoff_at <= valuation_at", name="cutoff_bound"),
    )
    plan_id: Mapped[UUID] = mapped_column()
    revision_number: Mapped[int] = mapped_column(Integer)
    target_version_id: Mapped[UUID] = mapped_column()
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    calculation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )
    contribution: Mapped[Decimal] = mapped_column(ExactNumeric())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    mode: Mapped[str] = mapped_column(String(20))
    coverage_policy: Mapped[str] = mapped_column(String(30))
    monetary_quantum: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency_policy_version: Mapped[str] = mapped_column(String(100))
    method_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(20))
    target_content_digest: Mapped[str] = mapped_column(String(64))
    valuation_content_digest: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    command_digest: Mapped[str] = mapped_column(String(64))
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    portfolio_total: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    quality_state: Mapped[str] = mapped_column(String(30))
    coverage_complete: Mapped[bool] = mapped_column(Boolean)
    reconciled: Mapped[bool] = mapped_column(Boolean)
    missing_inputs: Mapped[list[str]] = mapped_column(ARRAY(String(120)))
    cash_reserve: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(120))
    # Fixed-schema canonical bytes are an integrity mirror of the normalized
    # inputs below, never an executable or arbitrary task payload.
    canonical_input: Mapped[bytes] = mapped_column(LargeBinary)
    normalized_digest: Mapped[str] = mapped_column(String(64))


class ContributionPlanInputModel(PlanningOwned):
    __tablename__ = "contribution_plan_inputs"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id", "ordinal"),
        CheckConstraint(
            "num_nonnulls(fx_source_id,fx_digest,fx_base_currency,fx_quote_currency,"
            "fx_rate,fx_effective_at,fx_first_observed_at)=0 OR "
            "(num_nonnulls(fx_source_id,fx_digest,fx_base_currency,fx_quote_currency,"
            "fx_rate,fx_effective_at,fx_first_observed_at)=7 AND fx_rate>0 "
            "AND fx_base_currency<>fx_quote_currency)",
            name="complete_fx",
        ),
        CheckConstraint("kind IN ('position','cash')", name="kind_allowed"),
        CheckConstraint(
            "(kind='position' AND listing_id IS NOT NULL AND instrument_id IS NOT NULL) OR "
            "(kind='cash' AND listing_id IS NULL AND instrument_id IS NULL)",
            name="kind_identity",
        ),
    )
    request_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str] = mapped_column(String(3))
    quality_state: Mapped[str] = mapped_column(String(30))
    fx_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    fx_digest: Mapped[str | None] = mapped_column(String(64))
    fx_base_currency: Mapped[str | None] = mapped_column(String(3))
    fx_quote_currency: Mapped[str | None] = mapped_column(String(3))
    fx_rate: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    fx_effective_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fx_first_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ContributionPlanCatalogModel(PlanningOwned):
    __tablename__ = "contribution_plan_catalog"
    __table_args__ = (_owned(), _request_fk(), UniqueConstraint("request_id", "listing_id"))
    request_id: Mapped[UUID] = mapped_column()
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    active: Mapped[bool] = mapped_column(Boolean)


class ContributionPlanConstraintModel(PlanningOwned):
    __tablename__ = "contribution_plan_request_constraints"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id", "key"),
        CheckConstraint(
            "amount IS NULL OR (amount >= 0 AND amount <> 'NaN'::numeric)",
            name="amount_nonnegative",
        ),
        CheckConstraint(
            "coefficient IS NULL OR (coefficient >= 0.000001 AND coefficient <= 1000)",
            name="coefficient_bounds",
        ),
        CheckConstraint(
            "line_count IS NULL OR (line_count >= 0 AND line_count <= 256)", name="count_bounds"
        ),
        CheckConstraint("kind <> 'amount_increment' OR amount > 0", name="increment_positive"),
        CheckConstraint(
            "kind IN "
            "('minimum_funded_amount','amount_increment','minimum_post_weight','maximum_post_weight','minimum_group_funding','maximum_group_funding','cash_reserve','eligible','maximum_funded_lines','priority')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "(kind IN "
            "('minimum_funded_amount','amount_increment','minimum_group_funding',"
            "'maximum_group_funding') "
            "AND amount IS NOT NULL AND currency IS NOT NULL AND "
            "num_nonnulls(weight,enabled,line_count,coefficient)=0) OR (kind IN "
            "('minimum_post_weight','maximum_post_weight') AND weight IS NOT NULL AND "
            "num_nonnulls(amount,currency,enabled,line_count,coefficient)=0) OR "
            "(kind='cash_reserve' AND num_nonnulls(enabled,line_count,coefficient)=0 AND "
            "((amount IS NOT NULL AND currency IS NOT NULL) OR (amount IS NULL AND "
            "currency IS NULL AND weight IS NOT NULL))) OR (kind='eligible' AND enabled "
            "IS NOT NULL AND "
            "num_nonnulls(amount,currency,weight,line_count,coefficient)=0) OR "
            "(kind='maximum_funded_lines' AND line_count IS NOT NULL AND "
            "num_nonnulls(amount,currency,weight,enabled,coefficient)=0) OR "
            "(kind='priority' AND coefficient IS NOT NULL AND "
            "num_nonnulls(amount,currency,weight,enabled,line_count)=0)",
            name="kind_fields",
        ),
        CheckConstraint("weight IS NULL OR (weight >= 0 AND weight <= 1)", name="weight_bounds"),
    )
    request_id: Mapped[UUID] = mapped_column()
    key: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(40))
    node_key: Mapped[str | None] = mapped_column(String(80))
    amount: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str | None] = mapped_column(String(3))
    weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    line_count: Mapped[int | None] = mapped_column(Integer)
    coefficient: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class ContributionPlanSelectionModel(PlanningOwned):
    __tablename__ = "contribution_plan_selections"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id", "kind", "target_node_id"),
        CheckConstraint(
            "kind IN ('eligible','excluded','restricted','preference')", name="kind_allowed"
        ),
    )
    request_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    target_node_id: Mapped[UUID] = mapped_column(ForeignKey("target_nodes.id", ondelete="RESTRICT"))
    holding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("target_holdings.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))


class ContributionPlanHoldingConstraintModel(PlanningOwned):
    __tablename__ = "contribution_plan_holding_constraints"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id", "holding_id"),
        CheckConstraint(
            "minimum_amount >= 0 AND value_increment > 0 AND "
            "(maximum_post_weight IS NULL OR maximum_post_weight BETWEEN 0 AND 1)",
            name="bounds",
        ),
    )
    request_id: Mapped[UUID] = mapped_column()
    holding_id: Mapped[UUID] = mapped_column(ForeignKey("target_holdings.id", ondelete="RESTRICT"))
    minimum_amount: Mapped[Decimal] = mapped_column(ExactNumeric())
    value_increment: Mapped[Decimal] = mapped_column(ExactNumeric())
    maximum_post_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())


class ContributionPlanSourceModel(PlanningOwned):
    __tablename__ = "contribution_plan_sources"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id", "kind", "source_id"),
        CheckConstraint(
            "kind IN ('snapshot','calculation','target','source_record','target_mapping')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "((kind='snapshot' AND source_id=snapshot_id) OR "
            "(kind='calculation' AND source_id=calculation_run_id) OR "
            "(kind='target' AND source_id=target_version_id) OR "
            "(kind='source_record' AND source_id=source_record_id) OR "
            "(kind='target_mapping' AND source_id=target_mapping_id)) IS TRUE",
            name="source_identity",
        ),
        CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "num_nonnulls(snapshot_id,calculation_run_id,target_version_id,source_record_id,target_mapping_id)=1",
            name="one_source",
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_mapping_id"],
            ["target_mapping_decisions.owner_id", "target_mapping_decisions.id"],
            ondelete="RESTRICT",
        ),
    )
    request_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[UUID] = mapped_column()
    snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    calculation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calculation_runs.id", ondelete="RESTRICT")
    )
    target_version_id: Mapped[UUID | None] = mapped_column()
    source_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    target_mapping_id: Mapped[UUID | None] = mapped_column()
    digest: Mapped[str] = mapped_column(String(64))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ContributionPlanResultModel(PlanningOwned):
    __tablename__ = "contribution_plan_revisions"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id"),
        CheckConstraint(
            "outcome IN ('optimal','feasible_nonoptimal','infeasible','unavailable','failed')",
            name="outcome_allowed",
        ),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("residual_cash IS NULL OR residual_cash >= 0", name="residual_nonnegative"),
    )
    request_id: Mapped[UUID] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(30))
    method_version: Mapped[str] = mapped_column(String(80))
    content_digest: Mapped[str] = mapped_column(String(64))
    residual_cash: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    objective_before: Mapped[list[Decimal]] = mapped_column(ARRAY(ExactNumeric()))
    objective_after: Mapped[list[Decimal]] = mapped_column(ARRAY(ExactNumeric()))
    lower_bound: Mapped[list[Decimal]] = mapped_column(ARRAY(ExactNumeric()))
    objective_gap: Mapped[list[Decimal]] = mapped_column(ARRAY(ExactNumeric()))
    search_nodes: Mapped[int] = mapped_column(Integer)
    canonical_result: Mapped[bytes] = mapped_column(LargeBinary)


class ContributionPlanLineModel(PlanningOwned):
    __tablename__ = "contribution_plan_lines"
    __table_args__ = (
        _owned(),
        _result_fk(),
        UniqueConstraint("result_id", "ordinal"),
        UniqueConstraint("result_id", "node_key", name="uq_plan_lines_result_key"),
        CheckConstraint("recommended_amount >= 0", name="no_sales"),
    )
    result_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    node_key: Mapped[str] = mapped_column(String(80))
    target_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("target_nodes.id", ondelete="RESTRICT")
    )
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    holding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("target_holdings.id", ondelete="RESTRICT")
    )
    current_value: Mapped[Decimal] = mapped_column(ExactNumeric())
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    current_weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    target_weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    post_value: Mapped[Decimal] = mapped_column(ExactNumeric())
    post_weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    recommended_amount: Mapped[Decimal] = mapped_column(ExactNumeric())
    currency: Mapped[str] = mapped_column(String(3))
    minimum_funded_amount: Mapped[Decimal] = mapped_column(ExactNumeric())
    value_increment: Mapped[Decimal] = mapped_column(ExactNumeric())
    excluded: Mapped[bool] = mapped_column(Boolean)
    binding_constraint_keys: Mapped[list[str]] = mapped_column(ARRAY(String(80)))


class ContributionPlanExplanationModel(PlanningOwned):
    __tablename__ = "contribution_plan_explanations"
    __table_args__ = (_owned(), _result_fk(), UniqueConstraint("result_id", "ordinal"))
    result_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(80))
    constraint_keys: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    node_keys: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    message: Mapped[str] = mapped_column(String(1000))
    severity: Mapped[str] = mapped_column(String(20))


class PlanningCommandIdentityModel(PlanningOwned):
    __tablename__ = "planning_command_identities"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint(
            "owner_id",
            "broker_account_id",
            "command_kind",
            "idempotency_key",
            name="uq_planning_command_identity",
        ),
        CheckConstraint("command_kind IN ('create_plan','revise_plan')", name="command_allowed"),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    request_id: Mapped[UUID] = mapped_column()
    command_kind: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    request_digest: Mapped[str] = mapped_column(String(64))
    actor_principal_id: Mapped[str] = mapped_column(String(255))


class ContributionPlanJobModel(PlanningOwned):
    __tablename__ = "contribution_plan_jobs"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id"),
        CheckConstraint(
            "state IN ('queued','running','succeeded','failed','expired','cancelled')",
            name="state_allowed",
        ),
        CheckConstraint(
            "consumer_attempts >= 0 AND consumer_attempts <= 4", name="attempts_bounded"
        ),
        Index("ix_plan_jobs_state_lease", "state", "lease_expires_at", "id"),
    )
    request_id: Mapped[UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(20))
    consumer_attempts: Mapped[int] = mapped_column(Integer)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consumer_id: Mapped[str | None] = mapped_column(String(120))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ContributionPlanOutboxModel(PlanningOwned):
    __tablename__ = "contribution_plan_dispatch_outbox"
    __table_args__ = (
        _owned(),
        UniqueConstraint("job_id"),
        ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["contribution_plan_jobs.owner_id", "contribution_plan_jobs.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("task_name = 'plans.calculate.v1'", name="fixed_task"),
        CheckConstraint(
            "publication_attempts >= 0 AND publication_attempts <= 8", name="attempts_bounded"
        ),
        CheckConstraint(
            "state IN ('pending','claimed','published','completed','dead_letter')",
            name="state_allowed",
        ),
        Index("ix_plan_outbox_available", "state", "available_at", "id"),
    )
    job_id: Mapped[UUID] = mapped_column()
    task_name: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(20))
    publication_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    claim_token: Mapped[UUID | None] = mapped_column()
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dispatcher_id: Mapped[str | None] = mapped_column(String(120))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str | None] = mapped_column(String(80))


class ContributionPlanAttemptModel(PlanningOwned):
    __tablename__ = "contribution_plan_attempts"
    __table_args__ = (
        _owned(),
        ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["contribution_plan_jobs.owner_id", "contribution_plan_jobs.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", "sequence"),
        CheckConstraint("kind IN ('publication','consumer')", name="kind_allowed"),
        CheckConstraint(
            "event IN ('claimed','published','heartbeat','succeeded','failed','expired')",
            name="event_allowed",
        ),
    )
    job_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(20))
    attempt_number: Mapped[int] = mapped_column(Integer)
    claim_token: Mapped[UUID] = mapped_column()
    failure_code: Mapped[str | None] = mapped_column(String(80))


class PlanningAuditModel(PlanningOwned):
    __tablename__ = "planning_audit_events"
    __table_args__ = (
        _owned(),
        _request_fk(),
        UniqueConstraint("request_id", "kind"),
        CheckConstraint("kind IN ('requested','completed','failed')", name="kind_allowed"),
    )
    request_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30))
    actor_principal_id: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str] = mapped_column(String(120))


class AnalyticsRunModel(PlanningOwned):
    __tablename__ = "analytics_runs"
    __table_args__ = (
        _owned(),
        UniqueConstraint(
            "owner_id",
            "broker_account_id",
            "kind",
            "input_digest",
            name="uq_analytics_runs_semantic_input",
        ),
        CheckConstraint(
            "kind IN "
            "('actual_vs_target','drift','performance','benchmark','income','attribution','cash_flow','xray')",
            name="kind_allowed",
        ),
    )
    broker_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(30))
    input_digest: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(80))
    reporting_currency: Mapped[str] = mapped_column(String(3))
    valuation_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    canonical_input: Mapped[bytes] = mapped_column(LargeBinary)
    canonical_result: Mapped[bytes] = mapped_column(LargeBinary)


class AnalyticsSourceModel(PlanningOwned):
    __tablename__ = "analytics_run_sources"
    __table_args__ = (
        _owned(),
        ForeignKeyConstraint(
            ["owner_id", "xray_input_id"],
            ["xray_input_snapshots.owner_id", "xray_input_snapshots.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "historical_input_id"],
            ["historical_input_snapshots.owner_id", "historical_input_snapshots.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["analytics_runs.owner_id", "analytics_runs.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(snapshot_id,target_version_id,source_record_id,"
            "historical_input_id,xray_input_id) = 1",
            name="one_source",
        ),
        ForeignKeyConstraint(
            ["owner_id", "target_version_id"],
            ["target_versions.owner_id", "target_versions.id"],
            ondelete="RESTRICT",
        ),
    )
    historical_input_id: Mapped[UUID | None] = mapped_column()
    xray_input_id: Mapped[UUID | None] = mapped_column()
    run_id: Mapped[UUID] = mapped_column()
    snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    target_version_id: Mapped[UUID | None] = mapped_column()
    source_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT")
    )
    digest: Mapped[str] = mapped_column(String(64))


class AnalyticsDriftRowModel(PlanningOwned):
    __tablename__ = "analytics_drift_rows"
    __table_args__ = (
        _owned(),
        ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["analytics_runs.owner_id", "analytics_runs.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "ordinal"),
        UniqueConstraint("run_id", "key", name="uq_analytics_rows_run_key"),
    )
    run_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(120))
    node_id: Mapped[UUID | None] = mapped_column(ForeignKey("target_nodes.id", ondelete="RESTRICT"))
    holding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("target_holdings.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(30))
    parent_key: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(255))
    depth: Mapped[int] = mapped_column(Integer)
    listing_id: Mapped[UUID | None] = mapped_column(ForeignKey("listings.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    target_weight: Mapped[Decimal] = mapped_column(ExactNumeric())
    actual_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    currency: Mapped[str] = mapped_column(String(3))
    actual_direct_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    effective_weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    effective_weight_reason: Mapped[str] = mapped_column(String(80))
    signed_drift: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    absolute_drift: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    relative_drift: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    relative_drift_reason: Mapped[str | None] = mapped_column(String(80))
    classification: Mapped[str | None] = mapped_column(String(30))
    monetary_gap: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    quality_state: Mapped[str] = mapped_column(String(30))


class PlanningCollectionBindingModel(PlanningOwned):
    __tablename__ = "planning_collection_bindings"
    __table_args__ = (
        _owned(),
        UniqueConstraint("collection_snapshot_id"),
        ForeignKeyConstraint(
            ["owner_id", "collection_snapshot_id"],
            ["collection_query_snapshots.owner_id", "collection_query_snapshots.id"],
            ondelete="CASCADE",
        ),
        _request_fk(),
        _result_fk(),
        ForeignKeyConstraint(
            ["owner_id", "run_id"],
            ["analytics_runs.owner_id", "analytics_runs.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("num_nonnulls(request_id,result_id,run_id)=1", name="one_source"),
        CheckConstraint("cache_key ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_planning_collection_cache", "owner_id", "cache_key"),
    )
    collection_snapshot_id: Mapped[UUID] = mapped_column()
    cache_key: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[UUID | None] = mapped_column()
    result_id: Mapped[UUID | None] = mapped_column()
    run_id: Mapped[UUID | None] = mapped_column()


PLANNING_MODELS = (
    ContributionPlanModel,
    ContributionPlanRequestModel,
    ContributionPlanInputModel,
    ContributionPlanCatalogModel,
    ContributionPlanConstraintModel,
    ContributionPlanSelectionModel,
    ContributionPlanHoldingConstraintModel,
    ContributionPlanSourceModel,
    ContributionPlanResultModel,
    ContributionPlanLineModel,
    ContributionPlanExplanationModel,
    PlanningCommandIdentityModel,
    ContributionPlanJobModel,
    ContributionPlanOutboxModel,
    ContributionPlanAttemptModel,
    PlanningAuditModel,
    AnalyticsRunModel,
    AnalyticsSourceModel,
    AnalyticsDriftRowModel,
    PlanningCollectionBindingModel,
)


# Every normalized financial scalar rejects PostgreSQL's nonfinite numeric values.
for _model in PLANNING_MODELS:
    for _column in _model.__table__.columns:
        if isinstance(_column.type, ExactNumeric):
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} IS NULL OR {_column.name} NOT IN "
                    "('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)",
                    name=f"f_{_column.name}",
                )
            )
        if _column.name in {
            "currency",
            "reporting_currency",
            "fx_base_currency",
            "fx_quote_currency",
        }:
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} IS NULL OR {_column.name} ~ '^[A-Z]{{3}}$'",
                    name=f"format_{_column.name}",
                )
            )

for _bounded_model, _document in (
    (ContributionPlanRequestModel, "canonical_input"),
    (ContributionPlanResultModel, "canonical_result"),
    (AnalyticsRunModel, "canonical_input"),
    (AnalyticsRunModel, "canonical_result"),
):
    cast(Table, _bounded_model.__table__).append_constraint(
        CheckConstraint(
            f"octet_length({_document}) <= "
            + (
                "CASE WHEN kind IN ('performance','benchmark','income','attribution','cash_flow') "
                "THEN 33554432 ELSE 8388608 END"
                if _bounded_model is AnalyticsRunModel
                else "8388608"
            ),
            name=f"bound_{_document}",
        )
    )
