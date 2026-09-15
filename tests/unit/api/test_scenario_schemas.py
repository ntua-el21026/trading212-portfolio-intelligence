"""Strict scenario requests and complete distinct public financial DTOs."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError
from trading212_api.scenario_schemas import scenario_definition, scenario_run
from trading212_api_contracts import scenarios as wire
from trading212_domain.serialization import to_primitive

from tests.unit.api.scenario_factories import (
    ACCOUNT,
    RUN,
    SNAPSHOT,
    VERSION,
    comparison,
    queued,
    run,
    version,
)
from tests.unit.api.test_scenario_routes import run_body


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", " "),
        ("method_version", "latest"),
        ("mode", "arbitrary"),
        ("owner_id", "private-owner-canary"),
        ("shocks", [{}] * 129),
        ("exclusions", [{}] * 129),
    ],
)
def test_closed_definition_fields_and_admitted_counts(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        wire.ScenarioVersionContent.model_validate(
            {**to_primitive(version().content), field: value}
        )


@pytest.mark.parametrize(
    "kind,value",
    [
        ("price", 0.1),
        ("price", True),
        ("price", "6"),
        ("fx", "-1.1"),
        ("rate", "1.1"),
        ("factor", "NaN"),
        ("rate", "1e-3"),
    ],
)
def test_all_shock_variants_require_exact_bounded_decimal_strings(kind: str, value: object) -> None:
    shock = {"kind": kind, "size": value}
    if kind in ("rate", "factor"):
        shock["source"] = {
            "version_id": str(VERSION),
            "content_digest": "a" * 64,
            "driver_id": str(RUN),
            "driver_definition_version_id": str(SNAPSHOT),
        }
    else:
        shock["selector"] = (
            {"kind": "economic_currency", "currency": "EUR"}
            if kind == "fx"
            else {"kind": "instrument", "instrument_id": str(SNAPSHOT)}
        )
    with pytest.raises(ValidationError):
        wire.ScenarioVersionContent.model_validate(
            {**to_primitive(version().content), "shocks": [shock]}
        )


def test_conversion_preserves_exact_shock_and_saved_run_pins() -> None:
    payload = to_primitive(version().content)
    payload["shocks"][0]["size"] = "-0.123456789012345678"
    parsed = wire.ScenarioVersionContent.model_validate(payload)
    assert scenario_definition(parsed).shocks[0].size == Decimal("-0.123456789012345678")
    body = wire.CreateScenarioRunRequest.model_validate(run_body())
    command = scenario_run(str(ACCOUNT), body, key="synthetic-key", correlation="trace")
    assert command.scenario_version_id == VERSION and command.account_id == ACCOUNT
    for forbidden in (
        "coefficient",
        "returns",
        "sources",
        "exposures",
        "owner_id",
        "xray_input_id",
    ):
        with pytest.raises(ValidationError):
            wire.CreateScenarioRunRequest.model_validate(
                {**run_body(), forbidden: "private-canary"}
            )


def test_equal_selectors_and_driver_aliases_cannot_repeat() -> None:
    payload = to_primitive(version().content)
    shock = payload["shocks"][0]
    for duplicate in (shock, {**shock, "size": "0.2"}):
        with pytest.raises(ValidationError):
            wire.ScenarioVersionContent.model_validate({**payload, "shocks": [shock, duplicate]})
    source = {
        "version_id": str(VERSION),
        "content_digest": "a" * 64,
        "driver_id": str(RUN),
        "driver_definition_version_id": str(SNAPSHOT),
    }
    with pytest.raises(ValidationError):
        wire.ScenarioVersionContent.model_validate(
            {
                **payload,
                "shocks": [
                    {"kind": "rate", "source": source, "size": "0.01"},
                    {
                        "kind": "factor",
                        "source": {**source, "version_id": str(SNAPSHOT)},
                        "size": "0.02",
                    },
                ],
            }
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"start_date": "2025-01-01", "end_date": "2025-01-01"},
        {"start_date": "2025-01-02", "end_date": "2025-01-01"},
        {"market_knowledge_cutoff_at": "2025-01-01T00:00:00"},
        {"holdings_basis": "latest"},
        {"knowledge_basis": "unknown"},
    ],
)
def test_replay_selection_has_closed_dates_holdings_and_knowledge(extra: dict[str, object]) -> None:
    value = {
        "historical_input_snapshot_id": str(VERSION),
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "market_knowledge_cutoff_at": "2025-01-02T00:00:00Z",
        "holdings_basis": "current_holdings",
        "knowledge_basis": "point_in_time",
    }
    with pytest.raises(ValidationError):
        wire.ScenarioReplaySelection.model_validate({**value, **extra})


def test_public_result_and_comparison_roundtrip_preserve_exact_money_and_original_pins() -> None:
    for schema, value in (
        (wire.ScenarioRunResponse, run()),
        (wire.ScenarioComparisonPage, comparison()),
    ):
        data = to_primitive(value)
        assert schema.model_validate(data).model_dump(mode="json") == data
    wire.ScenarioOperationalRunResponse.model_validate(to_primitive(queued()))
    with pytest.raises(ValidationError):
        wire.ScenarioOperationalRunResponse.model_validate(to_primitive(run()))
    mutated = deepcopy(to_primitive(run()))
    mutated["result"]["components"]["items"][0]["post_value"]["value"]["amount"] = 1.0
    with pytest.raises(ValidationError):
        wire.ScenarioRunResponse.model_validate(mutated)


@pytest.mark.parametrize(
    "kind", ("running_result", "missing_result", "different_pin", "missing_completion")
)
def test_atomic_operational_and_financial_status(kind: str) -> None:
    data = to_primitive(run())
    if kind == "running_result":
        data["state"], data["completed_at"] = "running", None
    elif kind == "missing_result":
        data["result"] = None
    elif kind == "different_pin":
        data["scenario_version_id"] = str(SNAPSHOT)
    else:
        data["completed_at"] = None
    with pytest.raises(ValidationError):
        wire.ScenarioRunResponse.model_validate(data)
    assert (
        wire.ScenarioOperationalRunResponse.model_validate(
            to_primitive(replace(run(), result=None, result_availability="not_loaded"))
        ).state
        == "succeeded"
    )


@pytest.mark.parametrize("state", ("queued", "running"))
def test_retry_status_preserves_fixed_previous_attempt_failure(state: str) -> None:
    data = to_primitive(queued())
    data["state"] = state
    data["failure_code"] = "storage_unavailable"
    value = wire.ScenarioOperationalRunResponse.model_validate(data)
    assert value.state == state and value.failure_code == "storage_unavailable"
    data["failure_code"] = "private-provider-error-canary"
    with pytest.raises(ValidationError):
        wire.ScenarioOperationalRunResponse.model_validate(data)
