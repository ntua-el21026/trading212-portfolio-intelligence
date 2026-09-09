from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, DefaultContext, Inexact, Rounded, localcontext
from typing import Any, cast
from unittest.mock import patch

import pytest
from trading212_analytics.xray import (
    calculate_common_entities,
    calculate_overlap_pairs,
    calculate_xray,
    company_exposure_basis,
    project_common_entities_top,
    verify_xray_result,
)
from trading212_domain import xray as d
from trading212_domain.errors import DomainError
from trading212_domain.values import Instant
from trading212_domain.xray_codec import decode_xray_result, encode_xray_input, encode_xray_result
from trading212_domain.xray_result import CanonicalFundPair

from .xray_factories import AT, Builder, fixture, reversed_input, uid

pytestmark = pytest.mark.unit


def test_frozen_economic_example_all_dimensions_and_provenance() -> None:
    value = fixture()
    result = calculate_xray(value)
    basis = company_exposure_basis(result)
    weights = {item.bucket_key: item.absolute_weight.value for item in basis.exposures}
    assert weights == {str(uid(110)): Decimal("0.56"), str(uid(111)): Decimal("0.39")}
    assert result.portfolio_summary.unresolved_weight.value == Decimal("0.05")
    assert result.portfolio_summary.duplicated_exposure.value == Decimal("0.41")
    assert result.portfolio_summary.hhi.value == Decimal("0.4657")
    assert {item.dimension for item in result.dimensions} == set(d.XrayDimension)
    assert all(item.known_weight.value == Decimal("0.95") for item in result.dimensions)
    assert result.direct_positions[1].is_fund
    assert result.direct_positions[1].reporting_value.value is not None
    assert result.direct_positions[1].reporting_value.value.amount == Decimal("500")
    assert result.typed_source_uses and result.classification_decisions
    assert all(item.confidence is not None for item in result.exposure_buckets)
    assert all(path.reporting_value.value is not None for path in result.terminal_paths)
    assert all(len(path.dimension_weights) == 6 for path in result.terminal_paths)
    assert decode_xray_result(encode_xray_result(result)) == result
    verify_xray_result(value, result)


def test_input_permutations_do_not_change_any_canonical_result_or_proof() -> None:
    from trading212_domain.xray_codec import decode_xray_input

    value = fixture()
    reordered = reversed_input(value)
    assert encode_xray_input(value) == encode_xray_input(reordered)
    expected = calculate_xray(value)
    assert calculate_xray(reordered) == expected
    assert calculate_xray(decode_xray_input(encode_xray_input(value))) == expected
    assert encode_xray_result(expected) == encode_xray_result(calculate_xray(reordered))


def test_overlap_common_and_top_are_pure_retained_unit_projections() -> None:
    result = calculate_xray(fixture())
    with patch("trading212_analytics.xray.walk", side_effect=AssertionError("must not retraverse")):
        pairs = calculate_overlap_pairs(result, (uid(30), uid(20)))
        common = calculate_common_entities(result, CanonicalFundPair(uid(20), uid(30)))
        top = project_common_entities_top(common, 1)
    assert pairs[0].overlap.value == Decimal("0.5")
    assert pairs[0].overlap.bound is d.XrayBound.LOWER_BOUND
    assert [item.entity_id for item in common.entities] == [uid(111), uid(110)]
    assert top.returned_count == 1 and top.omitted_count == 1 and top.total_count == 2
    assert top.omitted_common_weight.value == Decimal("0.2")


@pytest.mark.parametrize("composition", ("disjoint", "partial", "subquantum"))
def test_pair_exact_zero_lower_zero_and_subquantum_common_mass_are_distinct(
    composition: str,
) -> None:
    from fractions import Fraction

    from .test_xray_decimal import oracle

    builder = Builder()
    builder.position(uid(20), "100")
    builder.position(uid(30), "100")
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(111))
    expected = Fraction()
    if composition == "subquantum":
        builder.fund(uid(20), ((uid(21), "0.000000000000000001"),))
        builder.fund(uid(21), ((uid(10), "0.1"),))
        builder.fund(uid(30), ((uid(31), "0.000000000000000001"),))
        builder.fund(uid(31), ((uid(10), "0.1"),))
        expected = Fraction(1, 10**19)
    else:
        weight = "1" if composition == "disjoint" else "0.5"
        builder.fund(uid(20), ((uid(10), weight),))
        builder.fund(uid(30), ((uid(11), weight),))
    result = calculate_xray(builder.finish())
    pair = calculate_overlap_pairs(result, (uid(20), uid(30)))[0]
    common = calculate_common_entities(result, CanonicalFundPair(uid(20), uid(30)))
    assert Fraction(pair.overlap_coefficient) / 10**72 == expected
    assert pair.overlap.value == oracle(expected) == Decimal("0")
    assert pair.overlap.availability is d.XrayAvailability.AVAILABLE
    assert pair.overlap.bound is (
        d.XrayBound.EXACT if composition == "disjoint" else d.XrayBound.LOWER_BOUND
    )
    assert pair.overlap.positive_below_quantum is (composition == "subquantum")
    assert all(fund.complete is (composition == "disjoint") for fund in result.fund_compositions)
    assert pair.common_entity_count == len(common.entities) == (1 if expected else 0)
    if expected:
        entity = common.entities[0]
        assert entity.entity_id == uid(110)
        assert entity.common_weight.value == Decimal("0")
        assert entity.common_weight.positive_below_quantum
        assert Fraction(entity.common_coefficient) / 10**72 == expected
    else:
        assert common.entities == ()


@pytest.mark.parametrize("amount", ["0", None])
def test_unit_composition_survives_zero_money_and_missing_fx(amount: str | None) -> None:
    builder = Builder()
    builder.position(uid(20), amount, position_id=uid(1000))
    builder.position(uid(30), amount, position_id=uid(1001))
    builder.identity(uid(10), uid(110))
    builder.fund(uid(20), ((uid(10), "1"),))
    builder.fund(uid(30), ((uid(10), "1"),))
    value = builder.finish()
    result = calculate_xray(value)
    pair = calculate_overlap_pairs(result, (uid(20), uid(30)))[0]
    assert pair.overlap.value == Decimal("1") and pair.overlap.bound is d.XrayBound.EXACT
    assert result.portfolio_summary.hhi.value is None
    assert all(item.complete for item in result.fund_compositions)
    if amount is None:
        assert all(path.money_coefficient is None for path in result.terminal_paths)
    verify_xray_result(value, result)


def test_first_real_position_is_representative_even_when_zero() -> None:
    builder = Builder()
    builder.position(uid(20), "100", position_id=uid(1001))
    builder.position(uid(20), "0", position_id=uid(1000))
    builder.identity(uid(10), uid(110))
    builder.fund(uid(20), ((uid(10), "0.8"),))
    result = calculate_xray(builder.finish())
    composition = result.fund_compositions[0]
    assert composition.composition_root_key == f"position:{uid(1000)}"
    assert composition.entities[0].weight.value == Decimal("0.8")
    assert composition.unresolved_weight.value == Decimal("0.2")
    assert all(
        path.money_coefficient == 0
        for path in result.terminal_paths
        if path.root_key == composition.composition_root_key
    )


def test_four_edges_cycle_and_diamond_preserve_unit_mass() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    builder.identity(uid(10), uid(110))
    builder.fund(uid(20), ((uid(21), "0.5"), (uid(22), "0.5")))
    builder.fund(uid(21), ((uid(23), "1"),))
    builder.fund(uid(22), ((uid(23), "1"),))
    builder.fund(uid(23), ((uid(10), "0.5"), (uid(20), "0.5")))
    result = calculate_xray(builder.finish())
    assert len([path for path in result.terminal_paths if path.entity_id == uid(110)]) == 2
    assert (
        len(
            [path for path in result.terminal_paths if path.unresolved_reason is d.XrayReason.CYCLE]
        )
        == 2
    )
    assert result.fund_compositions[0].unresolved_weight.value == Decimal("0.5")
    assert sum(
        (path.relative_coefficient for path in result.terminal_paths), Decimal("0")
    ) == Decimal("1e72")


def test_fifth_fund_edge_retains_entire_parent_unresolved() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    for instrument in range(20, 25):
        builder.fund(uid(instrument), ((uid(instrument + 1), "1"),))
    builder.identity(uid(25), uid(125))
    result = calculate_xray(builder.finish())
    assert len(result.terminal_paths) == 1
    path = result.terminal_paths[0]
    assert len(path.fund_edges) == 4
    assert path.unresolved_reason is d.XrayReason.DEPTH_LIMIT
    assert path.relative_coefficient == Decimal("1e72")


def test_pending_root_capacity_preserves_cash_and_no_favorable_child_prefix() -> None:
    builder = Builder()
    builder.position(uid(20), "100", position_id=uid(1000))
    builder.cash_row("1", row_id=uid(999))
    builder.fund(uid(20), tuple((uid(10), "0.0001") for _ in range(9999)))
    builder.identity(uid(10), uid(110))
    result = calculate_xray(builder.finish())
    assert result.exact_state.visited_paths == 2
    assert len(result.terminal_paths) == 2
    assert result.terminal_paths[0].unresolved_reason is d.XrayReason.PATH_LIMIT
    assert result.terminal_paths[1].explicit_cash
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("101")


def test_initial_root_inventory_overflow_includes_cash_and_rejects_complete_capture() -> None:
    from trading212_domain.errors import ErrorCode

    builder = Builder()
    for _ in range(10_000):
        builder.position(uid(10), "0")
    builder.cash_row("0")
    with pytest.raises(DomainError) as failure:
        builder.finish()
    assert failure.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert failure.value.field == "roots"
    assert len(builder.positions) == 10_000 and len(builder.cash) == 1


def test_cutoff_equality_future_effective_and_first_knowledge_are_distinct() -> None:
    value = fixture()
    first = value.constituent_candidates[0]
    known_equal = replace(
        first, evidence=replace(first.evidence, first_known_at=value.source_cutoff_at)
    )
    equal_input = replace(
        value, constituent_candidates=(known_equal, *value.constituent_candidates[1:])
    )
    assert calculate_xray(equal_input).fund_compositions[0].coverage.value == Decimal("0.9")
    for changed in (
        replace(first.evidence, effective_at=Instant.parse("2026-01-01T00:00:00Z")),
        replace(first.evidence, first_known_at=Instant.parse("2026-09-08T00:00:00Z")),
    ):
        candidate = replace(first, evidence=changed)
        output = calculate_xray(
            replace(value, constituent_candidates=(candidate, *value.constituent_candidates[1:]))
        )
        assert output.fund_compositions[0].unresolved_weight.value == Decimal("1")


def test_preferred_provider_gap_blocks_available_secondary() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    builder.identity(uid(10), uid(110))
    first = builder.fund(uid(20), ((uid(10), "1"),))
    other_evidence = builder.evidence(
        d.XrayDependencyKind.CONSTITUENTS, d.XraySubjectKind.FUND_MAPPING, first.fund_mapping_id
    )
    builder.dependencies[-1] = replace(builder.dependencies[-1], provider_id=str(uid(901)))
    builder.constituents[0] = replace(
        first, evidence=replace(first.evidence, state=d.XraySourceState.GAP)
    )
    builder.constituents.append(replace(first, id=builder.next_id(), evidence=other_evidence))
    result = calculate_xray(builder.finish())
    assert result.terminal_paths[0].unresolved_reason is d.XrayReason.SOURCE_GAP
    assert result.fund_compositions[0].unresolved_weight.value == 1


def test_explicit_entity_classification_wins_and_conflicting_fallback_is_unresolved() -> None:
    builder = Builder()
    builder.position(uid(10), "40")
    builder.position(uid(11), "60")
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(110))
    builder.classifications_for(uid(110), key="explicit")
    original = builder.classifications.pop()
    first = replace(
        original,
        assignments=tuple(
            replace(
                row,
                subject_kind=d.XraySubjectKind.INSTRUMENT,
                subject_id=uid(10),
                bucket_key="first",
            )
            for row in original.assignments
        ),
    )
    second_evidence = builder.evidence(
        d.XrayDependencyKind.CLASSIFICATION, d.XraySubjectKind.SOURCE_RECORD, None
    )
    second = replace(
        original,
        evidence=second_evidence,
        assignments=tuple(
            replace(
                row,
                id=builder.next_id(),
                subject_kind=d.XraySubjectKind.INSTRUMENT,
                subject_id=uid(11),
                bucket_key="second",
            )
            for row in original.assignments
        ),
    )
    builder.classifications.extend((first, second))
    partial = calculate_xray(builder.finish())
    assert all(
        row.unresolved_weight.value == 1
        for row in partial.dimensions
        if row.dimension is not d.XrayDimension.COMPANY
    )
    explicit_evidence = builder.evidence(
        d.XrayDependencyKind.CLASSIFICATION, d.XraySubjectKind.SOURCE_RECORD, None
    )
    builder.classifications.append(replace(original, evidence=explicit_evidence))
    complete = calculate_xray(builder.finish())
    assert all(row.known_weight.value == 1 for row in complete.dimensions)


@pytest.mark.parametrize("subject_kind", (d.XraySubjectKind.ENTITY, d.XraySubjectKind.INSTRUMENT))
@pytest.mark.parametrize("gap_source", ("newer", "preferred", "mixed"))
def test_requested_classification_gap_blocks_only_matching_older_assignment(
    subject_kind: d.XraySubjectKind, gap_source: str
) -> None:
    builder = Builder()
    builder.position(uid(10), "40")
    builder.position(uid(11), "60")
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(111))
    builder.classifications_for(uid(110), key="first")
    builder.classifications_for(uid(111), key="second")
    first = builder.classifications[0]
    subject = uid(110) if subject_kind is d.XraySubjectKind.ENTITY else uid(10)
    builder.classifications[0] = replace(
        first,
        assignments=tuple(
            replace(row, subject_kind=subject_kind, subject_id=subject) for row in first.assignments
        ),
    )
    if subject_kind is d.XraySubjectKind.ENTITY:
        builder.classifications.append(
            replace(
                first,
                evidence=builder.evidence(
                    d.XrayDependencyKind.CLASSIFICATION, d.XraySubjectKind.SOURCE_RECORD, None
                ),
                assignments=tuple(
                    replace(
                        row,
                        id=builder.next_id(),
                        subject_kind=d.XraySubjectKind.INSTRUMENT,
                        subject_id=uid(10),
                    )
                    for row in first.assignments
                ),
            )
        )
    sector = next(row for row in first.assignments if row.dimension is d.XrayDimension.SECTOR)
    target = d.XrayClassificationSubject(
        subject_kind, subject, sector.dimension, sector.taxonomy_id, sector.taxonomy_version
    )
    evidence = builder.evidence(
        d.XrayDependencyKind.CLASSIFICATION, d.XraySubjectKind.SOURCE_RECORD, None
    )
    if gap_source == "preferred":
        builder.dependencies = [
            replace(row, provider_id=str(uid(901)))
            if row.id == first.evidence.source_reference_id
            else row
            for row in builder.dependencies
        ]
    evidence = replace(
        evidence,
        revision=1 if gap_source == "preferred" else 2,
        state=d.XraySourceState.AVAILABLE if gap_source == "mixed" else d.XraySourceState.GAP,
    )
    # A complete page can have both a returned row and a requested subject with no row.
    available = (
        tuple(
            replace(row, id=builder.next_id())
            for row in builder.classifications[1].assignments
            if row.dimension is d.XrayDimension.SECTOR
        )
        if gap_source == "mixed"
        else ()
    )
    builder.classifications.append(d.XrayClassificationBatch(evidence, available, (target,)))
    value = builder.finish()
    result = calculate_xray(value)
    dimensions = {row.dimension: row for row in result.dimensions}
    assert dimensions[d.XrayDimension.SECTOR].known_weight.value == Decimal("0.6")
    assert dimensions[d.XrayDimension.SECTOR].unresolved_weight.value == Decimal("0.4")
    assert all(
        row.known_weight.value == Decimal("1")
        for row in result.dimensions
        if row.dimension is not d.XrayDimension.SECTOR
    )
    decision = next(
        row
        for row in result.classification_decisions
        if row.entity_id == uid(110) and row.dimension is d.XrayDimension.SECTOR
    )
    assert decision.bucket_key is None and decision.assignment_ids == ()
    assert decision.evidence_ids == (evidence.id,)
    assert decision.source_reference_ids == (evidence.source_reference_id,)
    assert decision.reason is (
        d.XrayReason.SOURCE_GAP
        if subject_kind is d.XraySubjectKind.ENTITY
        else d.XrayReason.AMBIGUOUS_CLASSIFICATION
    )
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("100")
    verify_xray_result(value, result)


@pytest.mark.parametrize("ineligible", ("future_effective", "future_known", "other_taxonomy"))
def test_ineligible_requested_classification_gap_cannot_rewrite_selected_history(
    ineligible: str,
) -> None:
    builder = Builder()
    builder.position(uid(10), "100")
    builder.identity(uid(10), uid(110))
    builder.classifications_for(uid(110))
    original = builder.finish()
    sector = next(
        row
        for row in builder.classifications[0].assignments
        if row.dimension is d.XrayDimension.SECTOR
    )
    evidence = replace(
        builder.evidence(
            d.XrayDependencyKind.CLASSIFICATION, d.XraySubjectKind.SOURCE_RECORD, None
        ),
        revision=2,
        state=d.XraySourceState.GAP,
        effective_at=Instant.parse("2026-01-01T00:00:00Z")
        if ineligible == "future_effective"
        else AT,
        first_known_at=Instant.parse("2026-09-08T00:00:00Z")
        if ineligible == "future_known"
        else AT,
    )
    target = d.XrayClassificationSubject(
        sector.subject_kind,
        sector.subject_id,
        sector.dimension,
        uid(9999) if ineligible == "other_taxonomy" else sector.taxonomy_id,
        sector.taxonomy_version,
    )
    builder.classifications.append(d.XrayClassificationBatch(evidence, (), (target,)))
    result = calculate_xray(builder.finish())
    assert result.dimensions == calculate_xray(original).dimensions
    assert all(row.known_weight.value == Decimal("1") for row in result.dimensions)
    assert all(evidence.id not in row.evidence_ids for row in result.classification_decisions)


def test_threshold_exact_comparison_can_breach_partial_but_not_clear_it() -> None:
    value = fixture()
    threshold_id, reference_id = uid(777), uid(778)
    policy = d.ConcentrationThresholdPolicy(
        threshold_id,
        "1",
        reference_id,
        Decimal("0.56"),
        Decimal("0.99"),
        Decimal("0.4657"),
        d.XrayComparison.GE,
        d.XrayComparison.GT,
        d.XrayComparison.GE,
    )
    dependency = d.XraySourceDependency(
        reference_id,
        value.owner_id,
        value.account_id,
        value.snapshot_id,
        d.XrayDependencyKind.THRESHOLD,
        d.XraySubjectKind.POLICY,
        threshold_id,
        None,
        None,
        "b" * 64,
        d.XrayPhysicalReference(d.XrayReferenceKind.OWNER_POLICY, threshold_id, None),
    )
    value = replace(
        value,
        policy=replace(value.policy, thresholds=policy),
        source_dependencies=(*value.source_dependencies, dependency),
    )
    result = calculate_xray(value)
    assert [row.breached for row in result.portfolio_summary.thresholds] == [True, None, True]
    assert result.portfolio_summary.thresholds[1].reason is d.XrayReason.INCONCLUSIVE_LOWER_BOUND


def test_source_warnings_and_confidence_use_pinned_evaluation_time() -> None:
    value = fixture()
    policy = replace(
        value.policy,
        freshness_policy=replace(
            value.policy.freshness_policy,
            stale_after_seconds=1,
            evaluation_basis="source_cutoff_at",
        ),
    )
    result = calculate_xray(replace(value, policy=policy))
    assert result.quality_evaluated_at == value.source_cutoff_at
    assert any(item.code is d.XrayWarningCode.STALE_SOURCE for item in result.warnings)
    assert all(item.confidence == Decimal("0.8") for item in result.exposure_buckets)


def test_hostile_ambient_and_default_context_success_error_and_flags_are_isolated() -> None:
    value = fixture()
    baseline = encode_xray_result(calculate_xray(value))
    default_saved = DefaultContext.copy()
    try:
        DefaultContext.prec = 2
        DefaultContext.rounding = ROUND_DOWN
        DefaultContext.Emax = 2
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            context.Emin = -2
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            context.flags[Inexact] = True
            before = context.copy()
            result = calculate_xray(value)
            verify_xray_result(value, result)
            calculate_overlap_pairs(result, (uid(20), uid(30)))
            assert encode_xray_result(result) == baseline
            with pytest.raises(DomainError):
                calculate_overlap_pairs(result, (uid(20), uid(20)))
            assert context == before or (
                context.prec,
                context.Emin,
                context.Emax,
                context.rounding,
                dict(context.flags),
                dict(context.traps),
            ) == (
                before.prec,
                before.Emin,
                before.Emax,
                before.rounding,
                dict(before.flags),
                dict(before.traps),
            )
    finally:
        for field in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(DefaultContext, field, getattr(default_saved, field))
        DefaultContext.flags = default_saved.flags.copy()
        DefaultContext.traps = default_saved.traps.copy()


def test_independent_verifier_rejects_coefficient_and_provenance_mutation() -> None:
    value = fixture()
    result = calculate_xray(value)
    first = result.terminal_paths[0]
    for changed in (
        replace(first, relative_coefficient=Decimal("9" * 72)),
        replace(first, source_reference_ids=()),
    ):
        with pytest.raises(DomainError):
            verify_xray_result(
                value, replace(result, terminal_paths=(changed, *result.terminal_paths[1:]))
            )


def test_zero_representative_with_exhausted_proof_budget_is_not_replaced() -> None:
    builder = Builder()
    representative = builder.position(uid(20), "0", position_id=uid(1000))
    builder.position(uid(20), "100", position_id=uid(1001))
    extra = tuple(
        builder.reference(
            d.XrayDependencyKind.VALUATION,
            d.XraySubjectKind.SNAPSHOT_POSITION,
            uid(1000),
            internal=True,
        )
        for _ in range(253)
    )
    builder.positions[0] = replace(
        representative, valuation_refs=(*representative.valuation_refs, *extra)
    )
    builder.identity(uid(10), uid(110))
    builder.fund(uid(20), ((uid(10), "1"),))
    result = calculate_xray(builder.finish())
    composition = result.fund_compositions[0]
    assert composition.composition_root_key == representative.root.key
    assert composition.unresolved_weight.value == 1 and not composition.complete
    later = [path for path in result.terminal_paths if path.root_key == f"position:{uid(1001)}"]
    assert later and all(path.entity_id == uid(110) for path in later)


def test_positive_subquantum_unknown_mass_is_not_reclassified_as_complete() -> None:
    builder = Builder()
    builder.position(uid(10), "1")
    builder.position(uid(20), "0.000000000000000001")
    builder.identity(uid(10), uid(110))
    builder.fund(uid(20), ((uid(10), "0.999999999999999999"),))
    result = calculate_xray(builder.finish())
    company = next(item for item in result.dimensions if item.dimension is d.XrayDimension.COMPANY)
    assert not company.complete
    assert company.unresolved.value is not None and company.unresolved.value.amount == 0
    assert company.positive_unresolved_below_quantum
    assert company.unresolved_weight.positive_below_quantum
    assert result.fund_compositions[0].unresolved_coefficient > 0


def test_receipt_ratio_is_evidence_and_never_multiplies_already_valued_money() -> None:
    builder = Builder()
    builder.position(uid(10), "250")
    evidence = builder.evidence(
        d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.INSTRUMENT, uid(10)
    )
    builder.relationships.append(
        d.XrayRelationshipVersion(
            uid(10),
            uid(11),
            uid(110),
            d.XrayRelationshipKind.DEPOSITARY_RECEIPT,
            Decimal("20"),
            evidence,
        )
    )
    result = calculate_xray(builder.finish())
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("250")
    assert result.portfolio_summary.company_known_weight.value == 1
    assert result.terminal_paths[0].entity_id == uid(110)
    assert evidence.id in result.terminal_paths[0].identity_decision_ids


def test_revision_conflict_gap_and_same_proof_tie_are_distinct() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    builder.identity(uid(10), uid(110))
    first = builder.fund(uid(20), ((uid(10), "1"),))
    proof = builder.evidence(
        d.XrayDependencyKind.CONSTITUENTS, d.XraySubjectKind.FUND_MAPPING, first.fund_mapping_id
    )
    second = replace(first, id=builder.next_id(), evidence=proof)
    builder.constituents.append(second)
    equal = calculate_xray(builder.finish())
    assert equal.fund_compositions[0].complete
    builder.constituents[-1] = replace(
        second, holdings=(replace(second.holdings[0], weight=Decimal("0.8")),)
    )
    conflict = calculate_xray(builder.finish())
    assert conflict.terminal_paths[0].unresolved_reason is d.XrayReason.AMBIGUOUS_SOURCE
    builder.constituents[-1] = replace(
        builder.constituents[-1], evidence=replace(proof, revision=2)
    )
    corrected = calculate_xray(builder.finish())
    assert corrected.fund_compositions[0].coverage.value == Decimal("0.8")


def test_expired_source_interval_is_exclusive() -> None:
    value = fixture()
    candidate = value.constituent_candidates[0]
    candidate = replace(
        candidate,
        evidence=replace(
            candidate.evidence, effective_at=Instant.parse("2025-12-30T00:00:00Z"), valid_until=AT
        ),
    )
    result = calculate_xray(
        replace(value, constituent_candidates=(candidate, *value.constituent_candidates[1:]))
    )
    assert result.fund_compositions[0].unresolved_weight.value == 1


def test_total_overflow_fails_before_publishing_a_partial_result() -> None:
    value = fixture()
    first = value.positions[0]
    assert first.reporting_value.value is not None
    huge = replace(
        first.reporting_value,
        value=replace(first.reporting_value.value, amount=Decimal("99999999999999999999")),
    )
    changed = replace(value, positions=(replace(first, reporting_value=huge), *value.positions[1:]))
    with pytest.raises(DomainError, match="NUMERIC"):
        calculate_xray(changed)


def test_classification_scalar_decision_binds_full_retained_consensus_and_source_uses() -> None:
    result = calculate_xray(fixture())
    decisions = {item.key: item for item in result.classification_decisions}
    for path in result.terminal_paths:
        for assignment in path.classifications:
            if assignment.decision_key is None:
                continue
            decision = decisions[assignment.decision_key]
            assert decision.dimension is assignment.dimension
            assert decision.bucket_key == assignment.bucket_key
            assert len(decision.assignment_ids) <= 256 and len(decision.evidence_ids) <= 256
            uses = {
                item.evidence_id
                for item in result.typed_source_uses
                if item.consumer_key == decision.key
            }
            assert uses == set(decision.evidence_ids)
            assert set(decision.source_reference_ids).issubset(path.source_reference_ids)


def test_saved_reporting_money_and_real_licensed_fx_subject_are_preserved() -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR

    builder = Builder()
    position = builder.position(uid(10), "250")
    usd = CurrencyCode("USD")
    leg = builder.fx_leg(EUR, usd, "1.2")
    builder.reporting_currency = usd
    builder.licensed_fx.append(
        d.XrayLicensedFx(position.root.key, position.reporting_value, usd, (leg,))
    )
    builder.positions[0] = replace(
        position,
        reporting_value=convert_xray_money(position.reporting_value, usd, legs=(leg,)),
        fx_refs=(leg.source_reference_id,),
    )
    builder.identity(uid(10), uid(110))
    result = calculate_xray(builder.finish())
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("300")
    uses = [item for item in result.typed_source_uses if item.kind is d.XrayDependencyKind.FX]
    assert uses and all(item.subject_id == leg.observation_id for item in uses)


def test_every_terminal_reference_has_an_actual_consumer_use() -> None:
    result = calculate_xray(fixture())
    for path in result.terminal_paths:
        used = {
            item.source_reference_id
            for item in result.typed_source_uses
            if item.consumer_key == path.key
        }
        assert used == set(path.source_reference_ids)


def test_entity_only_constituents_are_supported_without_inventing_instruments() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    source = builder.fund(uid(20), ((uid(10), "0.8"),))
    holding = replace(
        source.holdings[0],
        kind=d.XrayHoldingKind.ENTITY,
        instrument_id=None,
        entity_id=uid(110),
        evidence_key="explicit-entity-evidence",
    )
    builder.constituents[0] = replace(source, holdings=(holding,))
    builder.classifications_for(uid(110), key="entity-only")
    value = builder.finish()
    result = calculate_xray(value)
    path = next(path for path in result.terminal_paths if path.entity_id is not None)
    assert path.instrument_id is None and path.entity_id == uid(110)
    assert holding.id in path.identity_decision_ids
    assert path.reporting_value.value is not None and path.reporting_value.value.amount == Decimal(
        "80"
    )
    assert result.fund_compositions[0].entities[0].weight.value == Decimal("0.8")
    verify_xray_result(value, result)


def test_inclusive_headers_do_not_double_count_cash_and_preserve_header_only_mass() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    builder.identity(uid(10), uid(110))
    source = builder.fund(uid(20), ((uid(10), "0.6"), (None, "0.1")))
    builder.constituents[0] = replace(
        source,
        stated_coverage=Decimal("0.7"),
        cash_weight=Decimal("0.2"),
        unresolved_weight=Decimal("0.1"),
    )
    result = calculate_xray(builder.finish())
    composition = result.fund_compositions[0]
    assert composition.entities[0].weight.value == Decimal("0.6")
    assert composition.cash_weight.value == Decimal("0.2")
    assert composition.unresolved_weight.value == Decimal("0.2")
    assert composition.coverage.value == Decimal("0.8")
    origins = {path.fund_edges[-1].origin: path for path in result.terminal_paths}
    assert origins["header_cash"].explicit_cash
    assert origins["header_cash"].fund_edges[-1].holding_id is None
    assert origins["header_unresolved"].unresolved_reason is d.XrayReason.SOURCE_REMAINDER
    assert origins["remainder"].relative_weight.value == Decimal("0.1")
    assert sum(
        (path.relative_coefficient for path in result.terminal_paths), Decimal("0")
    ) == Decimal("1e72")


def test_source_headers_reject_overclaims_and_row_contradictions() -> None:
    builder = Builder()
    source = builder.fund(uid(20), ((uid(10), "0.6"), (None, "0.2")))
    for changes in (
        {"cash_weight": Decimal("0.1")},
        {"stated_coverage": Decimal("0.5")},
        {"unresolved_weight": Decimal("0.3")},
    ):
        with pytest.raises(DomainError):
            replace(source, **cast(dict[str, Any], changes))


def test_broker_fx_preserves_wallet_rate_and_saved_reporting_amount_without_license() -> None:
    from trading212_domain.xray_codec import decode_xray_input, encode_xray_input

    builder = Builder()
    quote = builder.broker_position()
    builder.identity(uid(10), uid(110))
    value = builder.finish()
    decoded = decode_xray_input(encode_xray_input(value))
    assert decoded.broker_fx == (quote,)
    assert decoded.positions[0].original_value.value is not None
    assert decoded.positions[0].original_value.value.amount == Decimal("62.50")
    assert quote.rate == Decimal("0.8")
    result = calculate_xray(decoded)
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("50")
    assert result.exact_state.roots[0].money_coefficient == Decimal("5e19")
    assert result.terminal_paths[0].confidence is None
    broker_uses = [
        item for item in result.typed_source_uses if item.kind is d.XrayDependencyKind.BROKER_FX
    ]
    assert broker_uses and all(item.subject_id == quote.source_record_id for item in broker_uses)
    assert all(
        item.provider_id is None and item.license_version_id is None
        for item in result.source_dependencies
        if item.kind is d.XrayDependencyKind.BROKER_FX
    )
    verify_xray_result(decoded, result)


@pytest.mark.parametrize(
    ("original", "rate", "saved"),
    (
        ("0", "0.8", "0"),
        ("0.000000000000000001", "0.5", "0"),
        ("0.000000000000000003", "0.5", "0.000000000000000002"),
    ),
)
def test_broker_fx_saved_boundary_uses_exact_half_even(
    original: str, rate: str, saved: str
) -> None:
    builder = Builder()
    builder.broker_position(original, saved, rate)
    value = builder.finish()
    result = calculate_xray(value)
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal(saved)
    verify_xray_result(value, result)


def test_broker_fx_wrong_saved_conversion_fails_before_any_result() -> None:
    builder = Builder()
    builder.broker_position(reporting="40")  # A second 0.8 conversion must not pass.
    with pytest.raises(DomainError):
        calculate_xray(builder.finish())


def test_broker_fx_hostile_context_success_and_mismatch() -> None:
    from decimal import ROUND_DOWN, Context, localcontext

    good = Builder()
    good.broker_position()
    good_value = good.finish()
    bad = Builder()
    bad.broker_position(reporting="40")
    bad_value = bad.finish()
    with localcontext(Context(prec=2, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as hostile:
        before = hostile.copy()
        result = calculate_xray(good_value)
        verify_xray_result(good_value, result)
        with pytest.raises(DomainError):
            calculate_xray(bad_value)
        assert hostile.prec == before.prec and hostile.flags == before.flags


def test_listing_and_issuer_parent_rows_are_retained_without_automatic_equity_merge() -> None:
    from trading212_domain.xray_codec import decode_xray_input, encode_xray_input

    builder = Builder()
    builder.position(uid(10), "100", listing=uid(501))
    builder.identity(uid(10), uid(110))
    listing_evidence = builder.evidence(
        d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.LISTING, uid(501)
    )
    parent_evidence = builder.evidence(
        d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.ENTITY, uid(110)
    )
    builder.relationships.extend(
        (
            d.XrayRelationshipVersion(
                uid(10),
                None,
                None,
                d.XrayRelationshipKind.LISTING_OF,
                None,
                listing_evidence,
                listing_id=uid(501),
            ),
            d.XrayRelationshipVersion(
                None,
                None,
                uid(110),
                d.XrayRelationshipKind.ISSUER_PARENT,
                None,
                parent_evidence,
                parent_entity_id=uid(999),
            ),
        )
    )
    value = builder.finish()
    assert encode_xray_input(decode_xray_input(encode_xray_input(value))) == encode_xray_input(
        value
    )
    result = calculate_xray(value)
    path = result.terminal_paths[0]
    assert path.entity_id == uid(110)
    assert listing_evidence.id in path.identity_decision_ids
    assert parent_evidence.id not in path.identity_decision_ids
    assert {item.id for item in result.source_dependencies} >= {
        listing_evidence.source_reference_id,
        parent_evidence.source_reference_id,
    }
    verify_xray_result(value, result)


def test_explicit_conflicting_listing_evidence_cannot_relabel_a_saved_root() -> None:
    builder = Builder()
    builder.position(uid(10), "100", listing=uid(501))
    builder.identity(uid(10), uid(110))
    evidence = builder.evidence(
        d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.LISTING, uid(501)
    )
    builder.relationships.append(
        d.XrayRelationshipVersion(
            uid(11),
            None,
            None,
            d.XrayRelationshipKind.LISTING_OF,
            None,
            evidence,
            listing_id=uid(501),
        )
    )
    result = calculate_xray(builder.finish())
    assert result.terminal_paths[0].entity_id is None
    assert result.terminal_paths[0].unresolved_reason is d.XrayReason.AMBIGUOUS_IDENTITY
    assert result.terminal_paths[0].reporting_value.value is not None
    assert result.terminal_paths[0].reporting_value.value.amount == Decimal("100")


def test_unknown_receipt_unit_ratio_is_retained_and_never_multiplies_money() -> None:
    builder = Builder()
    builder.position(uid(10), "100")
    evidence = builder.evidence(
        d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.INSTRUMENT, uid(10)
    )
    builder.relationships.append(
        d.XrayRelationshipVersion(
            uid(10),
            uid(11),
            uid(110),
            d.XrayRelationshipKind.DEPOSITARY_RECEIPT,
            None,
            evidence,
        )
    )
    value = builder.finish()
    result = calculate_xray(value)
    assert result.terminal_paths[0].entity_id == uid(110)
    assert result.terminal_paths[0].reporting_value.value is not None
    assert result.terminal_paths[0].reporting_value.value.amount == Decimal("100")
    verify_xray_result(value, result)


@pytest.mark.parametrize(
    ("original", "rate", "inverse", "expected"),
    (
        ("50", "1.25", False, "62.5"),
        ("50", "1.25", True, "40"),
        ("1", "3", True, "0.333333333333333333"),
        ("0.000000000000000001", "0.5", False, "0"),
        ("0.000000000000000003", "0.5", False, "0.000000000000000002"),
        ("-0.000000000000000003", "0.5", False, "-0.000000000000000002"),
    ),
)
def test_licensed_fx_exact_rounding(original: str, rate: str, inverse: bool, expected: str) -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR, metric

    usd = CurrencyCode("USD")
    builder = Builder()
    leg = builder.fx_leg(usd if inverse else EUR, EUR if inverse else usd, rate, inverse=inverse)
    result = convert_xray_money(metric(original), usd, legs=(leg,))
    assert result.value is not None and result.value.currency == usd
    assert result.value.amount == Decimal(expected)


def test_two_leg_fx_rounds_only_after_the_complete_route() -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR, metric

    usd, gbp = CurrencyCode("USD"), CurrencyCode("GBP")
    builder = Builder()
    first = builder.fx_leg(usd, EUR, "3", inverse=True)
    second = builder.fx_leg(usd, gbp, "3", snapshot_id=first.snapshot_id)
    result = convert_xray_money(metric("1"), gbp, legs=(first, second))
    assert result.value is not None and result.value.amount == Decimal("1")
    with pytest.raises(DomainError):
        convert_xray_money(metric("1"), gbp, legs=(second, first))


@pytest.mark.parametrize("mismatch", ("snapshot", "observed_at"))
def test_two_leg_fx_rejects_incompatible_source_fixings(mismatch: str) -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR, metric

    usd, gbp = CurrencyCode("USD"), CurrencyCode("GBP")
    builder = Builder()
    first = builder.fx_leg(usd, EUR, "3", inverse=True)
    second = builder.fx_leg(usd, gbp, "3", snapshot_id=first.snapshot_id)
    second = (
        replace(second, snapshot_id=builder.next_id())
        if mismatch == "snapshot"
        else replace(second, observed_at=Instant.parse("2025-12-30T00:00:00Z"))
    )
    with pytest.raises(DomainError):
        convert_xray_money(metric("1"), gbp, legs=(first, second))


def test_new_reporting_currency_retains_broker_original_saved_value_and_quote() -> None:
    from trading212_analytics.xray import convert_xray_money, verify_xray_result
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR

    builder = Builder()
    broker = builder.broker_position()
    position = builder.positions[0]
    gbp = CurrencyCode("GBP")
    leg = builder.fx_leg(EUR, gbp, "0.75")
    builder.reporting_currency = gbp
    builder.licensed_fx.append(
        d.XrayLicensedFx(position.root.key, position.reporting_value, gbp, (leg,))
    )
    builder.positions[0] = replace(
        position,
        reporting_value=convert_xray_money(position.reporting_value, gbp, legs=(leg,)),
        fx_refs=(*position.fx_refs, leg.source_reference_id),
    )
    builder.identity(uid(10), uid(110))
    value = builder.finish()
    result = calculate_xray(value)
    verify_xray_result(value, result)
    assert value.positions[0].original_value.value is not None
    assert value.positions[0].original_value.value.amount == Decimal("62.50")
    assert value.licensed_fx[0].input_value.value is not None
    assert value.licensed_fx[0].input_value.value.amount == Decimal("50")
    assert broker.rate == Decimal("0.8")
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("37.5")
    with pytest.raises(DomainError):
        calculate_xray(replace(value, broker_fx=(replace(broker, rate=Decimal("0.9")),)))


def test_missing_new_fx_preserves_saved_broker_basis_instead_of_zero_or_no_audit() -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.values import CurrencyCode

    builder = Builder()
    broker = builder.broker_position()
    position = builder.positions[0]
    gbp = CurrencyCode("GBP")
    builder.reporting_currency = gbp
    builder.licensed_fx.append(
        d.XrayLicensedFx(position.root.key, position.reporting_value, gbp, ())
    )
    builder.positions[0] = replace(
        position, reporting_value=convert_xray_money(position.reporting_value, gbp)
    )
    value = builder.finish()
    result = calculate_xray(value)
    assert result.portfolio_summary.total.value is None
    assert value.positions[0].reporting_value.reason is d.XrayReason.MISSING_FX
    with pytest.raises(DomainError):
        calculate_xray(replace(value, broker_fx=(replace(broker, rate=Decimal("0.9")),)))


def test_reconciliation_builder_preserves_separate_missing_declared_and_root_totals() -> None:
    from trading212_analytics.xray import build_xray_reconciliation

    from .xray_factories import metric

    builder = Builder()
    row = builder.position(uid(10), "5")
    reconciliation = build_xray_reconciliation((row,), (), metric(None))
    assert reconciliation.declared_total.value is None
    assert reconciliation.root_total.value is not None
    assert reconciliation.root_total.value.amount == Decimal("5")
    assert reconciliation.difference.value is None
    value = builder.finish()
    missing_total = metric(None)
    result = calculate_xray(
        replace(value, portfolio_total=missing_total, reconciliation=reconciliation)
    )
    assert result.reconciliation == reconciliation
    missing_root = replace(row, reporting_value=metric(None, row.valuation_refs))
    incomplete = build_xray_reconciliation((missing_root,), (), metric("5"))
    assert incomplete.declared_total.value is not None
    assert incomplete.root_total.value is None and incomplete.difference.value is None


def test_reconciliation_builder_reports_exact_difference_with_actual_saved_provenance() -> None:
    from trading212_analytics.xray import build_xray_reconciliation

    from .xray_factories import metric

    builder = Builder()
    row = builder.position(uid(10), "5.000000000000000001")
    total = metric("5")
    reconciliation = build_xray_reconciliation((row,), (), total)
    assert reconciliation.difference.value is not None
    assert reconciliation.difference.value.amount == Decimal("-0.000000000000000001")
    assert (
        reconciliation.difference.source_reference_ids == row.reporting_value.source_reference_ids
    )
    result = calculate_xray(
        replace(builder.finish(), portfolio_total=total, reconciliation=reconciliation)
    )
    assert any(warning.code is d.XrayWarningCode.UNRECONCILED_VALUE for warning in result.warnings)


def test_licensed_fx_and_reconciliation_use_fresh_decimal_context() -> None:
    from decimal import ROUND_UP, Inexact, localcontext

    from trading212_analytics.xray import build_xray_reconciliation, convert_xray_money
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR, metric

    builder = Builder()
    row = builder.position(uid(10), "99999999999999999999.000000000000000001")
    usd = CurrencyCode("USD")
    leg = builder.fx_leg(usd, EUR, "3", inverse=True)
    with localcontext() as context:
        context.prec, context.rounding = 2, ROUND_UP
        context.flags[Inexact] = True
        before = (context.prec, context.rounding, dict(context.flags), dict(context.traps))
        converted = convert_xray_money(metric("1"), usd, legs=(leg,))
        reconciliation = build_xray_reconciliation((row,), (), row.reporting_value)
        assert converted.value is not None and converted.value.amount == Decimal(
            "0.333333333333333333"
        )
        assert (
            reconciliation.difference.value is not None
            and reconciliation.difference.value.amount == Decimal("0")
        )
        assert (context.prec, context.rounding, dict(context.flags), dict(context.traps)) == before


def test_overlap_common_count_is_retained_without_recomputing_metric_projection() -> None:
    from trading212_analytics.xray import calculate_common_entities, calculate_overlap_pairs
    from trading212_domain.xray_result import CanonicalFundPair

    result = calculate_xray(fixture())
    pair = CanonicalFundPair(uid(20), uid(30))
    retained = calculate_overlap_pairs(result, (uid(20), uid(30)))[0]
    common = calculate_common_entities(result, pair)
    assert retained.common_entity_count == len(common.entities) == 2


@pytest.mark.parametrize("state", ("missing", "unsupported", "disputed"))
def test_selected_licensed_fx_gap_preserves_typed_reference_and_never_converts(state: str) -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.sources import ObservationState
    from trading212_domain.values import CurrencyCode

    from .xray_factories import EUR

    builder = Builder()
    position = builder.position(uid(10), "250")
    usd = CurrencyCode("USD")
    leg = replace(builder.fx_leg(EUR, usd, "1.2"), rate=None, state=ObservationState(state))
    conversion = d.XrayLicensedFx(position.root.key, position.reporting_value, usd, (leg,))
    builder.licensed_fx.append(conversion)
    builder.reporting_currency = usd
    builder.positions[0] = replace(
        position,
        reporting_value=convert_xray_money(position.reporting_value, usd, legs=(leg,)),
        fx_refs=(leg.source_reference_id,),
    )
    value = builder.finish()
    result = calculate_xray(value)
    assert result.portfolio_summary.total.value is None
    assert result.direct_positions[0].reporting_value.reason is d.XrayReason.MISSING_FX
    assert any(
        use.source_reference_id == leg.source_reference_id for use in result.typed_source_uses
    )
    assert any(
        warning.code is d.XrayWarningCode.PARTIAL_SOURCE
        and leg.source_reference_id in warning.source_reference_ids
        for warning in result.warnings
    )


def test_actual_licensed_fx_coverage_gap_preserves_broker_basis_and_replay_provenance() -> None:
    from trading212_analytics.xray import convert_xray_money
    from trading212_domain.sources import ObservationState
    from trading212_domain.values import CurrencyCode
    from trading212_domain.xray_codec import decode_xray_input

    from .xray_factories import EUR

    builder = Builder()
    broker = builder.broker_position()
    position = builder.positions[0]
    gbp = CurrencyCode("GBP")
    observation = builder.fx_leg(EUR, gbp, "0.75")
    gap_id = builder.next_id()
    leg = replace(
        observation,
        observation_id=None,
        coverage_gap_id=gap_id,
        rate=None,
        state=ObservationState.MISSING,
    )
    dependency_index = next(
        index
        for index, dependency in enumerate(builder.dependencies)
        if dependency.id == leg.source_reference_id
    )
    dependency = builder.dependencies[dependency_index]
    builder.dependencies[dependency_index] = replace(
        dependency,
        subject_id=gap_id,
        reference=d.XrayPhysicalReference(
            d.XrayReferenceKind.FX_COVERAGE_GAP, gap_id, leg.snapshot_id
        ),
    )
    builder.reporting_currency = gbp
    builder.licensed_fx.append(
        d.XrayLicensedFx(position.root.key, position.reporting_value, gbp, (leg,))
    )
    builder.positions[0] = replace(
        position,
        reporting_value=convert_xray_money(position.reporting_value, gbp, legs=(leg,)),
        fx_refs=(*position.fx_refs, leg.source_reference_id),
    )
    builder.identity(uid(10), uid(110))
    value = builder.finish()
    replayed = decode_xray_input(encode_xray_input(value))
    result = calculate_xray(replayed)
    assert encode_xray_input(replayed) == encode_xray_input(value)
    assert replayed.positions[0].original_value == position.original_value
    assert replayed.licensed_fx[0].input_value == position.reporting_value
    assert replayed.broker_fx == (broker,)
    retained_leg = replayed.licensed_fx[0].legs[0]
    assert retained_leg.observation_id is None and retained_leg.coverage_gap_id == gap_id
    assert result.portfolio_summary.total.value is None
    direct = result.direct_positions[0]
    assert direct.reporting_value.value is None
    assert direct.reporting_value.reason is d.XrayReason.MISSING_FX
    assert leg.source_reference_id in direct.reporting_value.source_reference_ids
    uses = [
        use
        for use in result.typed_source_uses
        if use.source_reference_id == leg.source_reference_id
    ]
    assert uses and all(use.subject_id == gap_id for use in uses)
    assert any(
        warning.code is d.XrayWarningCode.PARTIAL_SOURCE
        and leg.source_reference_id in warning.source_reference_ids
        for warning in result.warnings
    )
    assert encode_xray_result(result) == encode_xray_result(calculate_xray(value))
    verify_xray_result(replayed, result)
    forged_observation = replace(retained_leg, observation_id=gap_id, coverage_gap_id=None)
    with pytest.raises(DomainError):
        replace(
            replayed,
            licensed_fx=(replace(replayed.licensed_fx[0], legs=(forged_observation,)),),
        )


def test_broker_fx_freshness_is_derived_for_paths_and_direct_money_from_pinned_policy() -> None:
    from trading212_domain.enums import QualityState

    builder = Builder()
    builder.broker_position()
    value = builder.finish()
    policy = replace(
        value.policy,
        freshness_policy=replace(
            value.policy.freshness_policy,
            stale_after_seconds=1,
            evaluation_basis="source_cutoff_at",
        ),
    )
    result = calculate_xray(replace(value, policy=policy))
    assert result.direct_positions[0].reporting_value.quality is QualityState.STALE
    assert result.direct_positions[0].absolute_weight.quality is QualityState.STALE
    assert any(warning.code is d.XrayWarningCode.STALE_SOURCE for warning in result.warnings)


@pytest.mark.parametrize("selected_evidence", ("conflicting", "ambiguous", "gap", "failed"))
def test_constituent_entity_assertion_cannot_override_unusable_selected_identity(
    selected_evidence: str,
) -> None:
    from trading212_domain.enums import QualityState

    builder = Builder()
    builder.position(uid(20), "100")
    source = builder.fund(uid(20), ((uid(10), "1"),))
    builder.constituents[0] = replace(
        source, holdings=(replace(source.holdings[0], entity_id=uid(110)),)
    )
    builder.identity(uid(10), uid(111) if selected_evidence == "conflicting" else uid(110))
    if selected_evidence == "ambiguous":
        builder.identity(uid(10), uid(111))
    elif selected_evidence == "gap":
        item = builder.entities[0]
        builder.entities[0] = replace(
            item, evidence=replace(item.evidence, state=d.XraySourceState.GAP)
        )
    elif selected_evidence == "failed":
        item = builder.entities[0]
        builder.entities[0] = replace(
            item, evidence=replace(item.evidence, quality=QualityState.FAILED)
        )
    value = builder.finish()
    result = calculate_xray(value)
    path = result.terminal_paths[0]
    assert path.entity_id is None
    assert path.unresolved_reason is (
        d.XrayReason.MISSING_SOURCE
        if selected_evidence == "failed"
        else d.XrayReason.AMBIGUOUS_IDENTITY
    )
    assert path.reporting_value.value is not None
    assert path.reporting_value.value.amount == Decimal("100")
    assert path.relative_coefficient == Decimal("1e72")
    assert result.portfolio_summary.company_known_weight.value == Decimal("0")
    assert result.portfolio_summary.unresolved_weight.value == Decimal("1")
    assert {item.evidence.id for item in builder.entities}.issubset(path.identity_decision_ids)
    verify_xray_result(value, result)


@pytest.mark.parametrize("listing_proof", (False, True))
def test_constituent_entity_assertion_remains_usable_when_company_mapping_is_absent(
    listing_proof: bool,
) -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    source = builder.fund(uid(20), ((uid(10), "1"),))
    builder.constituents[0] = replace(
        source,
        holdings=(
            replace(
                source.holdings[0],
                entity_id=uid(110),
                listing_id=uid(501) if listing_proof else None,
            ),
        ),
    )
    if listing_proof:
        evidence = builder.evidence(
            d.XrayDependencyKind.RELATIONSHIP, d.XraySubjectKind.LISTING, uid(501)
        )
        builder.relationships.append(
            d.XrayRelationshipVersion(
                uid(10),
                None,
                None,
                d.XrayRelationshipKind.LISTING_OF,
                None,
                evidence,
                listing_id=uid(501),
            )
        )
    value = builder.finish()
    result = calculate_xray(value)
    path = result.terminal_paths[0]
    assert path.entity_id == uid(110) and path.unresolved_reason is None
    assert path.reporting_value.value is not None and path.reporting_value.value.amount == Decimal(
        "100"
    )
    assert path.relative_coefficient == Decimal("1e72")
    assert result.portfolio_summary.company_known_weight.value == Decimal("1")
    assert result.portfolio_summary.unresolved_weight.value == Decimal("0")
    verify_xray_result(value, result)


def test_quality_coverage_counts_original_valuation_roots_including_zero_cash() -> None:
    builder = Builder()
    builder.position(uid(10), "100")
    builder.position(uid(11), "0")
    builder.cash_row("0")
    result = calculate_xray(builder.finish())
    coverage = result.portfolio_summary.quality_coverage
    assert (coverage.root_count, coverage.valued_root_count) == (3, 3)
    assert coverage.direct_portfolio_value.value is not None
    assert coverage.direct_portfolio_value.value.amount == Decimal("100")
    assert coverage.direct_portfolio_weight.value == Decimal("1")
    assert coverage.inferred_mapping_count == 0
    assert (
        coverage.inferred_value.value is not None
        and coverage.inferred_value.value.amount == Decimal("0")
    )
    assert coverage.stale_value.value is not None and coverage.stale_value.value.amount == Decimal(
        "0"
    )


def test_quality_coverage_missing_root_keeps_known_value_and_unavailable_weight_separate() -> None:
    builder = Builder()
    builder.position(uid(10), "100")
    builder.position(uid(11), None)
    result = calculate_xray(builder.finish())
    coverage = result.portfolio_summary.quality_coverage
    assert (coverage.root_count, coverage.valued_root_count) == (2, 1)
    assert coverage.direct_portfolio_value.value is not None
    assert coverage.direct_portfolio_value.value.amount == Decimal("100")
    assert coverage.direct_portfolio_value.bound is d.XrayBound.LOWER_BOUND
    assert coverage.direct_portfolio_weight.value is None
    assert coverage.direct_portfolio_weight.reason is d.XrayReason.INCOMPLETE_VALUATION


@pytest.mark.parametrize("source_quality", ("fresh", "estimated", "partial"))
def test_stale_value_uses_actual_evidence_union_even_when_quality_rank_masks_stale(
    source_quality: str,
) -> None:
    from datetime import timedelta

    from trading212_domain.enums import QualityState

    value = fixture()
    source = value.constituent_candidates[0]
    changed = replace(
        source,
        evidence=replace(
            source.evidence,
            effective_at=Instant(AT.value - timedelta(days=1)),
            quality=QualityState(source_quality),
        ),
    )
    policy = replace(
        value.policy,
        freshness_policy=replace(value.policy.freshness_policy, stale_after_seconds=3600),
    )
    value = replace(
        value, policy=policy, constituent_candidates=(changed, *value.constituent_candidates[1:])
    )
    result = calculate_xray(value)
    coverage = result.portfolio_summary.quality_coverage
    assert coverage.stale_value.value is not None
    assert coverage.stale_value.value.amount == Decimal("500")
    assert coverage.stale_weight.value == Decimal("0.5")
    assert coverage.inferred_mapping_count == 0
    assert (
        coverage.inferred_value.value is not None
        and coverage.inferred_value.value.amount == Decimal("0")
    )
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("1000")
    verify_xray_result(value, result)


def test_inferred_value_counts_real_estimated_identity_once_per_economic_path() -> None:
    from trading212_domain.enums import QualityState

    value = fixture()
    identity = value.entity_evidence[0]
    changed = replace(identity, evidence=replace(identity.evidence, quality=QualityState.ESTIMATED))
    value = replace(value, entity_evidence=(changed, *value.entity_evidence[1:]))
    result = calculate_xray(value)
    coverage = result.portfolio_summary.quality_coverage
    assert coverage.inferred_mapping_count == 1
    assert coverage.inferred_value.value is not None
    assert coverage.inferred_value.value.amount == Decimal("560")
    assert coverage.inferred_weight.value == Decimal("0.56")
    assert coverage.stale_value.value is not None and coverage.stale_value.value.amount == Decimal(
        "0"
    )
    assert result.portfolio_summary.company_known_weight.value == Decimal("0.95")
    verify_xray_result(value, result)


def test_inferred_and_stale_measures_can_overlap_without_changing_economic_mass() -> None:
    from datetime import timedelta

    from trading212_domain.enums import QualityState

    value = fixture()
    identity = value.entity_evidence[0]
    changed = replace(
        identity,
        evidence=replace(
            identity.evidence,
            quality=QualityState.ESTIMATED,
            effective_at=Instant(AT.value - timedelta(days=1)),
        ),
    )
    policy = replace(
        value.policy,
        freshness_policy=replace(value.policy.freshness_policy, stale_after_seconds=3600),
    )
    value = replace(value, policy=policy, entity_evidence=(changed, *value.entity_evidence[1:]))
    result = calculate_xray(value)
    coverage = result.portfolio_summary.quality_coverage
    assert coverage.inferred_mapping_count == 1
    assert coverage.inferred_value.value is not None and coverage.stale_value.value is not None
    assert (
        coverage.inferred_value.value.amount == coverage.stale_value.value.amount == Decimal("560")
    )
    assert coverage.inferred_weight.value == coverage.stale_weight.value == Decimal("0.56")
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == Decimal("1000")
    assert result.portfolio_summary.unresolved_weight.value == Decimal("0.05")


def test_broker_fx_stale_value_is_retained_without_licensed_fx_or_identity_rows() -> None:
    builder = Builder()
    builder.broker_position()
    value = builder.finish()
    policy = replace(
        value.policy,
        freshness_policy=replace(
            value.policy.freshness_policy,
            stale_after_seconds=1,
            evaluation_basis="source_cutoff_at",
        ),
    )
    result = calculate_xray(replace(value, policy=policy))
    coverage = result.portfolio_summary.quality_coverage
    assert coverage.stale_value.value is not None and coverage.stale_value.value.amount == Decimal(
        "50"
    )
    assert coverage.stale_weight.value == Decimal("1")
    assert coverage.inferred_mapping_count == 0
