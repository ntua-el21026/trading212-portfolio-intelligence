"""Authorized bounded requests and service contracts for immutable Portfolio X-ray."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol

from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.sources import SourceLicense, source_id, source_integer
from trading212_domain.values import CurrencyCode, require_utc
from trading212_domain.xray import (
    CashRoot,
    PositionRoot,
    XrayDependencyKind,
    XrayDimension,
    XrayMoneyMetric,
    XrayRatioMetric,
    XrayReason,
    XrayResidualKind,
    XrayWarningCode,
)
from trading212_domain.xray_result import (
    XrayDimensionSummary,
    XrayFundEdge,
    XrayPathClassification,
    XrayPortfolioSummary,
)
from trading212_security.principals import Principal

from .sources import SourceFreshnessView
from .targets import TargetPageQuery
from .views import Page


class XrayServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_SNAPSHOT_MISMATCH = "INPUT_SNAPSHOT_MISMATCH"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    XRAY_UNAVAILABLE = "XRAY_UNAVAILABLE"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    SOURCE_REVISION_CONFLICT = "SOURCE_REVISION_CONFLICT"


@dataclass(slots=True)
class XrayServiceError(Exception):
    code: XrayServiceErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplicitCurrency:
    reporting_currency: CurrencyCode

    def __post_init__(self) -> None:
        if not isinstance(self.reporting_currency, CurrencyCode):
            fail_validation("A typed reporting currency is required.", field="reporting_currency")


@dataclass(frozen=True, slots=True)
class SnapshotCurrency:
    """Internal MCP overlap selection, resolved after snapshot authorization."""


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayRunRequest:
    snapshot_id: str
    source_cutoff_at: datetime
    currency: ExplicitCurrency | SnapshotCurrency
    run_id: str | None = None

    def __post_init__(self) -> None:
        source_id(self.snapshot_id, "snapshot_id")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        if not isinstance(self.currency, (ExplicitCurrency, SnapshotCurrency)):
            fail_validation("A closed currency selection is required.", field="currency")
        if self.run_id is not None:
            source_id(self.run_id, "run_id")


def _dimension(dimension: XrayDimension, normalized_known_only: bool) -> None:
    if not isinstance(dimension, XrayDimension):
        fail_validation("A typed X-ray dimension is required.", field="dimension")
    if type(normalized_known_only) is not bool:
        fail_validation("Normalization must be explicit.", field="normalized_known_only")


@dataclass(frozen=True, slots=True, kw_only=True)
class Exposures:
    dimension: XrayDimension = XrayDimension.COMPANY
    normalized_known_only: bool = False
    view: Literal["exposures"] = field(default="exposures", init=False)

    def __post_init__(self) -> None:
        _dimension(self.dimension, self.normalized_known_only)


@dataclass(frozen=True, slots=True, kw_only=True)
class Paths:
    dimension: XrayDimension = XrayDimension.COMPANY
    normalized_known_only: bool = False
    exposure_id: str | None = None
    view: Literal["paths"] = field(default="paths", init=False)

    def __post_init__(self) -> None:
        _dimension(self.dimension, self.normalized_known_only)
        if self.exposure_id is not None:
            source_id(self.exposure_id, "exposure_id")


@dataclass(frozen=True, slots=True)
class HeldFunds:
    view: Literal["held_funds"] = field(default="held_funds", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectiveExposureQuery(TargetPageQuery):
    request: XrayRunRequest
    options: Exposures | Paths | HeldFunds = field(default_factory=Exposures)

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if not isinstance(self.request, XrayRunRequest):
            fail_validation("A complete X-ray request is required.", field="request")
        if not isinstance(self.options, (Exposures, Paths, HeldFunds)):
            fail_validation("A closed exposure view is required.", field="options")
        if isinstance(self.options, Paths) and self.request.run_id is None and self.cursor is None:
            fail_validation("Path detail requires a retained run pin.", field="run_id")


def _funds(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not 2 <= len(values) <= 32:
        fail_validation("Select between two and 32 held funds.", field="fund_ids")
    for value in values:
        source_id(value, "fund_ids")
    if len(set(values)) != len(values):
        fail_validation("Selected fund IDs must be unique.", field="fund_ids")
    return tuple(sorted(values))


def _pair(left: str, right: str) -> tuple[str, str]:
    source_id(left, "left_fund_id")
    source_id(right, "right_fund_id")
    if left == right:
        fail_validation("Select two distinct held funds.", field="right_fund_id")
    return (left, right) if left < right else (right, left)


@dataclass(frozen=True, slots=True, kw_only=True)
class Pairs:
    fund_ids: tuple[str, ...]
    view: Literal["pairs"] = field(default="pairs", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fund_ids", _funds(self.fund_ids))


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonEntities:
    fund_ids: tuple[str, ...]
    left_fund_id: str
    right_fund_id: str
    view: Literal["common_entities"] = field(default="common_entities", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fund_ids", _funds(self.fund_ids))
        left, right = _pair(self.left_fund_id, self.right_fund_id)
        if left not in self.fund_ids or right not in self.fund_ids:
            fail_validation("The common-entity pair must be selected.", field="fund_ids")
        object.__setattr__(self, "left_fund_id", left)
        object.__setattr__(self, "right_fund_id", right)


@dataclass(frozen=True, slots=True, kw_only=True)
class McpTopPair:
    left_fund_id: str
    right_fund_id: str
    top_n: int = 25
    view: Literal["mcp_top_pair"] = field(default="mcp_top_pair", init=False)

    def __post_init__(self) -> None:
        left, right = _pair(self.left_fund_id, self.right_fund_id)
        object.__setattr__(self, "left_fund_id", left)
        object.__setattr__(self, "right_fund_id", right)
        source_integer(self.top_n, "top_n", 1, 50)


@dataclass(frozen=True, slots=True, kw_only=True)
class EtfOverlapQuery(TargetPageQuery):
    request: XrayRunRequest
    options: Pairs | CommonEntities | McpTopPair

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if not isinstance(self.request, XrayRunRequest):
            fail_validation("A complete X-ray request is required.", field="request")
        if not isinstance(self.options, (Pairs, CommonEntities, McpTopPair)):
            fail_validation("A closed overlap view is required.", field="options")
        if (
            isinstance(self.options, CommonEntities)
            and self.request.run_id is None
            and self.cursor is None
        ):
            fail_validation("Common-entity detail requires a retained run pin.", field="run_id")
        if isinstance(self.options, McpTopPair) and (self.cursor is not None or self.limit != 25):
            fail_validation("MCP Top does not accept pagination selectors.", field="cursor")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentSnapshotQuery:
    account_id: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        if (self.account_id is None) != (self.run_id is None):
            fail_validation("Dependent source detail needs account and run.", field="run_id")
        for name in ("account_id", "run_id"):
            value = getattr(self, name)
            if value is not None:
                source_id(value, name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentHoldingsQuery(TargetPageQuery):
    account_id: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        ConstituentSnapshotQuery(account_id=self.account_id, run_id=self.run_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayMethodView:
    name: Literal["xray_v1"] = "xray_v1"
    version: Literal["1.1.0"] = "1.1.0"
    numeric_policy: Literal["xray_decimal256_exact_q18_v1"] = "xray_decimal256_exact_q18_v1"
    traversal_policy: Literal["xray_position_then_cash_uuid_v1"] = "xray_position_then_cash_uuid_v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayPolicyReference:
    kind: Literal[
        "calculation",
        "provider_selection",
        "identity",
        "classification",
        "freshness",
        "quality",
        "traversal",
        "threshold",
    ]
    id: str
    version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class XraySourceReferenceView:
    id: str
    kind: XrayDependencyKind
    subject_id: str
    content_digest: str
    source_at: datetime | None
    first_observed_at: datetime | None
    provider_id: str | None
    provider_name: str | None
    license_version_id: str | None
    confidence: Decimal | None
    quality: QualityState


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayWarningView:
    code: XrayWarningCode
    reason: XrayReason | None
    source_reference_ids: tuple[str, ...]
    source_count: int
    source_omitted_count: int
    path_keys: tuple[str, ...]
    path_count: int
    path_omitted_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayResidualView:
    key: str
    value: Decimal
    currency: CurrencyCode | None
    kind: XrayResidualKind
    consumer_key: str
    child_count: int
    parent_separately_rounded: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayAccessView:
    reproducibility: Literal["reproducible", "inputs_expired", "license_restricted"] = (
        "reproducible"
    )
    status_reference_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayContext:
    account_id: str
    snapshot_id: str
    run_id: str
    input_snapshot_id: str
    input_digest: str
    content_digest: str
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    calculated_at: datetime
    quality_evaluated_at: datetime
    method: XrayMethodView
    policies: tuple[XrayPolicyReference, ...]
    sources: tuple[XraySourceReferenceView, ...]
    source_count: int
    source_omitted_count: int
    warnings: tuple[XrayWarningView, ...]
    warning_count: int
    warning_omitted_count: int
    residuals: tuple[XrayResidualView, ...]
    residual_count: int
    residual_omitted_count: int
    access: XrayAccessView = field(default_factory=XrayAccessView)

    def __post_init__(self) -> None:
        for name in ("account_id", "snapshot_id", "run_id", "input_snapshot_id"):
            source_id(getattr(self, name), name)
        for name in ("valuation_at", "source_cutoff_at", "calculated_at", "quality_evaluated_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        for count, omitted, items in (
            (self.source_count, self.source_omitted_count, self.sources),
            (self.warning_count, self.warning_omitted_count, self.warnings),
            (self.residual_count, self.residual_omitted_count, self.residuals),
        ):
            source_integer(count, "total_count", 0, 100_000)
            source_integer(omitted, "omitted_count", 0, count)
            if len(items) > 64 or len(items) + omitted != count:
                fail_validation("X-ray preview counts disagree.", field="context")


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayExposureRowView:
    id: str
    dimension: XrayDimension
    bucket_key: str
    name: str
    direct: XrayMoneyMetric
    indirect: XrayMoneyMetric
    effective: XrayMoneyMetric
    direct_weight: XrayRatioMetric
    indirect_weight: XrayRatioMetric
    absolute_weight: XrayRatioMetric
    normalized_known_weight: XrayRatioMetric | None
    path_count: int
    residuals: tuple[XrayResidualView, ...]
    confidence: Decimal | None
    quality: QualityState


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayPathRowView:
    id: str
    key: str
    root_key: str
    root: PositionRoot | CashRoot
    instrument_id: str | None
    entity_id: str | None
    name: str
    explicit_cash: bool
    unresolved_reason: XrayReason | None
    fund_edges: tuple[XrayFundEdge, ...]
    reporting_value: XrayMoneyMetric
    absolute_weight: XrayRatioMetric
    relative_weight: XrayRatioMetric
    normalized_known_weight: XrayRatioMetric | None
    classification: XrayPathClassification | None
    identity_decision_ids: tuple[str, ...]
    source_reference_ids: tuple[str, ...]
    sources: tuple[XraySourceReferenceView, ...]
    residuals: tuple[XrayResidualView, ...]
    quality: QualityState
    confidence: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayHeldFundView:
    instrument_id: str
    name: str
    position_count: int
    composition_root_key: str
    constituent_snapshot_id: str | None
    source_at: datetime | None
    unit_coverage: XrayRatioMetric
    cash_weight: XrayRatioMetric
    unresolved_weight: XrayRatioMetric
    complete: bool
    quality: QualityState
    confidence: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayOverlapPairView:
    id: str
    left: XrayHeldFundView
    right: XrayHeldFundView
    overlap: XrayRatioMetric
    common_entity_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayCommonEntityView:
    id: str
    entity_id: str
    name: str
    left_weight: XrayRatioMetric
    right_weight: XrayRatioMetric
    common_weight: XrayRatioMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class ExposuresView:
    context: XrayContext
    summary: XrayPortfolioSummary
    dimension_summary: XrayDimensionSummary
    dimension_residuals: tuple[XrayResidualView, ...]
    normalized_known_only: bool
    exposures: Page[XrayExposureRowView]
    view: Literal["exposures"] = field(default="exposures", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class PathsView:
    context: XrayContext
    summary: XrayPortfolioSummary
    dimension_summary: XrayDimensionSummary
    dimension_residuals: tuple[XrayResidualView, ...]
    normalized_known_only: bool
    paths: Page[XrayPathRowView]
    view: Literal["paths"] = field(default="paths", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class HeldFundsView:
    context: XrayContext
    summary: XrayPortfolioSummary
    held_funds: Page[XrayHeldFundView]
    view: Literal["held_funds"] = field(default="held_funds", init=False)


type EffectiveExposureView = ExposuresView | PathsView | HeldFundsView


@dataclass(frozen=True, slots=True, kw_only=True)
class OverlapPairsView:
    context: XrayContext
    summary: XrayPortfolioSummary
    selected_fund_ids: tuple[str, ...]
    pairs: Page[XrayOverlapPairView]
    view: Literal["pairs"] = field(default="pairs", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonEntitiesView:
    context: XrayContext
    summary: XrayPortfolioSummary
    selected_fund_ids: tuple[str, ...]
    pair: XrayOverlapPairView
    common_entities: Page[XrayCommonEntityView]
    view: Literal["common_entities"] = field(default="common_entities", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class McpTopPairView:
    context: XrayContext
    summary: XrayPortfolioSummary
    pair: XrayOverlapPairView
    common_entities: tuple[XrayCommonEntityView, ...]
    total_count: int
    returned_count: int
    omitted_count: int
    omitted_common_weight: XrayRatioMetric
    view: Literal["mcp_top_pair"] = field(default="mcp_top_pair", init=False)


type EtfOverlapView = OverlapPairsView | CommonEntitiesView | McpTopPairView


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentSnapshotHeader:
    id: str
    fund_instrument_id: str
    fund_name: str
    fund_mapping_id: str
    source_at: datetime
    first_observed_at: datetime
    content_digest: str
    provider_id: str
    provider_name: str
    license: SourceLicense
    holding_count: int
    known_weight: Decimal | None
    unresolved_weight: Decimal | None
    cash_weight: Decimal | None
    quality: QualityState
    confidence: Decimal | None
    freshness: SourceFreshnessView
    freshness_evaluated_at: datetime
    access: XrayAccessView = field(default_factory=XrayAccessView)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentHoldingView:
    id: str
    source_key: str
    weight: Decimal
    state: Literal["resolved", "cash", "unresolved"]
    currency: CurrencyCode
    instrument_id: str | None
    entity_id: str | None
    name: str | None
    confidence: Decimal | None
    evidence_key: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentHoldingPage:
    snapshot_id: str
    items: tuple[ConstituentHoldingView, ...]
    next_cursor: str | None
    limit: int
    total: int


class XrayService(Protocol):
    async def get_effective_exposure(
        self, principal: Principal, account_id: str, *, query: EffectiveExposureQuery
    ) -> EffectiveExposureView: ...
    async def get_etf_overlap(
        self, principal: Principal, account_id: str, *, query: EtfOverlapQuery
    ) -> EtfOverlapView: ...
    async def get_constituent_snapshot(
        self, principal: Principal, snapshot_id: str, *, query: ConstituentSnapshotQuery
    ) -> ConstituentSnapshotHeader: ...
    async def list_constituent_holdings(
        self, principal: Principal, snapshot_id: str, *, query: ConstituentHoldingsQuery
    ) -> ConstituentHoldingPage: ...
