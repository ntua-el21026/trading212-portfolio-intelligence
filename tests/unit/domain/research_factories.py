"""Small synthetic owned research records, with real closed license/citation contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.research import ResearchEventKind, ResearchExposureReason
from trading212_domain.research_facts import ResearchPortfolioFacts, ResearchXrayPin
from trading212_domain.research_notes import (
    ResearchNoteContent,
    ResearchNoteRevision,
    ResearchReviewAcknowledgment,
)
from trading212_domain.research_ranking import ResearchRankedItem
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchCitationPin,
    ResearchCompanyOverviewFacts,
    ResearchEventRevision,
    ResearchNewsFacts,
    ResearchSourceVersion,
)
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import XrayAvailability, XrayBound

AT = datetime(2026, 9, 15, 12, tzinfo=UTC)
EUR = CurrencyCode("EUR")


def uid(number: int) -> UUID:
    return UUID(int=number)


def source(
    index: int = 1, *, entity_id: UUID | None = None, facts_digest: str = "f" * 64
) -> ResearchSourceVersion:
    license = SourceLicense(
        id=str(uid(901)),
        provider_id=str(uid(900)),
        version="1",
        effective_at=AT - timedelta(days=1),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=30,
        attribution="Synthetic evidence",
        evidence_key="research-license-1",
    )
    return ResearchSourceVersion(
        source_id=uid(902),
        version_id=uid(10000 + index),
        owner_id=uid(1),
        provider_id=uid(900),
        entity_id=uid(3) if entity_id is None else entity_id,
        facts_digest=facts_digest,
        license_version_id=uid(901),
        license=license,
        capability=ResearchEventKind.NEWS,
        adapter_version="news-1",
        request_digest="a" * 64,
        observed_at=AT - timedelta(hours=1),
        first_known_at=AT - timedelta(hours=1),
        source_cutoff_at=AT - timedelta(minutes=30),
        retained_at=AT,
        expires_at=AT + timedelta(days=30),
        synthetic=True,
    )


def event(
    index: int = 1,
    *,
    entity_id: UUID | None = None,
    summary: str = "The issuer published a dated update.",
    overview: bool = False,
) -> ResearchEventRevision:
    entity = uid(3) if entity_id is None else entity_id
    facts = (
        ResearchCompanyOverviewFacts(
            publisher="Synthetic publisher", company_name="Synthetic issuer", description=summary
        )
        if overview
        else ResearchNewsFacts(
            publisher="Synthetic publisher",
            title="Dated issuer update",
            summary=summary,
            published_at=AT - timedelta(hours=2),
        )
    )
    citation = ResearchCitation(
        citation_id=uid(20000 + index),
        source=replace(
            source(index, entity_id=entity, facts_digest=research_record_digest(facts)),
            capability=ResearchEventKind.COMPANY_OVERVIEW if overview else ResearchEventKind.NEWS,
        ),
        provider_event_key=f"event-{index}",
        entity_id=entity,
        facts_digest=research_record_digest(facts),
        published_at=facts.published_at,
    )
    return ResearchEventRevision(
        event_id=uid(30000 + index),
        revision_id=uid(40000 + index),
        revision=1,
        previous_revision_id=None,
        owner_id=uid(1),
        entity_id=entity,
        provider_id=uid(900),
        provider_event_key=f"event-{index}",
        facts=facts,
        citations=(citation,),
        created_at=AT,
    )


def pin() -> ResearchXrayPin:
    return ResearchXrayPin(
        owner_id=uid(1),
        account_id=uid(2),
        run_id=uid(10),
        snapshot_id=uid(11),
        input_digest="b" * 64,
        result_digest="c" * 64,
        reporting_currency=EUR,
        valuation_at=AT - timedelta(days=1),
        source_cutoff_at=AT - timedelta(hours=3),
        quality_evaluated_at=AT,
        policy_id=uid(12),
        policy_version="fixture-1",
    )


def portfolio(
    value: ResearchEventRevision, amount: str | None = "100", *, bound: XrayBound = XrayBound.EXACT
) -> ResearchPortfolioFacts:
    return ResearchPortfolioFacts(
        pin=pin(),
        entity_id=value.entity_id,
        effective_exposure=None if amount is None else Money(Decimal(amount), EUR),
        availability=XrayAvailability.UNAVAILABLE if amount is None else XrayAvailability.AVAILABLE,
        reason=ResearchExposureReason.CAPTURED_VALUE_UNAVAILABLE if amount is None else None,
        upstream_reason=None,
        quality=QualityState.PARTIAL if amount is None else QualityState.FRESH,
        origin=ValueOrigin.UNAVAILABLE if amount is None else ValueOrigin.DERIVED_DETERMINISTIC,
        bound=bound,
        confidence=None,
        source_reference_ids=(uid(22),),
        metric_source_reference_ids=(uid(22),),
        path_keys=("position:synthetic-path",),
        company_coverage_complete=True,
        positive_unresolved_below_quantum=False,
        warnings=(),
    )


def acknowledgment(value: ResearchEventRevision) -> ResearchReviewAcknowledgment:
    return ResearchReviewAcknowledgment(
        acknowledgment_id=uid(50),
        owner_id=value.owner_id,
        account_id=uid(2),
        event_id=value.event_id,
        revision_id=value.revision_id,
        revision_digest=value.content_digest,
        actor_id=uid(51),
        reviewed_at=value.created_at,
    )


def ranked(
    index: int = 1, *, amount: str | None = "100", reviewed: bool = False, overview: bool = False
) -> ResearchRankedItem:
    value = event(index, entity_id=uid(3 + index), overview=overview)
    return ResearchRankedItem(
        event=value,
        portfolio=portfolio(value, amount),
        review=acknowledgment(value) if reviewed else None,
    )


def corrected(value: ResearchEventRevision) -> ResearchEventRevision:
    assert isinstance(value.facts, ResearchNewsFacts)
    facts = replace(value.facts, summary="A corrected source fact.")
    citations = tuple(
        replace(
            item,
            facts_digest=research_record_digest(facts),
            source=replace(
                item.source, version_id=uid(60001), facts_digest=research_record_digest(facts)
            ),
        )
        for item in value.citations
    )
    return replace(
        value,
        revision_id=uid(60000),
        revision=2,
        previous_revision_id=value.revision_id,
        facts=facts,
        citations=citations,
    )


def note(value: ResearchEventRevision) -> ResearchNoteRevision:
    return ResearchNoteRevision(
        note_id=uid(70),
        revision_id=uid(71),
        revision=1,
        previous_revision_id=None,
        owner_id=value.owner_id,
        account_id=uid(2),
        entity_id=value.entity_id,
        actor_id=uid(51),
        created_at=AT,
        content=ResearchNoteContent(
            title="Owner thesis",
            thesis="Owner-written assumptions remain separate.",
            risks="A source can be wrong.",
            catalysts="Review the next filing.",
            break_conditions="The cited premise no longer holds.",
            citations=(ResearchCitationPin.from_citation(value.citations[0]),),
        ),
    )
