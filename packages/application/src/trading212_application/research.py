"""Eight frozen research operations; current authorization belongs to the service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Protocol
from uuid import UUID

from trading212_domain.errors import fail_validation
from trading212_domain.research import (
    MAX_RESEARCH_CITATIONS,
    MAX_RESEARCH_COMMAND_BYTES,
    MAX_RESEARCH_PAGE,
    MAX_RESEARCH_RESPONSE_BYTES,
    RESEARCH_METHOD,
    RESEARCH_VERSION,
    ResearchEventKind,
    ResearchRecord,
    ResearchReviewState,
    research_bound,
    research_unique,
)
from trading212_domain.research_facts import (
    ResearchPortfolioFacts,
    ResearchPortfolioWarning,
    ResearchSynthesisUnavailable,
    ResearchXrayPin,
)
from trading212_domain.research_notes import (
    ResearchNoteContent,
    ResearchNoteRevision,
    ResearchReviewAcknowledgment,
)
from trading212_domain.research_ranking import (
    research_rank_key,
    research_revision_is_visible,
    research_revision_reviewed,
)
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import ResearchEventRevision
from trading212_domain.serialization import canonical_json
from trading212_security.principals import Principal, Scope

from .targets import TargetServiceError, validate_target_idempotency_key
from .views import Page

RESEARCH_READ_SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.RESEARCH_READ})
RESEARCH_WRITE_SCOPES = RESEARCH_READ_SCOPES | {Scope.RESEARCH_WRITE}


class ResearchErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_BOUND_EXCEEDED = "INPUT_BOUND_EXCEEDED"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CURSOR_INVALID = "CURSOR_INVALID"


@dataclass(slots=True)
class ResearchServiceError(Exception):
    code: ResearchErrorCode
    message: str = "The research operation cannot be completed."

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchPageQuery(ResearchRecord):
    limit: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        research_bound(1 <= self.limit <= MAX_RESEARCH_PAGE, "limit")
        if self.cursor is not None:
            research_bound(1 <= len(self.cursor) <= 2048, "cursor")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSummaryQuery(ResearchPageQuery):
    account_id: UUID
    xray_run_id: UUID
    source_cutoff_at: datetime
    entity_id: UUID | None = None
    event_kind: ResearchEventKind | None = None
    review_state: ResearchReviewState = ResearchReviewState.ALL


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCommand(ResearchRecord):
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        try:
            validate_target_idempotency_key(self.idempotency_key)
        except TargetServiceError:
            fail_validation("Research idempotency identity is invalid.", field="idempotency_key")
        research_bound(1 <= len(self.correlation_id) <= 120, "correlation_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateResearchNote(ResearchCommand):
    account_id: UUID
    entity_id: UUID
    content: ResearchNoteContent


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateResearchNoteVersion(ResearchCommand):
    note_id: UUID
    expected_revision: int
    content: ResearchNoteContent

    def __post_init__(self) -> None:
        ResearchCommand.__post_init__(self)
        research_bound(1 <= self.expected_revision <= 512, "expected_revision")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewResearchEvent(ResearchCommand):
    event_id: UUID
    revision_id: UUID
    revision_digest: str


def research_command_digest(
    command: CreateResearchNote | CreateResearchNoteVersion | ReviewResearchEvent, account_id: UUID
) -> str:
    """Called only after owned reference resolution; audit metadata never changes semantics."""
    if type(account_id) is not UUID:
        fail_validation("A canonical research account is required.")
    identity: str
    data: object
    if type(command) is CreateResearchNote:
        if command.account_id != account_id:
            fail_validation("Research command account differs.")
        identity, data = "research.note.create.v1", (account_id, command.entity_id, command.content)
    elif type(command) is CreateResearchNoteVersion:
        identity, data = (
            "research.note.version.create.v1",
            (account_id, command.note_id, command.expected_revision, command.content),
        )
    elif type(command) is ReviewResearchEvent:
        identity, data = (
            "research.event.review.v1",
            (account_id, command.event_id, command.revision_id, command.revision_digest),
        )
    else:
        fail_validation("Unknown closed research command.")
    payload = canonical_json(data).encode()
    research_bound(len(payload) <= MAX_RESEARCH_COMMAND_BYTES, "command.bytes")
    return sha256(b"t212pi.command." + identity.encode("ascii") + b"\0" + payload).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWarningPreview(ResearchPortfolioWarning):
    source_references_omitted: int = 0
    paths_omitted: int = 0

    def __post_init__(self) -> None:
        ResearchPortfolioWarning.__post_init__(self)
        for values in (self.source_reference_ids, self.path_keys):
            research_bound(len(values) <= MAX_RESEARCH_CITATIONS, "warning_preview")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchPortfolioPreview(ResearchPortfolioFacts):
    warnings: tuple[ResearchWarningPreview, ...]
    warnings_omitted: int = 0
    canonical_facts_digest: str
    source_references_omitted: int = 0
    metric_sources_omitted: int = 0
    paths_omitted: int = 0
    view_schema: Literal["research_portfolio_preview_v1"] = "research_portfolio_preview_v1"

    def __post_init__(self) -> None:
        ResearchPortfolioFacts.__post_init__(self)
        for values in (
            self.source_reference_ids,
            self.metric_source_reference_ids,
            self.path_keys,
            self.warnings,
        ):
            research_bound(len(values) <= MAX_RESEARCH_CITATIONS, "source_preview")


def preview_research_portfolio(value: ResearchPortfolioFacts) -> ResearchPortfolioPreview:
    """Preserve every financial scalar while disclosing complete proof counts and identity."""
    if type(value) is not ResearchPortfolioFacts:
        fail_validation("Canonical research facts are required for projection.")
    limit = MAX_RESEARCH_CITATIONS
    warnings = tuple(
        ResearchWarningPreview(
            code=item.code,
            reason=item.reason,
            source_reference_ids=item.source_reference_ids[:limit],
            path_keys=item.path_keys[:limit],
            source_references_omitted=max(0, len(item.source_reference_ids) - limit),
            paths_omitted=max(0, len(item.path_keys) - limit),
        )
        for item in value.warnings[:limit]
    )
    return ResearchPortfolioPreview(
        pin=value.pin,
        entity_id=value.entity_id,
        effective_exposure=value.effective_exposure,
        availability=value.availability,
        reason=value.reason,
        upstream_reason=value.upstream_reason,
        quality=value.quality,
        origin=value.origin,
        bound=value.bound,
        confidence=value.confidence,
        source_reference_ids=value.source_reference_ids[:limit],
        metric_source_reference_ids=value.metric_source_reference_ids[:limit],
        path_keys=value.path_keys[:limit],
        company_coverage_complete=value.company_coverage_complete,
        positive_unresolved_below_quantum=value.positive_unresolved_below_quantum,
        warnings=warnings,
        warnings_omitted=max(0, len(value.warnings) - limit),
        canonical_facts_digest=research_record_digest(value),
        source_references_omitted=max(0, len(value.source_reference_ids) - limit),
        metric_sources_omitted=max(0, len(value.metric_source_reference_ids) - limit),
        paths_omitted=max(0, len(value.path_keys) - limit),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchItemView(ResearchRecord):
    item_id: UUID
    source_cutoff_at: datetime
    source: ResearchEventRevision
    portfolio: ResearchPortfolioPreview
    owner_revisions: tuple[ResearchNoteRevision, ...] = ()
    owner_revisions_omitted: int = 0
    review: ResearchReviewAcknowledgment | None = None
    synthesis: ResearchSynthesisUnavailable = field(default_factory=ResearchSynthesisUnavailable)

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        if (self.source.owner_id, self.source.entity_id) != (
            self.portfolio.pin.owner_id,
            self.portfolio.entity_id,
        ):
            fail_validation("Research event and portfolio scope differ.")
        if not research_revision_is_visible(self.source, self.source_cutoff_at):
            fail_validation("Research item source is not visible at its selected cutoff.")
        research_revision_reviewed(
            self.source, account_id=self.portfolio.pin.account_id, review=self.review
        )
        research_bound(len(self.owner_revisions) <= MAX_RESEARCH_CITATIONS, "owner_revisions")
        research_unique(tuple(item.note_id for item in self.owner_revisions), "owner_revisions")
        if any(
            (item.owner_id, item.account_id, item.entity_id)
            != (self.source.owner_id, self.portfolio.pin.account_id, self.source.entity_id)
            for item in self.owner_revisions
        ):
            fail_validation("Research owner revision scope differs.")
        research_bound(
            len(canonical_json(self).encode()) <= MAX_RESEARCH_RESPONSE_BYTES, "response.bytes"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSummary(ResearchRecord):
    pin: ResearchXrayPin
    source_cutoff_at: datetime
    items: tuple[ResearchItemView, ...]
    next_cursor: str | None
    limit: int
    total: int
    unknown_exposure_total: int
    method: str = RESEARCH_METHOD
    method_version: str = RESEARCH_VERSION
    schema_version: str = RESEARCH_VERSION

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        ResearchPageQuery(limit=self.limit, cursor=self.next_cursor)
        research_bound(len(self.items) <= self.limit, "items")
        if (
            self.total < len(self.items)
            or self.unknown_exposure_total > self.total
            or (self.method, self.method_version, self.schema_version)
            != (RESEARCH_METHOD, RESEARCH_VERSION, RESEARCH_VERSION)
        ):
            fail_validation("Research summary metadata differs.")
        unknown = sum(item.portfolio.effective_exposure is None for item in self.items)
        if (
            self.unknown_exposure_total < unknown
            or self.total - self.unknown_exposure_total < len(self.items) - unknown
        ):
            fail_validation("Research summary exposure counts differ.")
        if any(
            item.portfolio.pin != self.pin
            or item.source_cutoff_at != self.source_cutoff_at
            or not research_revision_is_visible(item.source, self.source_cutoff_at)
            for item in self.items
        ):
            fail_validation("Research summary basis or cutoff differs.")
        research_unique(tuple(item.source.event_id for item in self.items), "events")
        research_unique(tuple(item.item_id for item in self.items), "items")
        ranked = tuple(
            research_rank_key(
                item.source,
                item.portfolio.effective_exposure,
                reviewed=research_revision_reviewed(
                    item.source, account_id=self.pin.account_id, review=item.review
                ),
            )
            for item in self.items
        )
        if tuple(sorted(ranked)) != ranked:
            fail_validation("Research summary ranking differs.")
        item_bytes = 0
        for item in self.items:
            item_bytes += len(canonical_json(item).encode())
            research_bound(item_bytes <= MAX_RESEARCH_RESPONSE_BYTES, "response.bytes")
        research_bound(
            len(canonical_json(self).encode()) <= MAX_RESEARCH_RESPONSE_BYTES, "response.bytes"
        )


class ResearchService(Protocol):
    async def get_research_summary(
        self, principal: Principal, query: ResearchSummaryQuery
    ) -> ResearchSummary: ...
    async def get_research_item(
        self, principal: Principal, item_id: UUID, *, expected_account_id: UUID | None = None
    ) -> ResearchItemView: ...
    async def list_research_notes(
        self, principal: Principal, account_id: UUID, query: ResearchPageQuery
    ) -> Page[ResearchNoteRevision]: ...
    async def create_research_note(
        self, principal: Principal, command: CreateResearchNote
    ) -> ResearchNoteRevision: ...
    async def get_research_note(
        self, principal: Principal, note_id: UUID
    ) -> ResearchNoteRevision: ...
    async def list_research_note_versions(
        self, principal: Principal, note_id: UUID, query: ResearchPageQuery
    ) -> Page[ResearchNoteRevision]: ...
    async def create_research_note_version(
        self, principal: Principal, command: CreateResearchNoteVersion
    ) -> ResearchNoteRevision: ...
    async def review_research_event(
        self, principal: Principal, command: ReviewResearchEvent
    ) -> ResearchReviewAcknowledgment: ...
