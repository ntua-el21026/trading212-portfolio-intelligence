"""Closed codec and bounded metadata regressions independent of transport parsing."""

from dataclasses import replace
from decimal import Decimal

import pytest
from trading212_domain.aggregation_codec import (
    aggregation_holdings_input_from_json,
    aggregation_record_bytes,
    aggregation_record_digest,
)
from trading212_domain.errors import DomainError

from tests.unit.analytics.test_aggregation import holdings


def test_complete_input_round_trip_and_reject_other_digest() -> None:
    source = holdings()
    encoded = aggregation_record_bytes(source)
    assert (
        aggregation_holdings_input_from_json(
            encoded, expected_digest=aggregation_record_digest(source)
        )
        == source
    )
    with pytest.raises(DomainError):
        aggregation_holdings_input_from_json(encoded, expected_digest="0" * 64)


@pytest.mark.parametrize(
    "bad",
    (b'{"canary_secret":"nope"}', b'{"owner_id":"one","owner_id":"two"}', b"[" * 17 + b"]" * 17),
)
def test_unknown_duplicate_and_deep_data_has_sanitized_error(bad: bytes) -> None:
    with pytest.raises(DomainError) as raised:
        aggregation_holdings_input_from_json(bad)
    assert "canary_secret" not in str(raised.value)
    assert "nope" not in str(raised.value)


def test_financial_float_nan_and_noncanonical_json_are_rejected() -> None:
    source = holdings()
    with pytest.raises(DomainError):
        replace(source.components[0], native_value=Decimal("NaN"))
    encoded = aggregation_record_bytes(source)
    with pytest.raises(DomainError):
        aggregation_holdings_input_from_json(b" " + encoded)
    with pytest.raises(DomainError):
        aggregation_holdings_input_from_json(
            encoded.replace(b'"native_value":"1"', b'"native_value":1.0')
        )
