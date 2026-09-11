"""Company basis validation treats source-reference inventory order as nonsemantic."""

from dataclasses import replace
from hashlib import sha256
from uuid import UUID

import pytest
from trading212_analytics.planning import calculate_drift
from trading212_analytics.planning_company import project_company_weights
from trading212_analytics.xray import build_xray_reconciliation, calculate_xray
from trading212_domain.planning_company import PlanningCompanyBasisError
from trading212_domain.xray import XrayReferenceKind
from trading212_domain.xray_codec import (
    decode_xray_input,
    decode_xray_result,
    encode_xray_input,
    encode_xray_result,
)

from tests.unit.analytics.planning_company_factories import company_inputs, digest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("descending", (False, True), ids=("ascending", "descending"))
def test_separately_decoded_input_and_result_keep_equivalent_reconciliation(
    descending: bool,
) -> None:
    planning, value = company_inputs()
    references = tuple(
        sorted(
            (
                source.id
                for source in value.source_dependencies
                if source.reference.kind
                in (
                    XrayReferenceKind.CALCULATION_RUN,
                    XrayReferenceKind.PORTFOLIO_SNAPSHOT,
                )
            ),
            key=str,
            reverse=descending,
        )
    )
    assert len(references) == 2
    total = replace(value.portfolio_total, source_reference_ids=references)
    reconciliation = build_xray_reconciliation(
        value.positions,
        value.cash,
        total,
        source_reference_ids=value.reconciliation.source_reference_ids,
    )
    value = replace(
        value,
        portfolio_total=total,
        reconciliation=replace(
            reconciliation,
            root_total=replace(
                reconciliation.root_total,
                source_reference_ids=tuple(
                    sorted(
                        reconciliation.root_total.source_reference_ids,
                        key=str,
                        reverse=descending,
                    )
                ),
            ),
            difference=replace(
                reconciliation.difference,
                source_reference_ids=tuple(
                    sorted(
                        reconciliation.difference.source_reference_ids,
                        key=str,
                        reverse=descending,
                    )
                ),
            ),
        ),
    )
    calculation = calculate_drift(planning)
    result = calculate_xray(value)
    input_bytes = encode_xray_input(value)
    result_bytes = encode_xray_result(result)
    loaded_input = decode_xray_input(input_bytes)
    loaded_result = decode_xray_result(result_bytes)
    assert encode_xray_input(loaded_input) == input_bytes
    assert encode_xray_result(loaded_result) == result_bytes
    assert loaded_result.input_digest == sha256(input_bytes).hexdigest()
    # The outer tuple retains its genuine reconciliation dependencies (empty here).
    assert loaded_input.reconciliation.source_reference_ids == ()
    assert loaded_result.reconciliation.source_reference_ids == ()
    # Force the exact serialization seam independently of random source UUID order.
    assert loaded_input.reconciliation.declared_total.source_reference_ids == tuple(
        sorted(references, key=str)
    )
    assert loaded_result.reconciliation.declared_total.source_reference_ids == references
    if descending:
        assert loaded_input.reconciliation != loaded_result.reconciliation
    before = (input_bytes, result_bytes)
    projection = project_company_weights(
        planning,
        calculation,
        planning_run_id=UUID(int=9100),
        planning_content_digest=digest(calculation),
        xray_run_id=UUID(int=9101),
        xray_input_id=UUID(int=9102),
        value=loaded_input,
        result=loaded_result,
    )
    assert projection.binding is not None
    assert projection.binding.planning_content_digest == digest(calculation)
    assert projection.binding.xray_input_digest == sha256(input_bytes).hexdigest()
    assert (encode_xray_input(loaded_input), encode_xray_result(loaded_result)) == before
    # Ordering equivalence must never erase missing proof membership.
    reconciliation = loaded_result.reconciliation
    rejected = []
    for field, metric in (
        ("declared_total", reconciliation.declared_total),
        ("root_total", reconciliation.root_total),
        ("difference", reconciliation.difference),
    ):
        assert len(metric.source_reference_ids) >= 2
        for bad_ids in (
            metric.source_reference_ids[:1],
            (*metric.source_reference_ids, metric.source_reference_ids[0]),
        ):
            bad_metric = replace(metric, source_reference_ids=bad_ids)
            rejected.append(
                replace(
                    reconciliation,
                    declared_total=bad_metric
                    if field == "declared_total"
                    else reconciliation.declared_total,
                    root_total=bad_metric if field == "root_total" else reconciliation.root_total,
                    difference=bad_metric if field == "difference" else reconciliation.difference,
                )
            )
    for bad_reconciliation in rejected:
        bad = replace(loaded_result, reconciliation=bad_reconciliation)
        with pytest.raises(PlanningCompanyBasisError, match="valuation_basis_mismatch"):
            project_company_weights(
                planning,
                calculation,
                planning_run_id=UUID(int=9100),
                planning_content_digest=digest(calculation),
                xray_run_id=UUID(int=9101),
                xray_input_id=UUID(int=9102),
                value=loaded_input,
                result=bad,
            )
