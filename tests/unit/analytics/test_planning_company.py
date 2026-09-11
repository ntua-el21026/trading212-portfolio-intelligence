"""Exact company projections, immutable input binding and retained physical proof."""

from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.planning import calculate_contribution_plan, calculate_drift
from trading212_analytics.planning_company import (
    project_company_weights,
    unselected_company_projection,
)
from trading212_analytics.xray import calculate_xray, company_exposure_basis
from trading212_domain import CurrencyCode, Instant
from trading212_domain.errors import DomainError
from trading212_domain.planning import DriftBasis
from trading212_domain.planning_company import PlanningCompanyBasisError, company_row_view
from trading212_domain.planning_serialization import (
    drift_calculation_from_json,
    planning_input_from_json,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.xray import (
    XrayAvailability,
    XrayDimension,
    XrayReferenceKind,
    XraySubjectKind,
)

from .planning_company_factories import company_inputs, digest, project

pytestmark = pytest.mark.unit


def test_full_absolute_company_bucket_repeats_nonadditively_without_mutating_drift() -> None:
    planning, value = company_inputs()
    calculation = calculate_drift(planning)
    before = canonical_json(calculation)
    input_before = canonical_json(planning)
    plan_before = canonical_json(calculate_contribution_plan(planning))
    result = calculate_xray(value)
    projection = project(planning, value, result)
    cells = {row.row_key: row for row in projection.weights}
    full_bucket = next(
        row
        for row in company_exposure_basis(result).exposures
        if row.bucket_key == str(UUID(int=110))
    )
    # Independent fixture arithmetic: (100 + 100 + 500*.6 + 300*.2) / 1000.
    assert full_bucket.absolute_weight.value == Decimal("0.56")
    assert cells["target/A"].metric == cells["target/B"].metric == full_bucket.absolute_weight
    assert cells["target/A"].semantics == "full_portfolio_company_non_additive"
    assert all(
        cells[key].metric is None and cells[key].reason == "company_scope_not_applicable"
        for key in ("target/G", "target/C", "target/D")
    )
    assert all(
        row.drift_reason == "effective_exposure_target_unavailable" for row in projection.weights
    )
    view = company_row_view(
        next(row for row in calculation.rows if row.key == "target/A"), cells["target/A"]
    )
    assert view.effective_weight == Decimal("0.56")
    assert (
        view.signed_drift
        == next(row for row in calculation.rows if row.key == view.key).signed_drift
    )
    assert projection.binding is not None
    assert projection.binding.company_partition.dimension is XrayDimension.COMPANY
    assert projection.content_digest not in (None, digest(calculation))
    assert canonical_json(calculation) == before
    assert canonical_json(planning) == input_before
    assert canonical_json(drift_calculation_from_json(before)) == before
    assert canonical_json(planning_input_from_json(input_before)) == input_before
    assert canonical_json(calculate_contribution_plan(planning)) == plan_before


def test_tiny_authoritative_positive_zero_keeps_all_canonical_flags() -> None:
    planning, value = company_inputs(tiny=True)
    result = calculate_xray(value)
    bucket = next(
        row
        for row in company_exposure_basis(result).exposures
        if row.bucket_key == str(UUID(int=110))
    )
    cell = next(
        row for row in project(planning, value, result).weights if row.row_key == "target/A"
    )
    assert cell.metric == bucket.absolute_weight
    assert cell.metric is not None and cell.metric.value == Decimal(0)
    assert cell.metric.positive_below_quantum
    assert cell.metric.availability is XrayAvailability.AVAILABLE
    assert (
        company_row_view(
            next(row for row in calculate_drift(planning).rows if row.key == cell.row_key), cell
        ).effective_weight_reason
        == "positive_below_quantum"
    )


@pytest.mark.parametrize(
    "identity,reason",
    [("missing", "company_identity_unavailable"), ("conflict", "company_identity_conflict")],
)
def test_real_identity_selection_failure_is_never_fabricated_zero(
    identity: str, reason: str
) -> None:
    planning, value = company_inputs(identity=identity)
    cell = next(row for row in project(planning, value).weights if row.row_key == "target/A")
    assert cell.metric is None and cell.entity_id is None
    assert cell.reason == reason


@pytest.mark.parametrize("basis", [DriftBasis.DIRECT, DriftBasis.EFFECTIVE])
def test_unselected_basis_preserves_every_legacy_drift_field(basis: DriftBasis) -> None:
    planning, _ = company_inputs()
    calculation = calculate_drift(planning, basis=basis)
    before = canonical_json(calculation)
    projection = unselected_company_projection(calculation.rows)
    cells = {cell.row_key: cell for cell in projection.weights}
    assert {row.kind for row in calculation.rows} >= {"group", "holding", "cash"}
    for row in calculation.rows:
        view = company_row_view(row, cells[row.key])
        legacy = asdict(view)
        company = legacy.pop("company")
        assert company == asdict(cells[row.key])
        assert legacy == asdict(row)
    assert canonical_json(calculation) == before


def test_unselected_basis_has_no_projection_identity_and_no_effective_drift() -> None:
    planning, _ = company_inputs()
    calculation = calculate_drift(planning)
    projection = unselected_company_projection(calculation.rows)
    assert projection.binding is None and projection.content_digest is None
    assert all(row.metric is None for row in projection.weights)
    assert (
        next(row for row in projection.weights if row.row_key == "target/A").reason
        == "company_basis_not_selected"
    )
    assert all(
        row.drift_reason == "effective_exposure_target_unavailable" for row in projection.weights
    )


@pytest.mark.parametrize(
    "field", ["account_id", "snapshot_id", "reporting_currency", "valuation_at", "source_cutoff_at"]
)
def test_mismatched_saved_pins_fail_closed(field: str) -> None:
    planning, value = company_inputs()
    result = calculate_xray(value)
    # Deliberately corrupt one result pin from the real producer. Keep the valid
    # input and financial values intact so the projection guard is exercised,
    # rather than failing while constructing an inconsistent ValuationInput.
    if field == "account_id":
        result = replace(result, account_id=UUID(int=999))
    elif field == "snapshot_id":
        result = replace(result, snapshot_id=UUID(int=999))
    elif field == "reporting_currency":
        result = replace(result, reporting_currency=CurrencyCode("USD"))
    elif field == "valuation_at":
        result = replace(
            result, valuation_at=Instant(result.valuation_at.value + timedelta(seconds=1))
        )
    else:
        assert field == "source_cutoff_at"
        result = replace(
            result, source_cutoff_at=Instant(result.source_cutoff_at.value - timedelta(seconds=1))
        )
    with pytest.raises(PlanningCompanyBasisError, match="company_pin_mismatch"):
        project(planning, value, result)


def test_correct_scalar_total_cannot_replace_saved_calculation_source_proof() -> None:
    planning, value = company_inputs()
    planning = replace(
        planning,
        valuation=replace(
            planning.valuation,
            sources=tuple(
                replace(source, content_digest="e" * 64)
                if source.kind == "calculation_run"
                else source
                for source in planning.valuation.sources
            ),
        ),
    )
    with pytest.raises(PlanningCompanyBasisError, match="valuation_basis_mismatch"):
        project(planning, value)


def test_production_shaped_calculation_and_snapshot_proofs_have_distinct_digests() -> None:
    planning, value = company_inputs()
    calculation = next(
        source
        for source in value.source_dependencies
        if source.reference.kind is XrayReferenceKind.CALCULATION_RUN
    )
    snapshot = next(
        source
        for source in value.source_dependencies
        if source.reference.kind is XrayReferenceKind.PORTFOLIO_SNAPSHOT
    )
    assert calculation.content_digest == digest(("b" * 64, "c" * 64))
    assert snapshot.content_digest == digest((str(value.snapshot_id), "c" * 64))
    assert snapshot.content_digest == value.snapshot_digest != calculation.content_digest
    assert snapshot.reference.parent_record_id == calculation.reference.record_id
    assert project(planning, value).binding is not None


@pytest.mark.parametrize(
    "kind,field",
    [
        (XrayReferenceKind.CALCULATION_RUN, "record_id"),
        (XrayReferenceKind.CALCULATION_RUN, "parent_record_id"),
        (XrayReferenceKind.CALCULATION_RUN, "subject_id"),
        (XrayReferenceKind.CALCULATION_RUN, "subject_kind"),
        (XrayReferenceKind.PORTFOLIO_SNAPSHOT, "parent_record_id"),
        (XrayReferenceKind.PORTFOLIO_SNAPSHOT, "content_digest"),
        (XrayReferenceKind.PORTFOLIO_SNAPSHOT, "subject_id"),
        (XrayReferenceKind.PORTFOLIO_SNAPSHOT, "subject_kind"),
    ],
)
def test_mismatched_valuation_proof_pair_fails_closed(kind: XrayReferenceKind, field: str) -> None:
    planning, value = company_inputs()
    source = next(row for row in value.source_dependencies if row.reference.kind is kind)
    if field == "record_id":
        changed = replace(source, reference=replace(source.reference, record_id=UUID(int=999)))
    elif field == "parent_record_id":
        changed = replace(
            source, reference=replace(source.reference, parent_record_id=UUID(int=999))
        )
    elif field == "content_digest":
        changed = replace(source, content_digest="e" * 64)
    elif field == "subject_id":
        changed = replace(source, subject_id=UUID(int=999))
    else:
        assert field == "subject_kind"
        changed = replace(source, subject_kind=XraySubjectKind.INSTRUMENT)
    changed_value = replace(
        value,
        source_dependencies=tuple(
            changed if row.id == source.id else row for row in value.source_dependencies
        ),
    )
    # Recompute the real result so the input hash remains valid: rejection must
    # come from the retained proof pairing, not a stale result digest or scalar.
    result = calculate_xray(changed_value)
    assert changed_value.positions == value.positions
    assert changed_value.portfolio_total == value.portfolio_total
    with pytest.raises(PlanningCompanyBasisError, match="valuation_basis_mismatch"):
        project(planning, changed_value, result)


def test_wrong_snapshot_physical_id_is_rejected_by_dependency_admission() -> None:
    _, value = company_inputs()
    source = next(
        row
        for row in value.source_dependencies
        if row.reference.kind is XrayReferenceKind.PORTFOLIO_SNAPSHOT
    )
    # This malformed ID is rejected before a typed input can reach projection.
    with pytest.raises(DomainError, match="Invalid closed X-ray value or invariant"):
        replace(source, reference=replace(source.reference, record_id=UUID(int=999)))


def test_result_input_and_planning_digest_mismatch_fail_closed() -> None:
    planning, value = company_inputs()
    result = replace(calculate_xray(value), input_digest="f" * 64)
    with pytest.raises(PlanningCompanyBasisError, match="company_pin_mismatch"):
        project(planning, value, result)
    with pytest.raises(PlanningCompanyBasisError, match="company_result_invalid"):
        project_company_weights(
            planning,
            calculate_drift(planning),
            planning_run_id=UUID(int=9100),
            planning_content_digest="f" * 64,
            xray_run_id=UUID(int=9101),
            xray_input_id=UUID(int=9102),
            value=value,
            result=calculate_xray(value),
        )


def test_explicit_run_changes_identity_without_changing_financial_metrics() -> None:
    planning, value = company_inputs()
    result = calculate_xray(value)
    first, second = project(planning, value, result), project(planning, value, result, run=9201)
    assert first.weights == second.weights
    assert first.content_digest != second.content_digest
