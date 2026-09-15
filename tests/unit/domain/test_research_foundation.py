"""Research precision, immutable revisions, material identity and complete retained proof."""

from dataclasses import replace
from datetime import timedelta
from decimal import localcontext
from typing import Any, cast
from uuid import UUID

import pytest
from trading212_analytics.xray import calculate_xray
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.research import ResearchEventKind, ResearchExposureReason
from trading212_domain.research_facts import ResearchXrayPin, copy_research_portfolio_facts
from trading212_domain.research_ranking import (
    ResearchRankedItem,
    deduplicate_research_event,
    latest_research_revisions,
    rank_research_items,
    research_material_digest,
    validate_research_successor,
)
from trading212_domain.research_serialization import (
    research_event_from_json,
    research_note_from_json,
    research_portfolio_facts_from_json,
    research_record_bytes,
    research_source_version_from_json,
)
from trading212_domain.research_sources import ResearchCitationPin
from trading212_domain.sources import LicensePermission
from trading212_domain.xray import XrayAvailability, XrayBound, XrayDimension

from tests.unit.analytics.xray_factories import fixture
from tests.unit.domain.research_factories import (
    AT,
    acknowledgment,
    corrected,
    event,
    note,
    portfolio,
    ranked,
    source,
    uid,
)

pytestmark = pytest.mark.unit


def test_roundtrip_complete_facts_citations_notes_and_exposure() -> None:
    current = event()
    records = (
        (current, research_event_from_json),
        (current.citations[0].source, research_source_version_from_json),
        (note(current), research_note_from_json),
        (portfolio(current), research_portfolio_facts_from_json),
    )
    for value, decode in records:
        payload = research_record_bytes(value)
        assert decode(payload) == value
        assert research_record_bytes(decode(payload)) == payload
    citation = current.citations[0]
    assert note(current).content.citations == (ResearchCitationPin.from_citation(citation),)
    assert current.expires_at == citation.source.expires_at


def test_source_byte_limit_and_foreign_or_future_citation_fail_closed() -> None:
    value = event()
    with pytest.raises(DomainError):
        event(summary="\U00020000" * 4096)
    with pytest.raises(DomainError):
        replace(value.citations[0], entity_id=uid(999))
    with pytest.raises(DomainError):
        replace(value.citations[0], facts_digest="f" * 64)
    for changed in (
        replace(value.citations[0], source=replace(value.citations[0].source, owner_id=uid(999))),
        replace(
            value.citations[0],
            source=replace(
                value.citations[0].source, capability=ResearchEventKind.COMPANY_OVERVIEW
            ),
        ),
    ):
        with pytest.raises(DomainError):
            replace(value, citations=(changed,))
    with pytest.raises(DomainError):
        replace(value.citations[0], published_at=AT)
    with pytest.raises(DomainError):
        replace(source(), expires_at=AT + timedelta(days=31))
    with pytest.raises(DomainError):
        replace(source(), license=replace(source().license, display=LicensePermission.DENIED))
    with pytest.raises(DomainError):
        replace(value, citations=())
    with pytest.raises(DomainError):
        replace(value, created_at=value.expires_at)


def test_canonical_codec_rejects_duplicate_unknown_float_and_noncanonical_bytes() -> None:
    value = event()
    payload = research_record_bytes(value)
    assert research_event_from_json(payload, expected_digest=value.content_digest) == value
    with pytest.raises(DomainError):
        research_event_from_json(payload, expected_digest="f" * 64)
    for invalid in (
        payload + b" ",
        b'{"event_id":1,"event_id":1}',
        payload.replace(b'"revision":1', b'"revision":1.0'),
        payload[:-1] + b',"destination":"private-canary"}',
    ):
        with pytest.raises(DomainError) as rejected:
            research_event_from_json(invalid)
        assert "private-canary" not in str(rejected.value)
    encoded = research_record_bytes(portfolio(value, "12.5"))
    with pytest.raises(DomainError):
        research_portfolio_facts_from_json(encoded.replace(b'"amount":"12.5"', b'"amount":12.5'))
    with pytest.raises(DomainError):
        research_portfolio_facts_from_json(
            encoded.replace(b'"amount":"12.5"', b'"amount":"1.25e1"')
        )
    with pytest.raises(DomainError):
        replace(portfolio(value), confidence=cast(Any, 0.5))


def test_material_dedup_keeps_retrieval_alias_and_license_witnesses() -> None:
    old = event()
    citation = old.citations[0]
    later_source = replace(
        citation.source,
        version_id=uid(12345),
        observed_at=citation.source.observed_at + timedelta(hours=1),
        first_known_at=citation.source.first_known_at + timedelta(hours=1),
        source_cutoff_at=AT,
        retained_at=AT + timedelta(hours=1),
        expires_at=AT + timedelta(days=30, hours=1),
    )
    retrieval = replace(
        old,
        revision_id=uid(45678),
        citations=(replace(citation, citation_id=uid(23456), source=later_source),),
        created_at=AT + timedelta(hours=1),
    )
    assert old.content_digest != retrieval.content_digest
    assert research_material_digest(old) == research_material_digest(retrieval)
    decision = deduplicate_research_event(retrieval, (old,))
    assert (
        decision.action == "retrieval_only" and decision.incoming.citations == retrieval.citations
    )
    assert deduplicate_research_event(old, (old,)).action == "exact_replay"
    changed = corrected(old)
    assert deduplicate_research_event(changed, (old,)).action == "material_revision"
    validate_research_successor(old, changed)
    with pytest.raises(DomainError):
        validate_research_successor(
            old, replace(retrieval, revision=2, previous_revision_id=old.revision_id)
        )
    alias = event(2)
    decision = deduplicate_research_event(alias, (old,))
    assert decision.action == "semantic_alias"
    assert decision.existing_event_ids == (old.event_id,)
    assert decision.incoming.citations[0].provider_event_key == "event-2"
    revised_license = replace(citation.source.license, id=str(uid(903)), version="2")
    licensed = replace(
        old,
        citations=(
            replace(
                citation,
                source=replace(
                    citation.source, license_version_id=uid(903), license=revised_license
                ),
            ),
        ),
    )
    assert research_material_digest(licensed) != research_material_digest(old)


def test_review_acknowledges_exact_revision_and_cutoff_selects_visible_head() -> None:
    old, later = event(), corrected(event())
    reviewed = acknowledgment(old)
    assert ResearchRankedItem(event=old, portfolio=portfolio(old), review=reviewed).reviewed
    assert not ResearchRankedItem(event=later, portfolio=portfolio(later), review=reviewed).reviewed
    for value in (
        replace(reviewed, account_id=uid(999)),
        replace(reviewed, revision_digest="d" * 64),
    ):
        with pytest.raises(DomainError):
            ResearchRankedItem(event=old, portfolio=portfolio(old), review=value)
    assert latest_research_revisions((later, old), cutoff=AT) == (later,)
    assert latest_research_revisions((old,), cutoff=AT - timedelta(hours=2)) == ()
    assert latest_research_revisions((old,), cutoff=AT) == (old,)


def test_absolute_exposure_precedes_review_time_and_unknown_never_becomes_zero() -> None:
    short, middle, zero, unknown = (
        ranked(1, amount="-100"),
        ranked(2, amount="50"),
        ranked(3, amount="0"),
        ranked(4, amount=None),
    )
    assert rank_research_items((unknown, zero, middle, short)) == (short, middle, zero, unknown)
    lower = replace(
        short,
        portfolio=replace(
            short.portfolio, bound=XrayBound.LOWER_BOUND, quality=QualityState.PARTIAL
        ),
    )
    assert rank_research_items((middle, lower))[0] == lower
    assert lower.portfolio.bound is XrayBound.LOWER_BOUND
    reviewed, unreviewed = ranked(6, reviewed=True), ranked(7)
    assert rank_research_items((reviewed, unreviewed)) == (unreviewed, reviewed)
    overview, dated = ranked(8, overview=True), ranked(9)
    assert rank_research_items((overview, dated)) == (dated, overview)


def test_ranking_keeps_q18_tail_and_negative_magnitude_under_hostile_context() -> None:
    first = ranked(1, amount="99999999999999999999.123456789012345678")
    second = ranked(2, amount="-99999999999999999999.123456789012345679")
    with localcontext() as context:
        context.prec = 3
        assert rank_research_items((first, second)) == (second, first)
    same_amount_first, same_amount_second = ranked(10), ranked(11)
    assert rank_research_items((same_amount_second, same_amount_first)) == (
        same_amount_first,
        same_amount_second,
    )
    with pytest.raises(DomainError):
        rank_research_items(
            (
                first,
                replace(
                    second,
                    portfolio=replace(
                        second.portfolio, pin=replace(second.portfolio.pin, run_id=uid(999))
                    ),
                ),
            )
        )


def test_real_canonical_xray_bucket_is_copied_with_complete_quality_and_paths() -> None:
    calculation = calculate_xray(fixture())
    bucket = next(
        item for item in calculation.exposure_buckets if item.dimension is XrayDimension.COMPANY
    )
    selected = ResearchXrayPin(
        owner_id=calculation.owner_id,
        account_id=calculation.account_id,
        run_id=uid(123),
        snapshot_id=calculation.snapshot_id,
        input_digest=calculation.input_digest,
        result_digest=calculation.content_digest,
        reporting_currency=calculation.reporting_currency,
        valuation_at=calculation.valuation_at.value,
        source_cutoff_at=calculation.source_cutoff_at.value,
        quality_evaluated_at=calculation.quality_evaluated_at.value,
        policy_id=calculation.policy.id,
        policy_version=calculation.policy.version,
    )
    dimension = next(
        item for item in calculation.dimensions if item.dimension is XrayDimension.COMPANY
    )
    copied = copy_research_portfolio_facts(selected, calculation, UUID(bucket.bucket_key))
    assert copied.company_coverage_complete == dimension.complete
    assert copied.positive_unresolved_below_quantum == dimension.positive_unresolved_below_quantum
    assert tuple(
        (item.code, item.reason, item.source_reference_ids, item.path_keys)
        for item in copied.warnings
    ) == tuple(
        (item.code, item.reason, item.source_reference_ids, item.path_keys)
        for item in calculation.warnings
    )
    assert copied.effective_exposure is bucket.effective.value
    assert copied.metric_source_reference_ids == bucket.effective.source_reference_ids
    assert (
        copied.quality,
        copied.bound,
        copied.upstream_reason,
        copied.confidence,
        copied.path_keys,
        copied.source_reference_ids,
    ) == (
        bucket.effective.quality,
        bucket.effective.bound,
        bucket.effective.reason,
        bucket.effective.confidence,
        bucket.path_keys,
        bucket.source_reference_ids,
    )
    missing = copy_research_portfolio_facts(selected, calculation, uid(999))
    assert (
        missing.effective_exposure is None and missing.availability is XrayAvailability.UNAVAILABLE
    )
    assert missing.reason is ResearchExposureReason.ENTITY_ABSENT_FROM_CAPTURE
    with pytest.raises(DomainError):
        copy_research_portfolio_facts(
            replace(selected, result_digest="a" * 64), calculation, UUID(bucket.bucket_key)
        )
