"""Normalized immutable risk definitions, pinned requests and canonical projections."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .premium_models import PremiumOwned, digest_constraint, parent, scoped
from .types import ExactNumeric, UTCDateTime


def finite(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR ({column} > '-Infinity'::numeric AND {column} < 'Infinity'::numeric)",
        name=f"{column}_finite",
    )


def metric_pair(value: str, reason: str) -> CheckConstraint:
    return CheckConstraint(
        f"({value} IS NULL) = ({reason} IS NOT NULL)", name=f"{value}_availability"
    )


def owner_source(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{table}.owner_id", f"{table}.id"],
        ondelete="RESTRICT",
        name=f"fk_risk_{table}_{column}",
    )


class RiskDefinitionModel(PremiumOwned):
    __tablename__ = "risk_definitions"
    __table_args__ = (
        scoped(),
        CheckConstraint("revision BETWEEN 1 AND 512", name="revision_bound"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_bound"),
        Index(
            "ix_risk_definitions_owner_account_created",
            "owner_id",
            "account_id",
            "created_at",
            "id",
        ),
    )
    name: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class RiskVersionModel(PremiumOwned):
    __tablename__ = "risk_definition_versions"
    __table_args__ = (
        scoped(),
        parent("definition_id", "risk_definitions"),
        UniqueConstraint(
            "owner_id",
            "account_id",
            "definition_id",
            "id",
            name="uq_risk_version_definition_identity",
        ),
        UniqueConstraint("definition_id", "version_number"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "definition_id", "predecessor_id"],
            [
                "risk_definition_versions.owner_id",
                "risk_definition_versions.account_id",
                "risk_definition_versions.definition_id",
                "risk_definition_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_risk_version_predecessor",
        ),
        owner_source("calendar_id", "source_calendars"),
        digest_constraint("content_digest"),
        CheckConstraint(
            "version_number BETWEEN 1 AND 512 AND (version_number=1) = (predecessor_id IS NULL)",
            name="version_order",
        ),
        CheckConstraint(
            "frequency IN ('daily','monthly') AND return_kind IN ('simple','log')",
            name="return_basis",
        ),
        CheckConstraint(
            "annual_risk_free > -1 AND annual_risk_free <= 1 AND annual_minimum_a"
            "cceptable_return > -1 AND annual_minimum_acceptable_return <= 1",
            name="annual_bounds",
        ),
        CheckConstraint(
            "rolling_window BETWEEN 20 AND CASE WHEN frequency='daily' THEN 252 E"
            "LSE 120 END AND horizon BETWEEN 1 AND CASE WHEN frequency='daily' TH"
            "EN 20 ELSE 12 END",
            name="window_bounds",
        ),
        CheckConstraint(
            "confidence IN (0.90,0.95,0.99) AND shrinkage BETWEEN 0 AND 1", name="estimator_bounds"
        ),
        CheckConstraint(
            "regularization IN ('none','diagonal_shrinkage') AND (regularization "
            "<> 'none' OR shrinkage=0)",
            name="shrinkage_explicit",
        ),
        CheckConstraint(
            "method_version='1.0.0' AND char_length(name) BETWEEN 1 AND 120", name="version_name"
        ),
        Index("ix_risk_versions_definition_number", "definition_id", "version_number", "id"),
    )
    definition_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    predecessor_id: Mapped[UUID | None] = mapped_column()
    calendar_id: Mapped[UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1024))
    frequency: Mapped[str] = mapped_column(String(10))
    return_kind: Mapped[str] = mapped_column(String(10))
    annual_risk_free: Mapped[Decimal] = mapped_column(ExactNumeric())
    annual_minimum_acceptable_return: Mapped[Decimal] = mapped_column(ExactNumeric())
    rolling_window: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[Decimal] = mapped_column(ExactNumeric())
    horizon: Mapped[int] = mapped_column(Integer)
    regularization: Mapped[str] = mapped_column(String(30))
    shrinkage: Mapped[Decimal] = mapped_column(ExactNumeric())
    method_version: Mapped[str] = mapped_column(String(40))
    content_digest: Mapped[str] = mapped_column(String(64))


class RiskRunModel(PremiumOwned):
    __tablename__ = "risk_runs"
    __table_args__ = (
        scoped(),
        parent("id", "premium_runs"),
        parent("definition_version_id", "risk_definition_versions"),
        owner_source("historical_input_id", "historical_input_snapshots"),
        owner_source("benchmark_version_id", "benchmark_versions"),
        owner_source("xray_run_id", "xray_runs"),
        CheckConstraint(
            "reporting_currency ~ '^[A-Z]{3}$' AND window_start_at < window_end_a"
            "t AND window_end_at <= source_cutoff_at",
            name="window_currency",
        ),
        digest_constraint("historical_input_digest"),
        Index("ix_risk_runs_historical", "historical_input_id", "id"),
        Index("ix_risk_runs_xray", "xray_run_id", "id"),
    )
    definition_version_id: Mapped[UUID] = mapped_column()
    historical_input_id: Mapped[UUID] = mapped_column()
    historical_input_digest: Mapped[str] = mapped_column(String(64))
    portfolio_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
    )
    benchmark_version_id: Mapped[UUID | None] = mapped_column()
    xray_run_id: Mapped[UUID | None] = mapped_column()
    window_start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reporting_currency: Mapped[str] = mapped_column(String(3))
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskRunAssetModel(PremiumOwned):
    __tablename__ = "risk_run_assets"
    __table_args__ = (
        scoped(),
        parent("run_id", "risk_runs"),
        owner_source("source_series_id", "market_source_series"),
        UniqueConstraint("run_id", "instrument_id", name="uq_risk_assets_instrument"),
        UniqueConstraint("run_id", "source_series_id", name="uq_risk_assets_source"),
        UniqueConstraint("run_id", "ordinal", name="uq_risk_assets_ordinal"),
        CheckConstraint("ordinal BETWEEN 0 AND 31", name="ordinal_bound"),
        Index("ix_risk_assets_run", "run_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    source_series_id: Mapped[UUID] = mapped_column()


class RiskResultModel(PremiumOwned):
    __tablename__ = "risk_results"
    __table_args__ = (
        scoped(),
        parent("run_id", "risk_runs"),
        UniqueConstraint("run_id"),
        digest_constraint("content_digest"),
        CheckConstraint("octet_length(canonical_result) <= 33554432", name="payload_bound"),
        CheckConstraint(
            "series_count BETWEEN 1 AND 34 AND interval_count BETWEEN 0 AND 10000"
            "0 AND matrix_cell_count BETWEEN 0 AND 3072 AND component_count BETWE"
            "EN 0 AND 32 AND metric_count BETWEEN 1 AND 8192",
            name="count_bound",
        ),
        Index("ix_risk_result_run", "run_id", "id"),
    )
    run_id: Mapped[UUID] = mapped_column()
    content_digest: Mapped[str] = mapped_column(String(64))
    canonical_result: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    series_count: Mapped[int] = mapped_column(Integer)
    interval_count: Mapped[int] = mapped_column(Integer)
    matrix_cell_count: Mapped[int] = mapped_column(Integer)
    component_count: Mapped[int] = mapped_column(Integer)
    metric_count: Mapped[int] = mapped_column(Integer)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskSeriesModel(PremiumOwned):
    __tablename__ = "risk_series"
    __table_args__ = (
        scoped(),
        parent("result_id", "risk_results"),
        UniqueConstraint("result_id", "series_key"),
        UniqueConstraint(
            "owner_id", "account_id", "result_id", "id", name="uq_risk_series_result_identity"
        ),
        CheckConstraint(
            "kind IN ('portfolio','benchmark','asset') AND (kind='asset') = (inst"
            "rument_id IS NOT NULL)",
            name="series_identity",
        ),
        CheckConstraint(
            "(kind IN ('portfolio','benchmark') AND series_key=kind) OR (kind='as"
            "set' AND series_key=instrument_id::text)",
            name="series_key",
        ),
        CheckConstraint("interval_count BETWEEN 0 AND 3660", name="count_bound"),
        Index("ix_risk_series_result", "result_id", "id"),
    )
    result_id: Mapped[UUID] = mapped_column()
    series_key: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))
    instrument_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    interval_count: Mapped[int] = mapped_column(Integer)


class RiskIntervalModel(PremiumOwned):
    __tablename__ = "risk_intervals"
    __table_args__ = (
        scoped(),
        parent("result_id", "risk_results"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "series_id"],
            [
                "risk_series.owner_id",
                "risk_series.account_id",
                "risk_series.result_id",
                "risk_series.id",
            ],
            ondelete="RESTRICT",
            name="fk_risk_interval_series_result",
        ),
        UniqueConstraint("series_id", "ordinal"),
        UniqueConstraint("series_id", "start_at", "end_at", name="uq_risk_intervals_boundaries"),
        CheckConstraint("ordinal BETWEEN 0 AND 3659 AND start_at < end_at", name="interval_bound"),
        CheckConstraint("simple_return IS NULL OR simple_return >= -1", name="return_bound"),
        finite("simple_return"),
        metric_pair("simple_return", "reason"),
        CheckConstraint(
            "quality IN ('fresh','stale','partial','estimated','unreconciled','fa"
            "iled') AND (simple_return IS NOT NULL OR quality <> 'fresh')",
            name="quality_bound",
        ),
        Index("ix_risk_intervals_result", "result_id", "id"),
    )
    result_id: Mapped[UUID] = mapped_column()
    series_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    simple_return: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    quality: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(40))


class RiskMatrixCellModel(PremiumOwned):
    __tablename__ = "risk_matrix_cells"
    __table_args__ = (
        Index("ix_risk_matrix_col_cleanup", "result_id", "column_series_id"),
        Index("ix_risk_matrix_row_cleanup", "result_id", "row_series_id"),
        scoped(),
        parent("result_id", "risk_results"),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "row_series_id"],
            [
                "risk_series.owner_id",
                "risk_series.account_id",
                "risk_series.result_id",
                "risk_series.id",
            ],
            ondelete="RESTRICT",
            name="fk_risk_matrix_row_result",
        ),
        ForeignKeyConstraint(
            ["owner_id", "account_id", "result_id", "column_series_id"],
            [
                "risk_series.owner_id",
                "risk_series.account_id",
                "risk_series.result_id",
                "risk_series.id",
            ],
            ondelete="RESTRICT",
            name="fk_risk_matrix_column_result",
        ),
        UniqueConstraint("result_id", "kind", "row_series_id", "column_series_id"),
        CheckConstraint(
            "kind IN ('covariance','regularized_covariance','correlation')", name="kind_allowed"
        ),
        CheckConstraint(
            "kind <> 'correlation' OR value IS NULL OR value BETWEEN -1 AND 1",
            name="correlation_bound",
        ),
        metric_pair("value", "reason"),
        finite("value"),
        Index("ix_risk_matrix_result", "result_id", "id"),
    )
    result_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30))
    row_series_id: Mapped[UUID] = mapped_column()
    column_series_id: Mapped[UUID] = mapped_column()
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    reason: Mapped[str | None] = mapped_column(String(40))


class RiskMetricModel(PremiumOwned):
    __tablename__ = "risk_metrics"
    __table_args__ = (
        scoped(),
        parent("result_id", "risk_results"),
        UniqueConstraint("result_id", "key", "ordinal"),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 3660 AND char_length(key) BETWEEN 1 AND 80", name="key_bound"
        ),
        CheckConstraint(
            "(value IS NULL AND reason IS NOT NULL) OR (value IS NOT NULL AND "
            "(reason IS NULL OR key='observed.maximum_drawdown'))",
            name="value_availability",
        ),
        finite("value"),
        Index("ix_risk_metrics_result", "result_id", "id"),
    )
    result_id: Mapped[UUID] = mapped_column()
    key: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    reason: Mapped[str | None] = mapped_column(String(80))


class RiskComponentModel(PremiumOwned):
    __tablename__ = "risk_components"
    __table_args__ = (
        scoped(),
        parent("result_id", "risk_results"),
        UniqueConstraint("result_id", "instrument_id"),
        CheckConstraint("weight IS NULL OR weight BETWEEN 0 AND 1", name="weight_bound"),
        metric_pair("weight", "weight_reason"),
        metric_pair("marginal", "marginal_reason"),
        metric_pair("component", "component_reason"),
        finite("weight"),
        finite("marginal"),
        finite("component"),
        Index("ix_risk_components_result", "result_id", "id"),
    )
    result_id: Mapped[UUID] = mapped_column()
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    weight: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    weight_reason: Mapped[str | None] = mapped_column(String(40))
    marginal: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    marginal_reason: Mapped[str | None] = mapped_column(String(40))
    component: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    component_reason: Mapped[str | None] = mapped_column(String(40))


RISK_MODELS = (
    RiskDefinitionModel,
    RiskVersionModel,
    RiskRunModel,
    RiskRunAssetModel,
    RiskResultModel,
    RiskSeriesModel,
    RiskIntervalModel,
    RiskMatrixCellModel,
    RiskMetricModel,
    RiskComponentModel,
)
