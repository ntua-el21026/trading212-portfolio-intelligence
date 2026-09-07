"""Typed owner-scoped virtual-target commands and application service boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_domain.targets import (
    TARGET_VALIDATION_METHOD,
    TARGET_VALIDATION_VERSION,
    FlattenedTargetNode,
    TargetComparison,
    TargetContent,
    TargetNode,
    TargetNormalizationAdjustment,
    TargetValidationIssue,
    target_content_digest,
)
from trading212_domain.values import CurrencyCode, require_bounded_text, require_utc
from trading212_security.principals import Principal

from .views import Page


class TargetServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    IMMUTABLE_VERSION = "IMMUTABLE_VERSION"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    TARGET_VALIDATION_FAILED = "TARGET_VALIDATION_FAILED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    TARGETS_UNAVAILABLE = "TARGETS_UNAVAILABLE"


@dataclass(slots=True)
class TargetServiceError(Exception):
    code: TargetServiceErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


class VirtualPortfolioState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class VirtualPortfolioStateFilter(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    ALL = "all"


class VirtualPortfolioSort(StrEnum):
    NAME_ASC = "name_asc"
    UPDATED_DESC = "updated_desc"


class TargetVersionState(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class TargetVersionStateFilter(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    ALL = "all"


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError(f"{field} must be a UUID string") from None
    if str(parsed) != value:
        raise ValueError(f"{field} must be a canonical UUID string")


def validate_target_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,180}", value) is None:
        raise TargetServiceError(
            TargetServiceErrorCode.VALIDATION_FAILED, "Invalid idempotency key."
        )
    return value


def target_etag(aggregate_id: str, revision: int) -> str:
    _identifier(aggregate_id, "aggregate_id")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    return f'"{aggregate_id}:{revision}"'


def require_target_revision(if_match: str | None, aggregate_id: str, revision: int) -> None:
    """Check after an authorized exact-idempotency replay has been resolved."""
    if if_match is None:
        raise TargetServiceError(TargetServiceErrorCode.REVISION_REQUIRED, "If-Match is required.")
    if if_match != target_etag(aggregate_id, revision):
        raise TargetServiceError(
            TargetServiceErrorCode.REVISION_MISMATCH, "The aggregate revision has changed."
        )


@dataclass(frozen=True, slots=True)
class TargetPageQuery:
    cursor: str | None = None
    limit: int = 25

    def __post_init__(self) -> None:
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 100
        ):
            raise ValueError("limit must be an integer between 1 and 100")
        if self.cursor is not None:
            require_bounded_text(self.cursor, field="cursor", maximum=2048)


@dataclass(frozen=True, slots=True)
class VirtualPortfolioQuery(TargetPageQuery):
    account_id: str | None = None
    state: VirtualPortfolioStateFilter = VirtualPortfolioStateFilter.ACTIVE
    sort: VirtualPortfolioSort = VirtualPortfolioSort.NAME_ASC
    search: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if self.account_id is not None:
            _identifier(self.account_id, "account_id")
        if not isinstance(self.state, VirtualPortfolioStateFilter):
            raise ValueError("invalid virtual portfolio state filter")
        if not isinstance(self.sort, VirtualPortfolioSort):
            raise ValueError("invalid virtual portfolio sort")
        if self.search is not None:
            require_bounded_text(self.search, field="search", maximum=80, allow_empty=True)
            object.__setattr__(self, "search", self.search.strip().casefold() or None)


@dataclass(frozen=True, slots=True)
class TargetVersionQuery(TargetPageQuery):
    state: TargetVersionStateFilter = TargetVersionStateFilter.ALL

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if not isinstance(self.state, TargetVersionStateFilter):
            raise ValueError("invalid target version state filter")


@dataclass(frozen=True, slots=True)
class CreateVirtualPortfolioCommand:
    name: str
    reporting_currency: CurrencyCode
    account_id: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        require_bounded_text(self.name, field="name", maximum=120)
        if not self.name.strip():
            raise ValueError("name must contain non-whitespace text")
        require_bounded_text(self.description, field="description", maximum=2000, allow_empty=True)
        if not isinstance(self.reporting_currency, CurrencyCode):
            raise ValueError("reporting_currency must be a CurrencyCode")
        if self.account_id is not None:
            _identifier(self.account_id, "account_id")


@dataclass(frozen=True, slots=True)
class UpdateVirtualPortfolioCommand:
    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if self.name is None and self.description is None:
            raise ValueError("metadata update must contain a field")
        if self.name is not None:
            require_bounded_text(self.name, field="name", maximum=120)
            if not self.name.strip():
                raise ValueError("name must contain non-whitespace text")
        if self.description is not None:
            require_bounded_text(
                self.description, field="description", maximum=2000, allow_empty=True
            )


@dataclass(frozen=True, slots=True)
class CreateTargetVersionCommand:
    effective_at: datetime
    source_version_id: str | None = None
    content: TargetContent | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "effective_at", require_utc(self.effective_at, field="effective_at")
        )
        if (self.source_version_id is None) == (self.content is None):
            raise ValueError("exactly one source version or full content is required")
        if self.source_version_id is not None:
            _identifier(self.source_version_id, "source_version_id")
        if self.content is not None and not isinstance(self.content, TargetContent):
            raise ValueError("content must be TargetContent")


@dataclass(frozen=True, slots=True)
class ReplaceTargetDraftCommand:
    effective_at: datetime
    content: TargetContent

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "effective_at", require_utc(self.effective_at, field="effective_at")
        )
        if not isinstance(self.content, TargetContent):
            raise ValueError("content must be TargetContent")


@dataclass(frozen=True, slots=True)
class ValidateTargetCommand:
    normalize: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.normalize, bool):
            raise ValueError("normalize must be a boolean")


@dataclass(frozen=True, slots=True)
class PublishTargetCommand:
    validation_id: str

    def __post_init__(self) -> None:
        _identifier(self.validation_id, "validation_id")


@dataclass(frozen=True, slots=True)
class VirtualPortfolioView:
    id: str
    account_id: str | None
    name: str
    description: str
    reporting_currency: str
    revision: int
    state: VirtualPortfolioState
    created_at: datetime
    updated_at: datetime
    active_version_id: str | None = None

    @property
    def etag(self) -> str:
        return target_etag(self.id, self.revision)


@dataclass(frozen=True, slots=True)
class TargetValidationView:
    id: str
    version_id: str
    input_revision: int
    result_revision: int
    input_digest: str
    result_digest: str
    valid: bool
    normalize_requested: bool
    normalization_applied: bool
    issues: tuple[TargetValidationIssue, ...]
    adjustments: tuple[TargetNormalizationAdjustment, ...]
    evaluated_at: datetime
    method: str = TARGET_VALIDATION_METHOD
    method_version: str = TARGET_VALIDATION_VERSION

    @property
    def etag(self) -> str:
        return target_etag(self.version_id, self.result_revision)


@dataclass(frozen=True, slots=True)
class TargetVersionView:
    id: str
    portfolio_id: str
    version_number: int
    revision: int
    reporting_currency: str
    effective_at: datetime
    state: TargetVersionState
    content: TargetContent
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    content_digest: str | None = None
    source_version_id: str | None = None
    latest_validation: TargetValidationView | None = None
    flattened_nodes: tuple[FlattenedTargetNode, ...] = ()
    effective_weight_rounding_residual: Decimal | None = None

    @property
    def etag(self) -> str:
        return target_etag(self.id, self.revision)

    @property
    def has_current_validation(self) -> bool:
        if self.latest_validation is None:
            return False
        if self.published_at is None:
            # A replaced draft needs a fresh validation even when content is restored.
            return (
                self.latest_validation.result_revision == self.revision
                and self.latest_validation.result_digest
                == target_content_digest(
                    self.content,
                    reporting_currency=CurrencyCode(self.reporting_currency),
                    effective_at=self.effective_at,
                )
            )
        return self.latest_validation.result_digest == self.content_digest


@dataclass(frozen=True, slots=True)
class TargetVersionEventView:
    id: str
    version_id: str
    sequence: int
    kind: str
    actor_id: str
    occurred_at: datetime
    effective_at: datetime | None = None
    validation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TargetHierarchyNodeView:
    id: str
    node: TargetNode


@dataclass(frozen=True, slots=True)
class TargetPortfolioReadView:
    """One authorized transaction binds portfolio, selected version, and hierarchy page."""

    portfolio: VirtualPortfolioView
    version: TargetVersionView | None
    nodes: Page[TargetHierarchyNodeView]


@dataclass(frozen=True, slots=True)
class TargetVersionComparisonView:
    portfolio_id: str
    left_version_id: str
    right_version_id: str
    left_effective_at: datetime
    right_effective_at: datetime
    comparison: TargetComparison


class TargetService(Protocol):
    """Each method independently authorizes; commands never contact the broker."""

    async def list_virtual_portfolios(
        self, principal: Principal, *, query: VirtualPortfolioQuery
    ) -> Page[VirtualPortfolioView]: ...

    async def create_virtual_portfolio(
        self,
        principal: Principal,
        command: CreateVirtualPortfolioCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> VirtualPortfolioView: ...

    async def get_virtual_portfolio(
        self, principal: Principal, portfolio_id: str
    ) -> VirtualPortfolioView: ...

    async def get_virtual_portfolio_targets(
        self,
        principal: Principal,
        portfolio_id: str,
        *,
        account_id: str | None,
        target_version_id: str | None,
        parent_node_id: str | None,
        query: TargetPageQuery,
    ) -> TargetPortfolioReadView:
        """Require portfolio/target read scopes and return one consistent selected view."""
        ...

    async def update_virtual_portfolio(
        self,
        principal: Principal,
        portfolio_id: str,
        command: UpdateVirtualPortfolioCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> VirtualPortfolioView: ...

    async def archive_virtual_portfolio(
        self,
        principal: Principal,
        portfolio_id: str,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> VirtualPortfolioView: ...

    async def list_target_versions(
        self, principal: Principal, portfolio_id: str, *, query: TargetVersionQuery
    ) -> Page[TargetVersionView]: ...

    async def create_target_version(
        self,
        principal: Principal,
        portfolio_id: str,
        command: CreateTargetVersionCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> TargetVersionView: ...

    async def get_target_version(
        self, principal: Principal, version_id: str
    ) -> TargetVersionView: ...

    async def replace_target_draft(
        self,
        principal: Principal,
        version_id: str,
        command: ReplaceTargetDraftCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> TargetVersionView: ...

    async def validate_target_version(
        self,
        principal: Principal,
        version_id: str,
        command: ValidateTargetCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> TargetValidationView: ...

    async def publish_target_version(
        self,
        principal: Principal,
        version_id: str,
        command: PublishTargetCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> TargetVersionView: ...

    async def archive_target_version(
        self,
        principal: Principal,
        version_id: str,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> TargetVersionView: ...

    async def list_target_version_events(
        self, principal: Principal, version_id: str, *, query: TargetPageQuery
    ) -> Page[TargetVersionEventView]: ...

    async def compare_target_versions(
        self, principal: Principal, portfolio_id: str, left_version_id: str, right_version_id: str
    ) -> TargetVersionComparisonView: ...

    async def list_target_nodes(
        self,
        principal: Principal,
        version_id: str,
        *,
        parent_node_id: str | None,
        query: TargetPageQuery,
    ) -> Page[TargetHierarchyNodeView]: ...

    async def activate_due_versions(self, *, limit: int = 100) -> int:
        """Internal bounded scheduler operation; persistence supplies scoped fencing."""
        ...
