"""Eight closed research operations; prose is inert and financial scalars stay exact."""

from __future__ import annotations

import unicodedata
from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .historical import HistoricalPageLimit, HistoricalSchema
from .sources import SourceLicense, SourceQuality
from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Digest,
    UUIDString,
    WeightString,
)
from .xray import XrayBound, XrayReason, XrayWarningCode

ResearchEventKind = Literal["news", "company_overview"]
ResearchReviewState = Literal["all", "reviewed", "unreviewed"]
ResearchCount = Annotated[StrictInt, Field(ge=0, le=2_147_483_647)]
ResearchRevision = Annotated[StrictInt, Field(ge=1, le=512)]
ResearchOpaqueKey = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    ),
]


def _text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        and char not in "\n\t\u200c\u200d"
        for char in value
    ):
        raise ValueError("Research text contains unsupported controls.")
    value = unicodedata.normalize("NFC", value)
    if len(value) > 4096:
        raise ValueError("Research text exceeds its bound.")
    return value


ResearchText = Annotated[
    str,
    StringConstraints(
        strict=True, max_length=4096, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]*$"
    ),
    AfterValidator(_text),
]
ResearchPath = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=1024), AfterValidator(_text)
]


class ResearchSchema(HistoricalSchema):
    pass


class ResearchPageQuery(ResearchSchema):
    limit: HistoricalPageLimit = 25
    cursor: Cursor | None = None


class ResearchSummaryQuery(ResearchPageQuery):
    xray_run_id: UUIDString
    source_cutoff_at: AwareInstant
    entity_id: UUIDString | None = None
    event_kind: ResearchEventKind | None = None
    review_state: ResearchReviewState = "all"


class ResearchCitationPin(ResearchSchema):
    citation_id: UUIDString
    source_version_id: UUIDString
    source_version_digest: Digest
    citation_digest: Digest


class ResearchNoteContent(ResearchSchema):
    title: ResearchText
    note: ResearchText = ""
    thesis: ResearchText = ""
    risks: ResearchText = ""
    catalysts: ResearchText = ""
    break_conditions: ResearchText = ""
    citations: Annotated[list[ResearchCitationPin], Field(max_length=64)] = Field(
        default_factory=list
    )
    content_type: Literal["owner_revision"] = "owner_revision"

    @model_validator(mode="after")
    def meaningful(self) -> Self:
        if not self.title.strip() or not any(
            value.strip()
            for value in (self.note, self.thesis, self.risks, self.catalysts, self.break_conditions)
        ):
            raise ValueError("Owner research content is empty.")
        if len({item.citation_id for item in self.citations}) != len(self.citations):
            raise ValueError("Research citation identities are duplicated.")
        self.citations = sorted(self.citations, key=lambda item: item.citation_id)
        if len(self.model_dump_json().encode("utf-8")) > 64 * 1024:
            raise ValueError("Owner research content exceeds its byte bound.")
        return self


class CreateResearchNoteRequest(ResearchSchema):
    entity_id: UUIDString
    content: ResearchNoteContent


class CreateResearchNoteVersionRequest(ResearchSchema):
    content: ResearchNoteContent


class ReviewResearchEventRequest(ResearchSchema):
    revision_id: UUIDString
    revision_digest: Digest


class ResearchNoteRevision(ResearchSchema):
    note_id: UUIDString
    revision_id: UUIDString
    revision: ResearchRevision
    previous_revision_id: UUIDString | None
    owner_id: UUIDString
    account_id: UUIDString
    entity_id: UUIDString
    actor_id: UUIDString
    created_at: AwareInstant
    content: ResearchNoteContent
    content_digest: Digest
    schema_version: Literal["1.0.0"]

    @model_validator(mode="after")
    def ancestry(self) -> Self:
        if (self.revision == 1) != (
            self.previous_revision_id is None
        ) or self.previous_revision_id == self.revision_id:
            raise ValueError("Research note ancestry differs.")
        return self


class ResearchReviewAcknowledgment(ResearchSchema):
    acknowledgment_id: UUIDString
    owner_id: UUIDString
    account_id: UUIDString
    event_id: UUIDString
    revision_id: UUIDString
    revision_digest: Digest
    actor_id: UUIDString
    reviewed_at: AwareInstant


class ResearchSourceVersion(ResearchSchema):
    source_id: UUIDString
    version_id: UUIDString
    owner_id: UUIDString
    provider_id: UUIDString
    entity_id: UUIDString
    facts_digest: Digest
    license_version_id: UUIDString
    license: SourceLicense
    capability: ResearchEventKind
    adapter_version: ResearchOpaqueKey
    request_digest: Digest
    observed_at: AwareInstant
    first_known_at: AwareInstant
    source_cutoff_at: AwareInstant
    retained_at: AwareInstant
    expires_at: AwareInstant
    provider: Literal["alpha_vantage"]
    synthetic: StrictBool
    schema_version: Literal["1.0.0"]
    content_digest: Digest

    @model_validator(mode="after")
    def clocks_and_license(self) -> Self:
        if (self.license.id, self.license.provider_id) != (
            self.license_version_id,
            self.provider_id,
        ):
            raise ValueError("Research source license identity differs.")
        if (self.license.store, self.license.display) != (
            "allowed",
            "allowed",
        ) or self.license.effective_at > self.first_known_at:
            raise ValueError("Retained research permission is unavailable.")
        if (
            not self.observed_at
            <= self.first_known_at
            <= self.source_cutoff_at
            <= self.retained_at
            < self.expires_at
        ):
            raise ValueError("Research original clocks differ.")
        days = self.license.retention_days
        if days is None or self.expires_at > self.retained_at + timedelta(days=min(30, days)):
            raise ValueError("Research original retention exceeds its bound.")
        return self


class ResearchNewsFacts(ResearchSchema):
    publisher: ResearchText
    title: ResearchText
    summary: ResearchText
    published_at: AwareInstant
    kind: Literal["news"]
    content_type: Literal["source_facts"]

    @model_validator(mode="after")
    def named(self) -> Self:
        if not self.publisher.strip() or not self.title.strip():
            raise ValueError("Research source identity is empty.")
        return self


class ResearchCompanyOverviewFacts(ResearchSchema):
    publisher: ResearchText
    company_name: ResearchText
    description: ResearchText
    published_at: None
    publication_reason: Literal["provider_publication_unavailable"]
    kind: Literal["company_overview"]
    content_type: Literal["source_facts"]

    @model_validator(mode="after")
    def named(self) -> Self:
        if not self.publisher.strip() or not self.company_name.strip():
            raise ValueError("Research source identity is empty.")
        return self


ResearchSourceFacts = Annotated[
    ResearchNewsFacts | ResearchCompanyOverviewFacts, Field(discriminator="kind")
]


class ResearchCitation(ResearchSchema):
    citation_id: UUIDString
    source: ResearchSourceVersion
    provider_event_key: ResearchOpaqueKey
    entity_id: UUIDString
    facts_digest: Digest
    published_at: AwareInstant | None
    content_digest: Digest

    @model_validator(mode="after")
    def source_identity(self) -> Self:
        if (self.entity_id, self.facts_digest) != (
            self.source.entity_id,
            self.source.facts_digest,
        ) or (self.published_at is not None and self.published_at > self.source.observed_at):
            raise ValueError("Research citation source identity differs.")
        return self


class ResearchEventRevision(ResearchSchema):
    event_id: UUIDString
    revision_id: UUIDString
    revision: ResearchRevision
    previous_revision_id: UUIDString | None
    owner_id: UUIDString
    entity_id: UUIDString
    provider_id: UUIDString
    provider_event_key: ResearchOpaqueKey
    facts: ResearchSourceFacts
    citations: Annotated[list[ResearchCitation], Field(min_length=1, max_length=64)]
    created_at: AwareInstant
    content_digest: Digest
    expires_at: AwareInstant
    schema_version: Literal["1.0.0"]

    @model_validator(mode="after")
    def pinned_facts(self) -> Self:
        if (self.revision == 1) != (
            self.previous_revision_id is None
        ) or self.previous_revision_id == self.revision_id:
            raise ValueError("Research event ancestry differs.")
        if len({item.citation_id for item in self.citations}) != len(self.citations):
            raise ValueError("Research citations are duplicated.")
        if not any(
            (item.source.provider_id, item.provider_event_key)
            == (self.provider_id, self.provider_event_key)
            for item in self.citations
        ):
            raise ValueError("The primary research citation is absent.")
        for item in self.citations:
            if (
                item.source.owner_id,
                item.entity_id,
                item.published_at,
                item.source.capability,
            ) != (
                self.owner_id,
                self.entity_id,
                self.facts.published_at,
                self.facts.kind,
            ) or not item.source.retained_at <= self.created_at < item.source.expires_at:
                raise ValueError("Research source membership differs.")
        if self.expires_at != min(item.source.expires_at for item in self.citations):
            raise ValueError("Research source expiry differs.")
        return self


class ResearchMoney(ResearchSchema):
    amount: DecimalString
    currency: CurrencyString


class ResearchXrayPin(ResearchSchema):
    owner_id: UUIDString
    account_id: UUIDString
    run_id: UUIDString
    snapshot_id: UUIDString
    input_digest: Digest
    result_digest: Digest
    reporting_currency: CurrencyString
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    quality_evaluated_at: AwareInstant
    policy_id: UUIDString
    policy_version: ResearchText
    method: Literal["xray_v1"]
    method_version: Literal["1.1.0"]
    numerical_profile: Literal["xray_decimal256_exact_q18_v1"]
    schema_version: Literal["1"]


class ResearchWarningPreview(ResearchSchema):
    code: XrayWarningCode
    reason: XrayReason | None
    source_reference_ids: Annotated[list[UUIDString], Field(max_length=64)]
    path_keys: Annotated[list[ResearchPath], Field(max_length=64)]
    source_references_omitted: ResearchCount
    paths_omitted: ResearchCount


class ResearchPortfolioPreview(ResearchSchema):
    pin: ResearchXrayPin
    entity_id: UUIDString
    effective_exposure: ResearchMoney | None
    availability: Literal["available", "unavailable"]
    reason: Literal["captured_value_unavailable", "entity_absent_from_capture"] | None
    upstream_reason: XrayReason | None
    quality: SourceQuality
    origin: Literal[
        "observed_provider",
        "normalized_provider",
        "derived_deterministic",
        "estimated",
        "unavailable",
    ]
    bound: XrayBound
    confidence: WeightString | None
    source_reference_ids: Annotated[list[UUIDString], Field(max_length=64)]
    metric_source_reference_ids: Annotated[list[UUIDString], Field(max_length=64)]
    path_keys: Annotated[list[ResearchPath], Field(max_length=64)]
    company_coverage_complete: StrictBool
    positive_unresolved_below_quantum: StrictBool
    warnings: Annotated[list[ResearchWarningPreview], Field(max_length=64)]
    content_type: Literal["portfolio_facts"]
    schema_version: Literal["1.0.0"]
    warnings_omitted: ResearchCount
    canonical_facts_digest: Digest
    source_references_omitted: ResearchCount
    metric_sources_omitted: ResearchCount
    paths_omitted: ResearchCount
    view_schema: Literal["research_portfolio_preview_v1"]

    @model_validator(mode="after")
    def exact_availability(self) -> Self:
        if (self.availability == "available") != (
            self.effective_exposure is not None and self.reason is None
        ) or (
            self.availability == "unavailable"
            and (self.effective_exposure is not None or self.reason is None)
        ):
            raise ValueError("Research exposure availability differs.")
        if (
            self.effective_exposure is not None
            and self.effective_exposure.currency != self.pin.reporting_currency
        ):
            raise ValueError("Research exposure currency differs.")
        for values in (self.source_reference_ids, self.metric_source_reference_ids, self.path_keys):
            if len(set(values)) != len(values):
                raise ValueError("Research proof preview identities are duplicated.")
        return self


class ResearchSynthesisUnavailable(ResearchSchema):
    reason: Literal["disabled", "not_configured", "source_unavailable"]
    availability: Literal["unavailable"]
    content_type: Literal["optional_synthesis"]


class ResearchItemView(ResearchSchema):
    item_id: UUIDString
    source_cutoff_at: AwareInstant
    source: ResearchEventRevision
    portfolio: ResearchPortfolioPreview
    owner_revisions: Annotated[list[ResearchNoteRevision], Field(max_length=64)]
    owner_revisions_omitted: ResearchCount
    review: ResearchReviewAcknowledgment | None
    synthesis: ResearchSynthesisUnavailable

    @model_validator(mode="after")
    def scopes_and_review(self) -> Self:
        pin = self.portfolio.pin
        if (self.source.owner_id, self.source.entity_id) != (
            pin.owner_id,
            self.portfolio.entity_id,
        ):
            raise ValueError("Research source and portfolio scopes differ.")
        if any(
            item.source.first_known_at > self.source_cutoff_at for item in self.source.citations
        ):
            raise ValueError("Research source is not visible at the selected cutoff.")
        if (
            self.source.facts.published_at is not None
            and self.source.facts.published_at > self.source_cutoff_at
        ):
            raise ValueError("Research publication is after the selected cutoff.")
        if any(
            (item.owner_id, item.account_id, item.entity_id)
            != (pin.owner_id, pin.account_id, self.portfolio.entity_id)
            for item in self.owner_revisions
        ):
            raise ValueError("Research owner note scope differs.")
        if len({item.note_id for item in self.owner_revisions}) != len(self.owner_revisions):
            raise ValueError("Research owner notes are duplicated.")
        if self.review is not None and (
            self.review.owner_id,
            self.review.account_id,
            self.review.event_id,
            self.review.revision_id,
            self.review.revision_digest,
        ) != (
            pin.owner_id,
            pin.account_id,
            self.source.event_id,
            self.source.revision_id,
            self.source.content_digest,
        ):
            raise ValueError("Research acknowledgment does not bind this exact revision.")
        return self


class ResearchSummary(ResearchSchema):
    pin: ResearchXrayPin
    source_cutoff_at: AwareInstant
    items: Annotated[list[ResearchItemView], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: ResearchCount
    unknown_exposure_total: ResearchCount
    method: Literal["research_summary_v1"]
    method_version: Literal["1.0.0"]
    schema_version: Literal["1.0.0"]

    @model_validator(mode="after")
    def page_basis(self) -> Self:
        unknown = sum(item.portfolio.effective_exposure is None for item in self.items)
        if (
            len(self.items) > self.limit
            or self.total < len(self.items)
            or not unknown <= self.unknown_exposure_total <= self.total
            or self.total - self.unknown_exposure_total < len(self.items) - unknown
        ):
            raise ValueError("Research page counts differ.")
        if len({item.item_id for item in self.items}) != len(self.items) or len(
            {item.source.event_id for item in self.items}
        ) != len(self.items):
            raise ValueError("Research page identities are duplicated.")
        if any(
            item.portfolio.pin != self.pin or item.source_cutoff_at != self.source_cutoff_at
            for item in self.items
        ):
            raise ValueError("Research page basis differs.")
        return self


class ResearchNotePage(ResearchSchema):
    items: Annotated[list[ResearchNoteRevision], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0, le=512)]

    @model_validator(mode="after")
    def bounded_page(self) -> Self:
        if len(self.items) > min(self.limit, self.total):
            raise ValueError("Research note page counts differ.")
        return self
