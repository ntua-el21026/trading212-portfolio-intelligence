"""Closed risk commands and bounded views shared by all application transports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from trading212_domain.errors import fail_validation
from trading212_domain.historical import HistoricalRatioMetric, HistoricalWindow
from trading212_domain.historical_results import HistoricalResultContext
from trading212_domain.risk import RiskDefinitionContent, RiskSeriesStatistics
from trading212_domain.risk_history import RiskAssetSource
from trading212_domain.risk_result import RiskConcentration, RiskMatrix, RiskModel, RiskTail
from trading212_domain.sources import source_integer, source_tuple
from trading212_domain.values import require_bounded_text
from trading212_security.principals import Principal

from .targets import validate_target_idempotency_key
from .views import Page


class RiskErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    RATE_LIMITED = "RATE_LIMITED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    RISK_UNAVAILABLE = "RISK_UNAVAILABLE"
    RUN_EXPIRED = "RUN_EXPIRED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    CURSOR_INVALID = "CURSOR_INVALID"


@dataclass(slots=True)
class RiskServiceError(Exception):
    code: RiskErrorCode
    message: str = "The risk operation cannot be completed."

    def __str__(self) -> str:
        return self.message


class PremiumJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def _ids(*values: UUID) -> None:
    if any(type(value) is not UUID for value in values):
        fail_validation("Canonical UUID identities are required.", field="id")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskCommand:
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        validate_target_idempotency_key(self.idempotency_key)
        require_bounded_text(self.correlation_id, field="correlation_id", maximum=120)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateRiskDefinition(RiskCommand):
    account_id: UUID
    content: RiskDefinitionContent

    def __post_init__(self) -> None:
        RiskCommand.__post_init__(self)
        _ids(self.account_id)
        if not isinstance(self.content, RiskDefinitionContent):
            fail_validation("A risk definition is required.", field="content")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateRiskVersion(RiskCommand):
    definition_id: UUID
    expected_revision: int
    content: RiskDefinitionContent

    def __post_init__(self) -> None:
        RiskCommand.__post_init__(self)
        _ids(self.definition_id)
        source_integer(self.expected_revision, "expected_revision", 1, 512)
        if not isinstance(self.content, RiskDefinitionContent):
            fail_validation("A risk definition is required.", field="content")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateRiskRun(RiskCommand):
    account_id: UUID
    definition_version_id: UUID
    portfolio_snapshot_id: UUID
    historical_input_snapshot_id: UUID
    window: HistoricalWindow
    assets: tuple[RiskAssetSource, ...] = ()
    benchmark_version_id: UUID | None = None
    xray_run_id: UUID | None = None

    def __post_init__(self) -> None:
        RiskCommand.__post_init__(self)
        _ids(
            self.account_id,
            self.definition_version_id,
            self.portfolio_snapshot_id,
            self.historical_input_snapshot_id,
        )
        _ids(*(x for x in (self.benchmark_version_id, self.xray_run_id) if x is not None))
        if not isinstance(self.window, HistoricalWindow):
            fail_validation("An explicit historical window is required.", field="window")
        source_tuple(self.assets, RiskAssetSource, "assets", 32)
        if len({x.instrument_id for x in self.assets}) != len(self.assets) or len(
            {x.series_id for x in self.assets}
        ) != len(self.assets):
            fail_validation("Risk asset mappings must be unique.", field="assets")
        object.__setattr__(
            self, "assets", tuple(sorted(self.assets, key=lambda x: x.instrument_id))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelRiskRun(RiskCommand):
    run_id: UUID

    def __post_init__(self) -> None:
        RiskCommand.__post_init__(self)
        _ids(self.run_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskPageQuery:
    limit: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        source_integer(self.limit, "limit", 1, 100)
        if self.cursor is not None:
            require_bounded_text(self.cursor, field="cursor", maximum=2048)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskVersionView:
    id: UUID
    account_id: UUID
    definition_id: UUID
    version_number: int
    predecessor_id: UUID | None
    content: RiskDefinitionContent
    content_digest: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskDefinitionView:
    id: UUID
    account_id: UUID
    name: str
    revision: int
    archived: bool
    current_version_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskResultView:
    """No private return arrays or complete historical evidence graph in public results."""

    historical_context: HistoricalResultContext
    omitted_sources: int
    omitted_warnings: int
    observed: RiskSeriesStatistics
    maximum_drawdown: HistoricalRatioMetric
    matrix: RiskMatrix
    historical_tail: RiskTail
    parametric_tail: RiskTail
    modeled: RiskModel
    concentration: RiskConcentration
    xray_result_digest: str | None
    modeled_valuation_at: datetime | None
    annualization_factor: int
    covariance_degrees_of_freedom: int
    method_version: str
    schema_version: str
    numerical_profile: str
    content_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRunView:
    id: UUID
    account_id: UUID
    definition_version_id: UUID
    portfolio_snapshot_id: UUID
    historical_input_snapshot_id: UUID
    xray_run_id: UUID | None
    job_id: UUID
    state: PremiumJobState
    failure_code: str | None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    input_digest: str
    result: RiskResultView | None
    result_availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"]


class RiskService(Protocol):
    async def create_definition(
        self, principal: Principal, command: CreateRiskDefinition
    ) -> RiskDefinitionView: ...
    async def create_version(
        self, principal: Principal, command: CreateRiskVersion
    ) -> RiskVersionView: ...
    async def get_definition(
        self, principal: Principal, definition_id: UUID
    ) -> RiskDefinitionView: ...
    async def get_version(self, principal: Principal, version_id: UUID) -> RiskVersionView: ...
    async def list_definitions(
        self, principal: Principal, account_id: UUID, query: RiskPageQuery
    ) -> Page[RiskDefinitionView]: ...
    async def list_versions(
        self, principal: Principal, definition_id: UUID, query: RiskPageQuery
    ) -> Page[RiskVersionView]: ...
    async def create_run(self, principal: Principal, command: CreateRiskRun) -> RiskRunView: ...
    async def get_run(self, principal: Principal, run_id: UUID) -> RiskRunView: ...
    async def list_runs(
        self, principal: Principal, account_id: UUID, query: RiskPageQuery
    ) -> Page[RiskRunView]: ...
    async def get_matrix(self, principal: Principal, run_id: UUID) -> RiskMatrix: ...
    async def cancel_run(self, principal: Principal, command: CancelRiskRun) -> RiskRunView: ...
