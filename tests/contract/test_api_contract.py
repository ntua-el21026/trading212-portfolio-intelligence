from __future__ import annotations

import json

import pytest
from trading212_api.main import create_app
from trading212_security.settings import RuntimeEnvironment, SecuritySettings


@pytest.mark.contract
def test_openapi_contains_complete_phase1_routes_and_no_generic_broker_proxy() -> None:
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("localhost",),
        )
    )
    document = application.openapi()
    paths = set(document["paths"])
    required = {
        "/api/v1/me",
        "/api/v1/broker-connections",
        "/api/v1/accounts",
        "/api/v1/accounts/{account_id}",
        "/api/v1/accounts/{account_id}/refresh",
        "/api/v1/refresh-runs/{run_id}",
        "/api/v1/accounts/{account_id}/summary",
        "/api/v1/accounts/{account_id}/positions",
        "/api/v1/accounts/{account_id}/positions/{position_id}",
        "/api/v1/accounts/{account_id}/transactions",
        "/api/v1/accounts/{account_id}/dividends",
        "/api/v1/accounts/{account_id}/orders",
        "/api/v1/accounts/{account_id}/snapshots",
        "/api/v1/accounts/{account_id}/snapshots/latest",
        "/api/v1/accounts/{account_id}/snapshots/compare",
        "/api/v1/accounts/{account_id}/allocation",
        "/api/v1/accounts/{account_id}/performance/summary",
        "/api/v1/accounts/{account_id}/reconciliation",
        "/api/v1/accounts/{account_id}/reconciliation/discrepancies",
        "/api/v1/accounts/{account_id}/data-quality",
        "/api/v1/instruments",
        "/api/v1/instruments/{instrument_id}",
    }
    assert required <= paths
    assert not any("proxy" in path or "sql" in path for path in paths)
    assert set(document["paths"]["/api/v1/accounts/{account_id}/refresh"]) == {"post"}

    serialized = json.dumps(document, sort_keys=True).casefold()
    assert "api_secret" not in serialized
    assert "authorization: basic" not in serialized
    assert "broker credential" not in serialized


@pytest.mark.contract
def test_decimal_fields_are_strings_in_openapi() -> None:
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("localhost",),
        )
    )
    schemas = application.openapi()["components"]["schemas"]
    metric_value = schemas["MetricResponse"]["properties"]["value"]
    options = metric_value["anyOf"]
    assert any(option.get("type") == "string" for option in options)
    assert not any(option.get("type") == "number" for option in options)


@pytest.mark.contract
def test_refresh_contract_requires_snapshot_creation() -> None:
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("localhost",),
        )
    )
    schema = application.openapi()["components"]["schemas"]["RefreshRequest"]
    assert schema["properties"]["create_snapshot"]["const"] is True
