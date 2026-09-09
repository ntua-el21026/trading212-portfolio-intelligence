import json
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest
from trading212_analytics.xray import calculate_xray
from trading212_domain import xray as d
from trading212_domain.errors import DomainError
from trading212_domain.xray_codec import (
    decode_xray_input,
    decode_xray_result,
    encode_xray_input,
    encode_xray_result,
)

from tests.unit.analytics.xray_factories import fixture, uid

pytestmark = pytest.mark.unit


def wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_strict_input_codec_is_canonical_and_closed() -> None:
    payload = encode_xray_input(fixture())
    assert encode_xray_input(decode_xray_input(payload)) == payload
    source = json.loads(payload)
    for mutation in (
        dict(source, unexpected=True),
        dict(source, owner_id=str(uid(255)).upper()),
        dict(source, positions=[True]),
    ):
        if mutation == source:
            continue
        with pytest.raises(DomainError):
            decode_xray_input(wire(mutation))
    with pytest.raises(DomainError):
        decode_xray_input(b'{"owner_id":"x","owner_id":"x"}')
    with pytest.raises(DomainError):
        decode_xray_input(payload.replace(b'"amount":"200"', b'"amount":200', 1))
    with pytest.raises(DomainError):
        decode_xray_input(payload.replace(b'"amount":"200"', b'"amount":0.1', 1))


def test_codec_exact_coefficients_never_accept_exponents_or_leading_zero() -> None:
    result = calculate_xray(fixture())
    source = json.loads(encode_xray_result(result))
    for text in ("1e72", "+1", "01", "-0", "9" * 251):
        changed = json.loads(json.dumps(source))
        changed["terminal_paths"][0]["relative_coefficient"] = text
        with pytest.raises(DomainError):
            decode_xray_result(wire(changed))
    with pytest.raises(DomainError):
        decode_xray_result(wire(dict(source, content_digest=result.content_digest)))


def test_domain_constructor_enforces_types_bounds_and_availability() -> None:
    value = fixture()
    with pytest.raises(DomainError):
        replace(value, positions=cast(Any, list(value.positions)))
    with pytest.raises(DomainError):
        replace(value.positions[0].reporting_value, availability=d.XrayAvailability.UNAVAILABLE)
    with pytest.raises(DomainError):
        replace(value.positions[0].reporting_value, confidence=Decimal("1.000000000000000001"))
    with pytest.raises(DomainError):
        replace(value.policy.traversal_policy, max_visited_paths=cast(Any, 9999))
    with pytest.raises(DomainError):
        replace(value, account_id=uid(99))


def test_internal_references_have_no_fabricated_license_but_enrichment_requires_it() -> None:
    value = fixture()
    internal = next(
        item for item in value.source_dependencies if item.kind is d.XrayDependencyKind.VALUATION
    )
    licensed = next(
        item for item in value.source_dependencies if item.kind is d.XrayDependencyKind.CONSTITUENTS
    )
    assert internal.provider_id is None and internal.license_version_id is None
    with pytest.raises(DomainError):
        replace(licensed, provider_id=None, license_version_id=None)
    with pytest.raises(DomainError):
        replace(internal, provider_id=str(uid(900)))
    with pytest.raises(DomainError):
        replace(
            value,
            source_dependencies=tuple(
                replace(item, subject_id=uid(9999)) if item.id == licensed.id else item
                for item in value.source_dependencies
            ),
        )


def test_nullable_confidence_roundtrip_never_invents_one() -> None:
    value = fixture()
    evidence = value.entity_evidence[0]
    changed = replace(
        value,
        entity_evidence=(
            replace(evidence, evidence=replace(evidence.evidence, confidence=None)),
            *value.entity_evidence[1:],
        ),
    )
    result = calculate_xray(changed)
    company = next(
        item
        for item in result.exposure_buckets
        if item.dimension is d.XrayDimension.COMPANY and item.bucket_key == str(evidence.entity_id)
    )
    assert company.confidence is None and company.effective.confidence is None
    assert decode_xray_result(encode_xray_result(result)) == result


def test_annotated_nullable_metric_union_accepts_zero_and_unknown_confidence() -> None:
    from trading212_domain.enums import QualityState
    from trading212_domain.values import Money

    from tests.unit.analytics.xray_factories import EUR

    ratio = d.XrayRatioMetric(
        value=Decimal("0"),
        reason=None,
        quality=QualityState.FRESH,
        bound=d.XrayBound.EXACT,
        availability=d.XrayAvailability.AVAILABLE,
        confidence=None,
    )
    money = replace(
        fixture().positions[0].reporting_value, value=Money(Decimal("0"), EUR), confidence=None
    )
    assert ratio.value == Decimal("0") and ratio.confidence is None
    assert money.value is not None and money.value.amount == Decimal("0")
    assert money.confidence is None
    result = calculate_xray(fixture())
    changed = replace(
        result, portfolio_summary=replace(result.portfolio_summary, cash_weight=ratio, total=money)
    )
    assert decode_xray_result(encode_xray_result(changed)) == changed


def test_public_policy_and_typed_component_codecs_are_closed_and_lossless() -> None:
    from trading212_domain.xray_codec import (
        decode_xray_component,
        decode_xray_policy,
        encode_xray_component,
        encode_xray_policy,
    )

    value = fixture()
    policy_payload = encode_xray_policy(value.policy)
    assert encode_xray_policy(decode_xray_policy(policy_payload)) == policy_payload
    candidate = value.constituent_candidates[0]
    payload = encode_xray_component(candidate)
    assert (
        encode_xray_component(decode_xray_component(payload, d.XrayConstituentCandidate)) == payload
    )
    holding = candidate.holdings[0]
    assert (
        decode_xray_component(encode_xray_component(holding), d.XrayConstituentHolding) == holding
    )
    with pytest.raises(DomainError):
        decode_xray_component(payload, d.XrayConstituentHolding)
    document = json.loads(payload)
    document["value"]["cash_weight"] = "1e-1"
    with pytest.raises(DomainError):
        decode_xray_component(wire(document), d.XrayConstituentCandidate)
    with pytest.raises(DomainError):
        decode_xray_component(wire(dict(document, unexpected=True)), d.XrayConstituentCandidate)


def test_classification_requested_subjects_are_typed_closed_and_replayable() -> None:
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component

    value = fixture()
    batch = value.classification_batches[0]
    assignment = batch.assignments[0]
    target = d.XrayClassificationSubject(
        assignment.subject_kind,
        assignment.subject_id,
        assignment.dimension,
        assignment.taxonomy_id,
        assignment.taxonomy_version,
    )
    gap = replace(
        batch,
        evidence=replace(batch.evidence, state=d.XraySourceState.GAP),
        assignments=(),
        requested_subjects=(target,),
    )
    assert (
        decode_xray_component(encode_xray_component(target), d.XrayClassificationSubject) == target
    )
    assert decode_xray_component(encode_xray_component(gap), d.XrayClassificationBatch) == gap
    changed = replace(value, classification_batches=(gap, *value.classification_batches[1:]))
    payload = encode_xray_input(changed)
    assert encode_xray_input(decode_xray_input(payload)) == payload
    document = json.loads(encode_xray_component(gap))
    document["value"]["requested_subjects"][0]["bucket_key"] = "fabricated"
    with pytest.raises(DomainError):
        decode_xray_component(wire(document), d.XrayClassificationBatch)
    with pytest.raises(DomainError):
        replace(target, subject_kind=d.XraySubjectKind.SOURCE_RECORD)
    with pytest.raises(DomainError):
        replace(target, dimension=d.XrayDimension.COMPANY)
    with pytest.raises(DomainError):
        replace(gap, requested_subjects=())
    with pytest.raises(DomainError):
        replace(gap, requested_subjects=(target, target))
    with pytest.raises(DomainError):
        replace(gap, assignments=(assignment,))


def test_classification_gap_membership_must_match_subject_bound_source() -> None:
    value = fixture()
    batch = value.classification_batches[0]
    assignment = batch.assignments[0]
    target = d.XrayClassificationSubject(
        assignment.subject_kind,
        uid(9999),
        assignment.dimension,
        assignment.taxonomy_id,
        assignment.taxonomy_version,
    )
    gap = replace(
        batch,
        evidence=replace(batch.evidence, state=d.XraySourceState.GAP),
        assignments=(),
        requested_subjects=(target,),
    )
    dependencies = tuple(
        replace(row, subject_kind=assignment.subject_kind, subject_id=assignment.subject_id)
        if row.id == batch.evidence.source_reference_id
        else row
        for row in value.source_dependencies
    )
    with pytest.raises(DomainError):
        replace(
            value,
            classification_batches=(gap, *value.classification_batches[1:]),
            source_dependencies=dependencies,
        )


def test_physical_reference_shape_pins_real_snapshot_rows_and_license_branches() -> None:
    value = fixture()
    internal = next(
        item for item in value.source_dependencies if item.kind is d.XrayDependencyKind.VALUATION
    )
    licensed = next(
        item for item in value.source_dependencies if item.kind is d.XrayDependencyKind.CONSTITUENTS
    )
    with pytest.raises(DomainError):
        replace(internal, reference=replace(internal.reference, parent_record_id=uid(100)))
    with pytest.raises(DomainError):
        replace(licensed, reference=internal.reference, provider_id=None, license_version_id=None)
    with pytest.raises(DomainError):
        replace(licensed, provider_id="synthetic")
    with pytest.raises(DomainError):
        replace(value.positions[0].reporting_value, confidence=cast(Any, "0.9"))
    anchorless = replace(value.positions[0], valuation_refs=())
    with pytest.raises(DomainError):
        replace(value, positions=(anchorless, *value.positions[1:]))


def test_gap_headers_preserve_unknown_nulls_and_never_invent_zero() -> None:
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component

    source = fixture().constituent_candidates[0]
    gap = replace(
        source,
        holdings=(),
        stated_coverage=None,
        cash_weight=None,
        unresolved_weight=None,
        evidence=replace(source.evidence, state=d.XraySourceState.GAP),
    )
    payload = encode_xray_component(gap)
    assert decode_xray_component(payload, d.XrayConstituentCandidate) == gap
    for changes in (
        {"cash_weight": Decimal("0")},
        {"holdings": source.holdings},
        {"evidence": source.evidence},
    ):
        with pytest.raises(DomainError):
            replace(gap, **changes)


def test_broker_fx_binds_actual_rows_listing_cutoff_and_retained_rate() -> None:
    from trading212_domain.values import Instant

    from tests.unit.analytics.xray_factories import AT, Builder

    builder = Builder()
    quote = builder.broker_position()
    value = builder.finish()
    for changed in (
        replace(quote, listing_id=uid(909)),
        replace(quote, calculation_run_id=uid(909)),
        replace(quote, source_record_id=uid(909)),
        replace(quote, source_observed_at=Instant.parse("2027-01-01T00:00:00Z")),
    ):
        with pytest.raises(DomainError):
            replace(value, broker_fx=(changed,))
    with pytest.raises(DomainError):
        replace(value, broker_fx=())
    with pytest.raises(DomainError):
        replace(quote, observed_at=Instant.parse("2026-01-01T00:00:00Z"), source_observed_at=AT)
    with pytest.raises(DomainError):
        replace(quote, rate=Decimal("0"))
    dependency = next(
        item for item in value.source_dependencies if item.id == quote.source_reference_id
    )
    with pytest.raises(DomainError):
        replace(dependency, provider_id=str(uid(900)), license_version_id=uid(999))
    with pytest.raises(DomainError):
        replace(dependency, kind=d.XrayDependencyKind.FX)


def test_relationship_shapes_match_real_catalog_rows_without_fabricated_endpoints() -> None:
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component

    from tests.unit.analytics.xray_factories import Builder

    builder = Builder()
    evidence = builder.evidence(
        d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.INSTRUMENT, uid(10)
    )
    share_class = d.XrayRelationshipVersion(
        uid(10),
        None,
        uid(110),
        d.XrayRelationshipKind.SHARE_CLASS,
        None,
        evidence,
        share_class_id=uid(707),
    )
    assert (
        decode_xray_component(encode_xray_component(share_class), d.XrayRelationshipVersion)
        == share_class
    )
    for changes in (
        {"share_class_id": None},
        {"units_per_receipt": Decimal("1")},
        {"underlying_instrument_id": uid(11)},
        {"parent_entity_id": uid(111)},
    ):
        with pytest.raises(DomainError):
            replace(share_class, **changes)
    with pytest.raises(DomainError):
        d.XrayRelationshipVersion(
            None,
            None,
            uid(110),
            d.XrayRelationshipKind.ISSUER_PARENT,
            None,
            evidence,
            parent_entity_id=uid(110),
        )


def test_public_component_codec_decodes_null_enum_reason_before_enum_construction() -> None:
    from trading212_domain.enums import QualityState
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component

    metric = d.XrayRatioMetric(
        Decimal("0"),
        None,
        QualityState.FRESH,
        d.XrayBound.EXACT,
        d.XrayAvailability.AVAILABLE,
        None,
    )
    payload = encode_xray_component(metric)
    assert decode_xray_component(payload, d.XrayRatioMetric) == metric
    malformed = json.loads(payload)
    malformed["value"]["reason"] = "not_a_reason"
    with pytest.raises(DomainError):
        decode_xray_component(wire(malformed), d.XrayRatioMetric)


def test_licensed_fx_codec_retains_order_and_binds_actual_quote_rows() -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component

    from tests.unit.analytics.xray_factories import EUR, Builder

    builder = Builder()
    position = builder.position(uid(10), "1")
    usd, gbp = CurrencyCode("USD"), CurrencyCode("GBP")
    first = builder.fx_leg(usd, EUR, "3", inverse=True)
    second = builder.fx_leg(usd, gbp, "3", snapshot_id=first.snapshot_id)
    conversion = d.XrayLicensedFx(position.root.key, position.reporting_value, gbp, (first, second))
    assert decode_xray_component(encode_xray_component(conversion), d.XrayLicensedFx) == conversion
    builder.reporting_currency = gbp
    builder.licensed_fx.append(conversion)
    builder.positions[0] = replace(
        position,
        reporting_value=convert_xray_money(position.reporting_value, gbp, legs=conversion.legs),
        fx_refs=tuple(leg.source_reference_id for leg in conversion.legs),
    )
    value = builder.finish()
    assert encode_xray_input(decode_xray_input(encode_xray_input(value))) == encode_xray_input(
        value
    )
    for leg in (replace(first, snapshot_id=uid(11111)), replace(first, observation_id=uid(11111))):
        with pytest.raises(DomainError):
            replace(value, licensed_fx=(replace(conversion, legs=(leg, second)),))
    with pytest.raises(DomainError):
        replace(value, licensed_fx=())
    with pytest.raises(DomainError):
        replace(conversion, legs=(second, first))
    with pytest.raises(DomainError):
        replace(conversion, consumer_key="made-up-subject")
    dependency = next(
        row for row in value.source_dependencies if row.id == second.source_reference_id
    )
    for changed in (
        replace(dependency, provider_id=str(uid(901))),
        replace(dependency, subject_kind=d.XraySubjectKind.INSTRUMENT),
        replace(dependency, subject_id=uid(11111)),
    ):
        with pytest.raises(DomainError):
            replace(
                value,
                source_dependencies=tuple(
                    changed if row.id == changed.id else row for row in value.source_dependencies
                ),
            )


def test_licensed_fx_leg_requires_one_actual_observation_or_coverage_gap_identity() -> None:
    from trading212_domain.sources import ObservationState
    from trading212_domain.values import CurrencyCode
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component

    from tests.unit.analytics.xray_factories import EUR, Builder

    quote = Builder().fx_leg(EUR, CurrencyCode("GBP"), "0.8")
    gap = replace(
        quote,
        observation_id=None,
        coverage_gap_id=uid(11111),
        rate=None,
        state=ObservationState.MISSING,
    )
    assert decode_xray_component(encode_xray_component(gap), d.XrayFxLeg) == gap
    for changed in (
        {"observation_id": None},
        {"coverage_gap_id": uid(11111)},
        {
            "observation_id": None,
            "coverage_gap_id": uid(11111),
            "rate": None,
            "state": ObservationState.UNSUPPORTED,
        },
    ):
        with pytest.raises(DomainError):
            replace(quote, **changed)
    with pytest.raises(DomainError):
        replace(gap, rate=Decimal("0.8"), state=ObservationState.AVAILABLE)
    with pytest.raises(DomainError):
        d.XrayPhysicalReference(d.XrayReferenceKind.FX_COVERAGE_GAP, uid(11111), None)


def test_licensed_fx_rejects_opaque_reference_and_future_quote() -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode, Instant

    from tests.unit.analytics.xray_factories import EUR, Builder

    builder = Builder()
    position = builder.position(uid(10), "5")
    usd = CurrencyCode("USD")
    leg = builder.fx_leg(EUR, usd, "1.2")
    conversion = d.XrayLicensedFx(position.root.key, position.reporting_value, usd, (leg,))
    builder.reporting_currency = usd
    builder.licensed_fx.append(conversion)
    builder.positions[0] = replace(
        position,
        reporting_value=convert_xray_money(position.reporting_value, usd, legs=(leg,)),
        fx_refs=(leg.source_reference_id,),
    )
    value = builder.finish()
    for changed in (
        replace(leg, observed_at=Instant.parse("2030-01-01T00:00:00Z")),
        replace(leg, first_known_at=Instant.parse("2030-01-01T00:00:00Z")),
    ):
        with pytest.raises(DomainError):
            replace(value, licensed_fx=(replace(conversion, legs=(changed,)),))
    changed_dependency = replace(
        value.source_dependencies[-1],
        reference=d.XrayPhysicalReference(d.XrayReferenceKind.FX_SNAPSHOT, leg.snapshot_id, None),
    )
    with pytest.raises(DomainError):
        replace(value, source_dependencies=(*value.source_dependencies[:-1], changed_dependency))


def test_quality_coverage_bounds_and_codec_preserve_distinct_zero_and_unavailable() -> None:
    from trading212_domain.xray_codec import decode_xray_component, encode_xray_component
    from trading212_domain.xray_result import XrayQualityCoverage

    from tests.unit.analytics.xray_factories import Builder

    builder = Builder()
    builder.position(uid(10), None)
    coverage = calculate_xray(builder.finish()).portfolio_summary.quality_coverage
    assert decode_xray_component(encode_xray_component(coverage), XrayQualityCoverage) == coverage
    assert coverage.direct_portfolio_value.value is not None
    assert coverage.direct_portfolio_value.value.amount == Decimal("0")
    assert coverage.direct_portfolio_weight.value is None
    with pytest.raises(DomainError):
        replace(coverage, valued_root_count=2)
    with pytest.raises(DomainError):
        replace(coverage, root_count=10_001)
    with pytest.raises(DomainError):
        replace(coverage, inferred_mapping_count=100_001)
