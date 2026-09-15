"""Closed REST surface, command guards, conditional authorization and sanitized errors."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import scenario as app
from trading212_application.risk import PremiumJobState
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.analytics.xray_factories import uid
from tests.unit.api.scenario_factories import (
    ACCOUNT,
    DEFINITION,
    NOW,
    RUN,
    SECOND_RUN,
    SNAPSHOT,
    VERSION,
    XRAY,
    comparison,
    definition,
    inputs,
    queued,
    run,
    version,
)

ORIGIN = "https://testserver"
SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.SCENARIOS_WRITE})
HEADERS = {"Authorization": "Bearer synthetic-scenario-test", "X-Idempotency-Key": "synthetic-one"}


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == HEADERS["Authorization"].removeprefix("Bearer ")
        return Principal(
            "scenario-test",
            str(uid(1)),
            "test",
            "test",
            self.scopes,
            NOW,
            NOW + timedelta(hours=1),
        )


def application(
    scopes: frozenset[Scope] = SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.ScenarioService)
    service.create_definition.return_value = service.get_definition.return_value = definition()
    service.get_version.return_value = version()
    service.create_version.return_value = replace(
        version(), id=SNAPSHOT, predecessor_id=VERSION, version_number=2
    )
    service.create_run.return_value = queued()
    service.get_run.return_value = run()
    service.compare.return_value = comparison()
    service.cancel_run.return_value = replace(
        queued(),
        state=PremiumJobState.CANCELLED,
        completed_at=NOW,
        result_availability="unavailable",
    )
    service.list_definitions.return_value = Page((definition(),), None, 25, 1)
    service.list_versions.return_value = Page((version(),), None, 25, 1)
    service.list_runs.return_value = Page((queued(),), None, 25, 1)
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
            local_synthetic_auth_enabled=True,
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        scenario_service=cast(app.ScenarioService, service) if available else None,
        bearer_authenticator=Bearer(scopes),
        clock=lambda: NOW,
    )
    return api, service


def run_body() -> dict[str, object]:
    value = inputs()
    return {
        "scenario_version_id": str(VERSION),
        "portfolio_snapshot_id": str(SNAPSHOT),
        "xray_run_id": str(XRAY),
        "reporting_currency": value.pins.reporting_currency.value,
        "source_cutoff_at": value.pins.source_cutoff_at.isoformat(),
    }


OPERATIONS = (
    ("get", f"/accounts/{ACCOUNT}/scenarios", "list_definitions", 200),
    ("post", f"/accounts/{ACCOUNT}/scenarios", "create_definition", 201),
    ("get", f"/scenarios/{DEFINITION}", "get_definition", 200),
    ("get", f"/scenarios/{DEFINITION}/versions", "list_versions", 200),
    ("post", f"/scenarios/{DEFINITION}/versions", "create_version", 201),
    ("get", f"/scenario-versions/{VERSION}", "get_version", 200),
    ("get", f"/accounts/{ACCOUNT}/scenario-runs", "list_runs", 200),
    ("post", f"/accounts/{ACCOUNT}/scenario-runs", "create_run", 202),
    ("get", f"/scenario-runs/{RUN}", "get_run", 200),
    (
        "get",
        f"/accounts/{ACCOUNT}/scenario-comparison?run_ids={RUN}&run_ids={SECOND_RUN}",
        "compare",
        200,
    ),
    ("post", f"/scenario-runs/{RUN}/cancel", "cancel_run", 200),
)


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_eleven_routes_delegate_once_and_preserve_canonical_views(
    method: str, path: str, name: str, status: int
) -> None:
    api, service = application()
    body = (
        {"content": to_primitive(version().content)}
        if name in {"create_definition", "create_version"}
        else run_body()
        if name == "create_run"
        else {}
        if method == "post"
        else None
    )
    headers = {**HEADERS, "If-Match": f'"{DEFINITION}:1"'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(method, "/api/v1" + path, json=body, headers=headers)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == to_primitive(getattr(service, name).return_value)
    assert len(service.mock_calls) == 1
    if method == "post":
        command = getattr(service, name).call_args.args[1]
        assert command.idempotency_key == "synthetic-one"
    if name == "create_version":
        assert service.create_version.call_args.args[1].expected_revision == 1
        assert response.headers["etag"] == f'"{DEFINITION}:2"'


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_authentication_and_required_read_scopes_precede_parsing(
    method: str, path: str, name: str, status: int
) -> None:
    for scopes, headers, expected in (
        (SCOPES, {}, 401),
        (SCOPES - {Scope.ANALYTICS_READ}, HEADERS, 403),
        (SCOPES - {Scope.PORTFOLIO_READ}, HEADERS, 403),
    ):
        api, service = application(scopes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
            response = await client.request(
                method,
                "/api/v1" + path + ("&" if "?" in path else "?") + "private-canary=hidden",
                content=b"malformed",
                headers=headers,
            )
        assert response.status_code == expected
        assert not service.mock_calls and "canary" not in response.text


@pytest.mark.parametrize(
    "revision,status",
    [
        (None, 428),
        ('W/"old"', 422),
        ('"invalid"', 422),
        (f'"{DEFINITION}:513"', 422),
        (f'"{RUN}:1"', 412),
    ],
)
async def test_version_requires_owned_aggregate_revision(revision: str | None, status: int) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/scenarios/{DEFINITION}/versions",
            json={"content": to_primitive(version().content)},
            headers={**HEADERS, **({"If-Match": revision} if revision is not None else {})},
        )
    assert response.status_code == status and not service.mock_calls


@pytest.mark.parametrize(
    "code,status",
    [
        (app.ScenarioErrorCode.CONFLICT, 409),
        (app.ScenarioErrorCode.RUN_EXPIRED, 410),
        (app.ScenarioErrorCode.SOURCE_UNAVAILABLE, 503),
        (app.ScenarioErrorCode.ACCESS_DENIED, 403),
        (app.ScenarioErrorCode.RATE_LIMITED, 429),
    ],
)
async def test_conditional_reads_reauthorize_and_errors_are_sanitized(
    code: app.ScenarioErrorCode, status: int
) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        first = await client.get(f"/api/v1/scenario-runs/{RUN}", headers=HEADERS)
        unchanged = await client.get(
            f"/api/v1/scenario-runs/{RUN}",
            headers={**HEADERS, "If-None-Match": first.headers["etag"]},
        )
        assert unchanged.status_code == 304 and service.get_run.await_count == 2
        service.get_run.side_effect = app.ScenarioServiceError(code, "private-error-canary")
        denied = await client.get(
            f"/api/v1/scenario-runs/{RUN}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert denied.status_code == status and "canary" not in denied.text
    assert denied.headers["cache-control"] == "private, no-store"
    assert denied.json()["error"]["retryable"] == (status == 503)


async def test_unknown_duplicate_oversized_and_float_inputs_never_enter_service() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        path = f"/api/v1/accounts/{ACCOUNT}/scenarios"
        for query in ("limit=25&limit=26", "private-canary=hidden", "limit=101"):
            response = await client.get(path + "?" + query, headers=HEADERS)
            assert response.status_code == 422 and "canary" not in response.text
        for body in (
            {
                "content": {
                    **to_primitive(version().content),
                    "shocks": [
                        {
                            "kind": "price",
                            "selector": {"kind": "instrument", "instrument_id": str(SNAPSHOT)},
                            "size": 0.1,
                        }
                    ],
                }
            },
            {"owner_id": str(ACCOUNT), "content": to_primitive(version().content)},
        ):
            response = await client.post(path, json=body, headers=HEADERS)
            assert response.status_code == 422
        for key in (None, "", "x" * 181):
            headers = {
                "Authorization": HEADERS["Authorization"],
                **({"X-Idempotency-Key": key} if key is not None else {}),
            }
            response = await client.post(
                path, json={"content": to_primitive(version().content)}, headers=headers
            )
            assert response.status_code == 422
        response = await client.post(path, content=b"x" * 65537, headers=HEADERS)
        assert response.status_code == 413
        response = await client.post(
            path, json={}, headers=[*HEADERS.items(), ("X-Idempotency-Key", "two")]
        )
        assert response.status_code == 422
    assert not service.mock_calls


async def test_session_origin_csrf_and_write_scope_are_required() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        csrf = session.json()["csrf_token"]
        for extra in (
            {},
            {"Origin": ORIGIN},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
        ):
            response = await client.post(
                f"/api/v1/scenario-runs/{RUN}/cancel",
                json={},
                headers={"X-Idempotency-Key": "cancel-one", **extra},
            )
            assert response.status_code == 401
        assert not service.mock_calls
        response = await client.post(
            f"/api/v1/scenario-runs/{RUN}/cancel",
            json={},
            headers={"X-Idempotency-Key": "cancel-one", "Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
    api, service = application(SCOPES - {Scope.SCENARIOS_WRITE})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/scenario-runs/{RUN}/cancel", json={}, headers=HEADERS
        )
    assert response.status_code == 403 and not service.mock_calls


async def test_missing_composition_is_explicitly_unavailable() -> None:
    api, service = application(available=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/scenario-runs/{RUN}", headers=HEADERS)
    assert response.status_code == 503 and not service.mock_calls


async def test_detail_and_comparison_forward_only_closed_ordered_page_selections() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        detail = await client.get(
            f"/api/v1/scenario-runs/{RUN}?component_limit=100&component_cursor=opaque",
            headers=HEADERS,
        )
        assert detail.status_code == 200
        assert service.get_run.call_args.args[2] == app.ScenarioComponentPageQuery(
            component_limit=100, component_cursor="opaque"
        )
        compared = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/scenario-comparison?run_ids={SECOND_RUN}&run_ids={RUN}&component_limit=1&component_cursor=opaque",
            headers=HEADERS,
        )
        assert compared.status_code == 200
        assert service.compare.call_args.args[2] == app.ScenarioComparisonQuery(
            run_ids=(SECOND_RUN, RUN), component_limit=1, component_cursor="opaque"
        )


@pytest.mark.parametrize(
    "query",
    [
        "component_limit=0",
        "component_limit=101",
        "component_limit=true",
        "component_limit=1&component_limit=2",
        "component_cursor=" + "x" * 2049,
        "component_cursor=a&component_cursor=b",
        "run_ids=a&run_ids=b",
        "private-canary=hidden",
    ],
)
async def test_detail_page_invalid_queries_never_enter_service(query: str) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/scenario-runs/{RUN}?{query}", headers=HEADERS)
    assert response.status_code == 422 and not service.mock_calls
    assert "canary" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "",
        f"run_ids={RUN}",
        f"run_ids={RUN}&run_ids={RUN}",
        f"run_ids={RUN}&run_ids={SECOND_RUN}&run_ids={VERSION}",
        f"run_ids={RUN},{SECOND_RUN}",
        f"run_ids=invalid&run_ids={RUN}",
    ],
)
async def test_comparison_requires_exactly_two_distinct_repeated_uuid_values(query: str) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/scenario-comparison?{query}", headers=HEADERS
        )
    assert response.status_code == 422 and not service.mock_calls


@pytest.mark.parametrize("operation", ("create_run", "cancel_run", "list_runs"))
async def test_operational_routes_fail_closed_if_service_supplies_financial_payload(
    operation: str,
) -> None:
    api, service = application()
    getattr(service, operation).return_value = (
        Page((run(),), None, 25, 1) if operation == "list_runs" else run()
    )
    method = "get" if operation == "list_runs" else "post"
    path = (
        f"/api/v1/scenario-runs/{RUN}/cancel"
        if operation == "cancel_run"
        else f"/api/v1/accounts/{ACCOUNT}/scenario-runs"
    )
    body = run_body() if operation == "create_run" else {} if operation == "cancel_run" else None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(method, path, headers=HEADERS, json=body)
    assert response.status_code == 500
    assert "post_value" not in response.text and "components" not in response.text


async def test_cross_owner_not_found_precedes_wildcard_conditional_response() -> None:
    api, service = application()
    service.get_run.side_effect = app.ScenarioServiceError(
        app.ScenarioErrorCode.NOT_FOUND, "private-owner-canary"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/scenario-runs/{RUN}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert response.status_code == 404 and service.get_run.await_count == 1
    assert "canary" not in response.text


async def test_full_encoded_utf8_envelope_is_bounded_before_conditional_success() -> None:
    from decimal import Decimal

    from trading212_domain.scenario import ScenarioRateShock, ScenarioSensitivityVersionPin

    content = replace(
        version().content,
        description="界" * 1024,
        shocks=tuple(
            ScenarioRateShock(
                source=ScenarioSensitivityVersionPin(
                    version_id=uid(31000 + i),
                    content_digest="a" * 64,
                    driver_id=uid(32000 + i),
                    driver_definition_version_id=uid(33000 + i),
                ),
                size=Decimal("0.01"),
            )
            for i in range(128)
        ),
    )
    bulky = replace(version(), content=content)
    api, service = application()
    service.list_versions.return_value = Page(tuple(bulky for _ in range(100)), None, 100, 100)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/scenarios/{DEFINITION}/versions?limit=100",
            headers={**HEADERS, "If-None-Match": "*"},
        )
    assert response.status_code == 422 and response.json()["error"]["code"] == "RESULT_TOO_LARGE"
    assert "界" not in response.text


async def test_utf8_envelope_limit_is_checked_before_wildcard_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_api import scenario_schemas
    from trading212_api_contracts.scenarios import ScenarioDefinitionResponse

    api, service = application()
    value = replace(definition(), name="界" * 120)
    service.get_definition.return_value = value
    encoded = ScenarioDefinitionResponse.model_validate(to_primitive(value)).model_dump_json()
    assert len(encoded.encode("utf-8")) > len(encoded)
    monkeypatch.setattr(scenario_schemas, "RESPONSE_BYTE_LIMIT", len(encoded.encode("utf-8")) - 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/scenarios/{DEFINITION}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert response.status_code == 422 and service.get_definition.await_count == 1
    assert response.json()["error"]["code"] == "RESULT_TOO_LARGE"
