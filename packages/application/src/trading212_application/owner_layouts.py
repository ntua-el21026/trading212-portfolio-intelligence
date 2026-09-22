"""The five owner-preference ports; access is resolved by the current durable service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from trading212_domain.owner_layouts import (
    OwnerLayoutContent,
    layout_bound,
    layout_text,
    layout_uuid,
)
from trading212_security.principals import Principal, Scope

from .targets import validate_target_idempotency_key

LAYOUT_READ_SCOPES = frozenset({Scope.PREFERENCES_READ})
LAYOUT_WRITE_SCOPES = LAYOUT_READ_SCOPES | {Scope.PREFERENCES_WRITE}


class OwnerLayoutErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    CURSOR_INVALID = "CURSOR_INVALID"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass(slots=True)
class OwnerLayoutServiceError(Exception):
    code: OwnerLayoutErrorCode
    message: str = "The saved layout operation cannot be completed."

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutPageQuery:
    limit: int = 25
    cursor: str | None = None
    include_archived: bool = False

    def __post_init__(self) -> None:
        layout_bound(type(self.limit) is int and 1 <= self.limit <= 100, "limit")
        layout_bound(type(self.include_archived) is bool, "include_archived")
        if self.cursor is not None:
            layout_text(self.cursor, "cursor", 2048)


@dataclass(frozen=True, slots=True, kw_only=True)
class LayoutCommand:
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        validate_target_idempotency_key(self.idempotency_key)
        layout_text(self.correlation_id, "correlation_id", 120)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateOwnerLayout(LayoutCommand):
    content: OwnerLayoutContent

    def __post_init__(self) -> None:
        LayoutCommand.__post_init__(self)
        layout_bound(type(self.content) is OwnerLayoutContent, "content")


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateOwnerLayout(CreateOwnerLayout):
    layout_id: UUID
    expected_revision: int

    def __post_init__(self) -> None:
        CreateOwnerLayout.__post_init__(self)
        layout_uuid(self.layout_id, "layout_id")
        layout_bound(
            type(self.expected_revision) is int and 1 <= self.expected_revision <= 129,
            "expected_revision",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveOwnerLayout(LayoutCommand):
    layout_id: UUID
    expected_revision: int

    def __post_init__(self) -> None:
        LayoutCommand.__post_init__(self)
        layout_uuid(self.layout_id, "layout_id")
        layout_bound(
            type(self.expected_revision) is int and 1 <= self.expected_revision <= 129,
            "expected_revision",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutVersionHeader:
    id: UUID
    number: int
    created_at: datetime
    content_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutSummary:
    id: UUID
    name: str
    revision: int
    state: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime
    availability: Literal["available", "restricted"]
    reason: Literal["account_unavailable", "selection_unavailable"] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutView:
    id: UUID
    revision: int
    state: Literal["active", "archived"]
    version: OwnerLayoutVersionHeader
    content: OwnerLayoutContent
    versions: tuple[OwnerLayoutVersionHeader, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutArchiveReceipt:
    id: UUID
    revision: int
    state: Literal["archived"]
    archived_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLayoutPage:
    items: tuple[OwnerLayoutSummary, ...]
    total: int
    limit: int
    next_cursor: str | None
    read_cutoff_at: datetime


class OwnerLayoutService(Protocol):
    async def list_owner_layouts(
        self, principal: Principal, query: OwnerLayoutPageQuery
    ) -> OwnerLayoutPage: ...
    async def get_owner_layout(
        self, principal: Principal, layout_id: UUID, *, version_id: UUID | None = None
    ) -> OwnerLayoutView: ...
    async def create_owner_layout(
        self, principal: Principal, command: CreateOwnerLayout
    ) -> OwnerLayoutView: ...
    async def update_owner_layout(
        self, principal: Principal, command: UpdateOwnerLayout
    ) -> OwnerLayoutView: ...
    async def archive_owner_layout(
        self, principal: Principal, command: ArchiveOwnerLayout
    ) -> OwnerLayoutArchiveReceipt: ...
