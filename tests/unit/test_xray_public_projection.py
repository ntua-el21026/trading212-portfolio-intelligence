"""Public previews preserve exact retained metrics and complete path proofs."""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError
from trading212_api_contracts import xray as wire
from trading212_application.xray_projection import xray_public_primitive
from trading212_domain.errors import DomainError
from trading212_domain.xray import XrayAvailability, XrayReason

from tests.unit.api.xray_factories import exposures, money, ratio


def test_large_metric_provenance_has_exact_omissions_without_mutating_financial_value() -> None:
    refs = tuple(UUID(int=i + 1) for i in range(100_000))
    original = money("99999999999999999999.999999999999999999", refs=refs)
    result = wire.XrayMoneyMetric.model_validate(xray_public_primitive(original))
    assert result.value is not None
    assert result.value.amount == "99999999999999999999.999999999999999999"
    assert result.value.currency == "EUR"
    assert len(result.source_reference_ids) == 64
    assert result.source_count == 100_000 and result.source_omitted_count == 99_936
    assert original.source_reference_ids == refs and len(original.source_reference_ids) == 100_000
    assert len(result.model_dump_json()) < 4096


def test_zero_unavailable_and_subquantum_positive_remain_distinct() -> None:
    zero = ratio()
    unavailable = replace(
        zero,
        value=None,
        reason=XrayReason.ZERO_DENOMINATOR,
        availability=XrayAvailability.UNAVAILABLE,
    )
    subquantum = replace(zero, positive_below_quantum=True)
    results = [
        wire.XrayRatioMetric.model_validate(xray_public_primitive(item))
        for item in (zero, unavailable, subquantum)
    ]
    assert [(item.value, item.availability, item.positive_below_quantum) for item in results] == [
        ("0", "available", False),
        (None, "unavailable", False),
        ("0", "available", True),
    ]


def test_wire_rejects_private_coefficients_and_inconsistent_metric_previews() -> None:
    payload = xray_public_primitive(ratio("0.123456789012345678"))
    for extra in (
        {"coefficient": "123"},
        {"source_omitted_count": 1},
        {"availability": "unavailable"},
    ):
        with pytest.raises(ValidationError):
            wire.XrayRatioMetric.model_validate({**payload, **extra})
    assert payload["value"] == "0.123456789012345678"


def test_complete_typed_application_view_serializes_without_internal_state() -> None:
    original = exposures()
    result = wire.XrayExposuresResponse.model_validate(xray_public_primitive(original))
    assert result.summary.total.value is not None and result.summary.total.value.amount == "100"
    assert result.context.method.numeric_policy == "xray_decimal256_exact_q18_v1"
    assert "coefficient" not in result.model_dump_json()


def test_public_serializer_rejects_binary_floats_and_nonstring_mapping_keys() -> None:
    for value in (0.1, {1: Decimal("0.1")}, b"binary"):
        with pytest.raises(DomainError):
            xray_public_primitive(value)
