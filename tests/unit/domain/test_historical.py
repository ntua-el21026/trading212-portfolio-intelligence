import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_domain import DomainError
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import (
    historical_canonical_bytes,
    historical_input_from_json,
)
from trading212_domain.historical_validation import validate_historical_input
from trading212_domain.serialization import to_primitive
from trading212_domain.sources import FxOperation

from tests.unit.analytics.historical_factories import fixture
from tests.unit.analytics.source_factories import uid

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("policy", [None, "explicit_comparison", "historical_assignment"])
def test_closed_nullable_union_roundtrip(policy: str | None) -> None:
    value = fixture()
    if policy == "explicit_comparison":
        value = replace(
            value,
            selection=replace(
                value.selection, grouping_policy="explicit_comparison", target_version_id=uid(100)
            ),
        )
    elif policy == "historical_assignment":
        value = replace(
            value,
            selection=replace(
                value.selection, grouping_policy="historical_assignment", target_version_id=uid(100)
            ),
        )
    assert historical_input_from_json(historical_canonical_bytes(value)) == value


@pytest.mark.parametrize(
    "number",
    [
        0.1,
        float("nan"),
        float("inf"),
        "NaN",
        "Infinity",
        "100000000000000000000",
        "0.0000000000000000001",
    ],
)
def test_wire_float_nonfinite_overflow_and_excess_scale_are_rejected(number: str | float) -> None:
    primitive = to_primitive(fixture())
    assert isinstance(primitive, dict)
    encoded = json.dumps(primitive).replace(
        '"quantity": "1"', '"quantity": ' + json.dumps(number), 1
    )
    with pytest.raises(DomainError):
        historical_input_from_json(encoded)


def test_cross_record_proof_cannot_be_a_fabricated_reconciled_flag() -> None:
    value = fixture()
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    anchor = value.opening.anchor
    line = replace(anchor.reconciliation.lines[0], residual=Decimal(1))
    forged = replace(
        value,
        opening=replace(
            value.opening,
            anchor=replace(anchor, reconciliation=replace(anchor.reconciliation, lines=(line,))),
        ),
    )
    with pytest.raises(DomainError, match="residual"):
        validate_historical_input(forged)


def test_dated_absence_proof_cannot_cover_future_economics() -> None:
    chunk = fixture().activity_coverage[0]
    with pytest.raises(DomainError, match="future"):
        replace(chunk, end_at=chunk.first_observed_at + timedelta(microseconds=1))


def test_optional_result_money_ratio_rejects_excess_scale_even_inside_union() -> None:
    with pytest.raises(DomainError):
        r.HistoricalConversionUse(
            conversion_key="exact",
            use_at=fixture().selection.window.start_at,
            base=fixture().selection.window.reporting_currency,
            quote=fixture().selection.window.reporting_currency,
            operation=FxOperation.IDENTITY,
            rate=Decimal("0.0000000000000000001"),
            leg_use_keys=(),
        )
