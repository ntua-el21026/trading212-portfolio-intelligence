"""Negative wire-contract boundaries for owner-private target commands."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from trading212_api_contracts.targets import (
    AwareInstant,
    CreateTargetVersionRequest,
    CreateVirtualPortfolioRequest,
    DecimalString,
    TargetConstraint,
    TargetContent,
    TargetHoldingMapping,
    TargetNode,
    UpdateVirtualPortfolioRequest,
    ValidateTargetRequest,
)


@pytest.mark.parametrize(
    "value",
    [
        1,
        0.5,
        True,
        None,
        "1e2",
        "NaN",
        "Infinity",
        "+1",
        "01",
        ".5",
        "1.",
        "1" * 21,
        "0." + "1" * 19,
    ],
)
def test_financial_wire_values_reject_numbers_and_unbounded_or_noncanonical_text(
    value: Any,
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(DecimalString).validate_python(value)


@pytest.mark.parametrize(
    "value", ["0", "-0", "0.000000000000000001", "99999999999999999999.999999999999999999"]
)
def test_financial_wire_values_preserve_exact_decimal_strings(value: str) -> None:
    assert TypeAdapter(DecimalString).validate_python(value) == value


@pytest.mark.parametrize("value", [0, "2026-09-07", "2026-09-07T10:00:00", "2026-09-07 10:00:00Z"])
def test_target_instants_require_aware_rfc3339_text(value: Any) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AwareInstant).validate_python(value)


def test_target_instant_normalizes_an_explicit_offset_to_utc() -> None:
    value = TypeAdapter(AwareInstant).validate_python("2026-09-07T13:00:00+03:00")
    assert value == datetime(2026, 9, 7, 10, tzinfo=UTC)
    assert value.tzinfo is UTC


@pytest.mark.parametrize(
    "body",
    [
        {"name": "   ", "reporting_currency": "EUR"},
        {"name": "Template", "reporting_currency": "EUR", "provider_url": "secret-canary"},
        {"name": "Template", "reporting_currency": "EUR", "account_id": "not-a-uuid"},
        {"name": "Template", "reporting_currency": "eur"},
    ],
)
def test_portfolio_shape_and_identifiers_are_bounded(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CreateVirtualPortfolioRequest.model_validate(body)


def test_owner_private_template_accepts_an_explicit_null_account() -> None:
    body = CreateVirtualPortfolioRequest.model_validate(
        {"name": "Template", "reporting_currency": "EUR", "account_id": None}
    )
    assert body.account_id is None


def test_unresolved_listing_can_preserve_a_known_canonical_instrument() -> None:
    mapping = TargetHoldingMapping.model_validate(
        {
            "state": "unresolved",
            "instrument_id": "5d1d93e9-4b43-4a5e-9986-bcd36e08cbdb",
            "requested_identifier": {"kind": "isin", "value": "IE00B4L5Y983"},
            "reason": "The instrument is known but its listing requires resolution.",
        }
    )
    assert mapping.instrument_id == "5d1d93e9-4b43-4a5e-9986-bcd36e08cbdb"
    assert mapping.listing_id is None
    assert mapping.state == "unresolved"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"description": None},
        {"account_id": None},
        {"reporting_currency": "GBP"},
    ],
)
def test_metadata_patch_does_not_mutate_identity_or_accept_an_empty_change(
    body: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UpdateVirtualPortfolioRequest.model_validate(body)


def test_nested_unknown_fields_and_duplicate_keys_are_rejected() -> None:
    node = {"key": "cash", "kind": "cash", "name": "Cash", "weight": "1"}
    with pytest.raises(ValidationError):
        TargetContent.model_validate({"nodes": [{**node, "execute": True}]})
    with pytest.raises(ValidationError):
        TargetContent.model_validate({"nodes": [node, node]})
    with pytest.raises(ValidationError):
        TargetContent.model_validate(
            {"nodes": [{**node, "key": str(index)} for index in range(257)]}
        )


@pytest.mark.parametrize("weight", ["-0.1", "1.000000000000000001", 1, True])
def test_sibling_weights_require_exact_unit_interval_strings(weight: Any) -> None:
    with pytest.raises(ValidationError):
        TargetNode.model_validate({"key": "cash", "kind": "cash", "name": "Cash", "weight": weight})


@pytest.mark.parametrize(
    "body",
    [
        {"key": "rule", "kind": "eligible", "node_key": "leaf", "enabled": "false"},
        {
            "key": "rule",
            "kind": "eligible",
            "node_key": "leaf",
            "enabled": True,
            "amount": "1",
            "currency": "EUR",
        },
        {
            "key": "rule",
            "kind": "amount_increment",
            "node_key": "leaf",
            "amount": "0",
            "currency": "EUR",
        },
        {"key": "rule", "kind": "maximum_funded_lines", "count": True},
        {
            "key": "rule",
            "kind": "priority",
            "node_key": "leaf",
            "coefficient": "1000.000000000000000001",
        },
    ],
)
def test_constraints_reject_incorrect_value_combinations(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TargetConstraint.model_validate(body)


@pytest.mark.parametrize("normalize", [1, "true", "false", None])
def test_normalization_requires_an_explicit_boolean(normalize: Any) -> None:
    with pytest.raises(ValidationError):
        ValidateTargetRequest.model_validate({"normalize": normalize})


def test_cloning_and_inline_content_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError):
        CreateTargetVersionRequest.model_validate({"effective_at": "2026-09-07T00:00:00Z"})
    with pytest.raises(ValidationError):
        CreateTargetVersionRequest.model_validate(
            {
                "effective_at": "2026-09-07T00:00:00Z",
                "source_version_id": "f7b73ce0-a3e4-4ab9-bca9-9848bcb96632",
                "content": {"nodes": []},
            }
        )
