import json
import traceback
from dataclasses import replace

import pytest
from trading212_analytics.historical import calculate_performance, verify_historical_result
from trading212_domain import CurrencyCode, DomainError, Money
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import (
    historical_canonical_bytes,
    historical_input_from_json,
)

from tests.unit.analytics.historical_factories import fixture

pytestmark = pytest.mark.security


@pytest.mark.parametrize("location", ["unknown_key", "known_value", "duplicate_key"])
def test_untrusted_historical_document_never_reflects_canary_in_error_chain(location: str) -> None:
    marker = "_".join(("HISTORICAL", "PRIVATE", "CANARY"))
    raw = historical_canonical_bytes(fixture()).decode()
    if location == "unknown_key":
        raw = raw[:-1] + "," + json.dumps(marker) + ":" + json.dumps(marker) + "}"
    elif location == "known_value":
        raw = raw.replace('"quantity":"1"', '"quantity":' + json.dumps(marker))
    else:
        raw = raw[:-1] + ',"owner_id":' + json.dumps(marker) + "}"
    with pytest.raises(DomainError) as captured:
        historical_input_from_json(raw)
    assert marker not in str(captured.value)
    assert marker not in "".join(traceback.format_exception(captured.value))
    assert captured.value.__context__ is None and captured.value.__cause__ is None


def test_result_foreign_input_and_currency_cannot_pass_verifier() -> None:
    value = fixture()
    result = calculate_performance(value, options=r.PerformanceOptions())
    with pytest.raises(DomainError):
        verify_historical_result(
            value, replace(result, context=replace(result.context, input_digest="0" * 64))
        )
    assert result.summary.investment_gain.value is not None
    wrong = replace(
        result,
        summary=replace(
            result.summary,
            investment_gain=replace(
                result.summary.investment_gain,
                value=Money(result.summary.investment_gain.value.amount, CurrencyCode("USD")),
            ),
        ),
    )
    with pytest.raises(DomainError):
        verify_historical_result(value, wrong)


def test_result_cannot_relabel_frozen_method_or_change_point_currency() -> None:
    value = fixture()
    result = calculate_performance(value, options=r.PerformanceOptions())
    with pytest.raises(DomainError):
        verify_historical_result(
            value,
            replace(
                result,
                context=replace(
                    result.context, method=r.HistoricalMethod(name="income_v1", version="1.0.0")
                ),
            ),
        )
    point = result.points[0]
    assert point.portfolio_value.value is not None
    tampered = replace(
        point,
        portfolio_value=replace(
            point.portfolio_value,
            value=Money(point.portfolio_value.value.amount, CurrencyCode("USD")),
        ),
    )
    with pytest.raises(DomainError):
        verify_historical_result(value, replace(result, points=(tampered, *result.points[1:])))
