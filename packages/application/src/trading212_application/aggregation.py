"""Six closed owner/member aggregation operations; no generic financial source input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from trading212_domain.aggregation import (
    AggregateActivityWindow,
    AggregateFxBinding,
    AggregateRecord,
    AggregateSelectionContent,
    AggregateView,
    aggregate_bound,
    aggregate_unique,
)
from trading212_domain.errors import fail_validation
from trading212_domain.values import require_bounded_text
from trading212_security.principals import Principal, Scope

from .targets import TargetServiceError, validate_target_idempotency_key
from .views import Page

if TYPE_CHECKING:
    from .aggregation_views import AggregateRunPage

AGGREGATE_READ_SCOPES = frozenset(
    (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.AGGREGATE_READ)
)
AGGREGATE_WRITE_SCOPES = AGGREGATE_READ_SCOPES | {Scope.AGGREGATE_WRITE}


class AggregateErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    RUN_EXPIRED = "RUN_EXPIRED"
    CURSOR_INVALID = "CURSOR_INVALID"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


@dataclass(slots=True)
class AggregateServiceError(Exception):
    code: AggregateErrorCode
    message: str = "The aggregation operation cannot be completed."

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateCommand:
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        try:
            validate_target_idempotency_key(self.idempotency_key)
        except TargetServiceError:
            fail_validation("Invalid aggregation idempotency key.")
        require_bounded_text(self.correlation_id, field="correlation_id", maximum=120)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAggregateSelection(AggregateCommand):
    content: AggregateSelectionContent

    def __post_init__(self) -> None:
        AggregateCommand.__post_init__(self)
        if type(self.content) is not AggregateSelectionContent:
            fail_validation("An exact aggregate selection is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAggregateRun(AggregateCommand):
    selection_id: UUID
    expected_revision: int
    fx_bindings: tuple[AggregateFxBinding, ...] = ()
    activity_window: AggregateActivityWindow | None = None

    def __post_init__(self) -> None:
        AggregateCommand.__post_init__(self)
        if (
            type(self.selection_id) is not UUID
            or type(self.expected_revision) is not int
            or not 1 <= self.expected_revision <= 2147483647
        ):
            fail_validation("A selected aggregate and operational revision are required.")
        if type(self.fx_bindings) is not tuple or any(
            type(x) is not AggregateFxBinding for x in self.fx_bindings
        ):
            fail_validation("Exact FX observation bindings are required.")
        aggregate_bound(len(self.fx_bindings) <= 256, "fx")
        aggregate_unique(tuple((x.account_id, x.currency) for x in self.fx_bindings), "fx")
        object.__setattr__(
            self,
            "fx_bindings",
            tuple(sorted(self.fx_bindings, key=lambda x: (x.account_id, str(x.currency)))),
        )
        if (
            self.activity_window is not None
            and type(self.activity_window) is not AggregateActivityWindow
        ):
            fail_validation("An explicit activity window is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregatePageQuery:
    limit: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            fail_validation("Aggregation page size must be1..100.")
        if self.cursor is not None:
            require_bounded_text(self.cursor, field="cursor", maximum=2048)


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateRunQuery(AggregatePageQuery):
    view: AggregateView = AggregateView.HOLDINGS

    def __post_init__(self) -> None:
        AggregatePageQuery.__post_init__(self)
        if type(self.view) is not AggregateView:
            fail_validation("A fixed aggregation view is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateSelectionView(AggregateRecord):
    selection_id: UUID
    content: AggregateSelectionContent
    content_digest: str
    revision: int
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateRunReceipt(AggregateRecord):
    run_id: UUID
    selection_id: UUID
    selection_revision: int
    holdings_input_digest: str
    holdings_result_digest: str
    activity_input_digest: str | None
    activity_result_digest: str | None
    activity_requested: bool
    state: Literal["succeeded", "expired"]
    created_at: datetime
    expires_at: datetime


class AggregateService(Protocol):
    async def list_selections(
        self, principal: Principal, query: AggregatePageQuery
    ) -> Page[AggregateSelectionView]: ...
    async def create_selection(
        self, principal: Principal, command: CreateAggregateSelection
    ) -> AggregateSelectionView: ...
    async def get_selection(
        self, principal: Principal, selection_id: UUID
    ) -> AggregateSelectionView: ...
    async def list_runs(
        self, principal: Principal, selection_id: UUID, query: AggregatePageQuery
    ) -> Page[AggregateRunReceipt]: ...
    async def create_run(
        self, principal: Principal, command: CreateAggregateRun
    ) -> AggregateRunReceipt: ...
    async def get_run(
        self, principal: Principal, run_id: UUID, query: AggregateRunQuery
    ) -> AggregateRunPage: ...
