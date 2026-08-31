from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from trading212_provider.models import (
    AccountSummaryDTO,
    TransactionDTO,
    parse_rate_limit_headers,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/trading212"


def test_provider_money_is_decimal_and_additive_fields_are_retained() -> None:
    payload = json.loads(
        (FIXTURES / "account_summary.json").read_text(encoding="utf-8"),
        parse_float=Decimal,
    )
    payload["futureAdditiveField"] = "retained"
    account = AccountSummaryDTO.model_validate(payload)
    assert account.total_value == Decimal("10001.00")
    assert account.model_extra == {"futureAdditiveField": "retained"}


@pytest.mark.parametrize("value", [1.1, "1.1", float("inf")])
def test_provider_financial_values_reject_float_and_numeric_strings(value: object) -> None:
    with pytest.raises(ValidationError, match="financial numbers"):
        TransactionDTO.model_validate(
            {
                "amount": value,
                "currency": "EUR",
                "dateTime": "2026-01-01T00:00:00Z",
                "reference": "synthetic",
                "type": "DEPOSIT",
            }
        )


def test_missing_required_semantic_field_is_not_fabricated() -> None:
    with pytest.raises(ValidationError, match="amount"):
        TransactionDTO.model_validate(
            {
                "currency": "EUR",
                "dateTime": "2026-01-01T00:00:00Z",
                "reference": "synthetic",
                "type": "DEPOSIT",
            }
        )


def test_naive_source_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        TransactionDTO.model_validate(
            {
                "amount": Decimal("1"),
                "currency": "EUR",
                "dateTime": "2026-01-01T00:00:00",
                "reference": "synthetic",
                "type": "DEPOSIT",
            }
        )


def test_unrepresentable_rate_limit_reset_is_rejected_as_contract_data() -> None:
    with pytest.raises(ValueError, match="reset timestamp"):
        parse_rate_limit_headers(
            {
                "x-ratelimit-limit": "1",
                "x-ratelimit-period": "5",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "999999999999999999999999",
                "x-ratelimit-used": "1",
            }
        )
