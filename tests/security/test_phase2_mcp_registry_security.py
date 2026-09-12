"""Registry-wide scope and private-input boundaries, with explicit positive controls."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from starlette.testclient import TestClient
from trading212_application.alerts import AlertService
from trading212_application.historical import PerformanceIntelligenceService
from trading212_application.planning import PlanningService
from trading212_application.reports import ReportService
from trading212_application.services import PortfolioService, SyntheticPortfolioService
from trading212_application.targets import TargetService
from trading212_application.xray import XrayService
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import McpRuntime, create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.mcp_registry_cases import CASES, LEGACY_CASES, RegistryCase

pytestmark = pytest.mark.security
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _principal(scopes: frozenset[Scope]) -> Principal:
    return Principal(
        "registry-principal",
        SyntheticPortfolioService.OWNER_ID,
        "local.synthetic",
        "registry-owner",
        scopes,
        NOW,
        datetime(2099, 1, 1, tzinfo=UTC),
    )


def _runtime(service: AsyncMock | None = None) -> McpRuntime:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        target_service=cast(TargetService | None, service),
        planning_service=cast(PlanningService | None, service),
        historical_service=cast(PerformanceIntelligenceService | None, service),
        xray_service=cast(XrayService | None, service),
        report_service=cast(ReportService | None, service),
        alert_service=cast(AlertService | None, service),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_every_tool_hides_unknown_names_values_and_invalid_known_values_before_auth(
    case: RegistryCase,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    resolver = AsyncMock(side_effect=AssertionError("Validation reached authentication."))
    monkeypatch.setattr(PrincipalResolver, "resolve", resolver)
    server = _runtime().server
    private_key = "_".join(("REGISTRY", "PRIVATE", "ARGUMENT"))
    private_value = "_".join(("REGISTRY", "PRIVATE", "VALUE"))
    unknown = copy.deepcopy(case.arguments)
    unknown[private_key] = private_value
    invalid_known = copy.deepcopy(case.arguments)
    invalid_known["account_id"] = {private_key: private_value}
    for arguments in (unknown, invalid_known):
        with pytest.raises(ToolError) as failure:
            await server.call_tool(case.name, arguments)
        assert private_key not in str(failure.value) + caplog.text
        assert private_value not in str(failure.value) + caplog.text
    resolver.assert_not_awaited()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_exact_scopes_and_each_missing_scope_with_positive_dispatch_control(
    case: RegistryCase,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    required = frozenset(Scope(value) for value in case.scopes)
    selected = _principal(required)
    private_detail = "_".join(("REGISTRY", "APPLICATION", "PRIVATE"))

    async def resolve(_resolver: PrincipalResolver) -> Principal:
        return selected

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)
    service = AsyncMock()
    if case.service_method is not None:
        getattr(service, case.service_method).side_effect = RuntimeError(private_detail)
    server = _runtime(service).server
    arguments = {
        **copy.deepcopy(case.arguments),
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
    }

    # First prove this argument reaches the intended service with exactly its scopes.
    positive = await server.call_tool(case.name, arguments)
    assert isinstance(positive, CallToolResult) and positive.structured_content is not None
    RESULT_MODELS[case.name].model_validate(positive.structured_content)
    if case.legacy:
        assert not positive.is_error
    else:
        assert case.service_method is not None
        getattr(service, case.service_method).assert_awaited_once()
        assert positive.is_error
        assert positive.structured_content["error"]["code"] != "ACCESS_DENIED"
        assert private_detail not in positive.model_dump_json() + caplog.text

    # Extra unrelated scopes never compensate for any missing required grant.
    for missing in required:
        service.reset_mock()
        selected = _principal(frozenset(Scope) - {missing})
        denied = await server.call_tool(case.name, arguments)
        assert isinstance(denied, CallToolResult) and denied.is_error, (case.name, missing)
        assert denied.structured_content is not None
        assert denied.structured_content["data"] is None
        assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
        RESULT_MODELS[case.name].model_validate(denied.structured_content)
        # This mock observes new-family dispatch. The dedicated legacy regression
        # below also observes calls into its real synthetic application service.
        assert service.mock_calls == [], (case.name, missing)


@pytest.mark.parametrize("case", LEGACY_CASES, ids=lambda case: case.name)
async def test_legacy_tools_check_all_scopes_before_any_canonical_service_dispatch(
    case: RegistryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = frozenset(Scope(value) for value in case.scopes)
    authorized = replace(_principal(required), expires_at=NOW + timedelta(seconds=60))
    selected = authorized
    now = NOW

    async def resolve(_resolver: PrincipalResolver) -> Principal:
        return selected

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)
    canonical = SyntheticPortfolioService(clock=lambda: now)
    observed = AsyncMock(spec=PortfolioService, wraps=canonical)
    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
        ),
        service=cast(PortfolioService, observed),
        clock=lambda: now,
    ).server
    arguments = {
        **copy.deepcopy(case.arguments),
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
    }

    # The wrapper must really execute the canonical positive control with exact scopes.
    positive = await server.call_tool(case.name, arguments)
    assert isinstance(positive, CallToolResult) and not positive.is_error
    assert positive.structured_content is not None
    RESULT_MODELS[case.name].model_validate(positive.structured_content)
    assert positive.structured_content["data"] is not None
    assert positive.structured_content["error"] is None
    assert observed.mock_calls

    for missing in required:
        observed.reset_mock()
        selected = replace(authorized, scopes=frozenset(Scope) - {missing})
        denied = await server.call_tool(case.name, arguments)
        assert isinstance(denied, CallToolResult) and denied.is_error
        assert denied.structured_content is not None
        RESULT_MODELS[case.name].model_validate(denied.structured_content)
        assert denied.structured_content["data"] is None
        assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
        # Count invocation, not just awaiting: gather can schedule work before another
        # service rejects, and a submitted database thread cannot be rolled back here.
        assert observed.mock_calls == [], (case.name, missing)

    # A short-lived positive control and this boundary use the injected runtime clock.
    observed.reset_mock()
    selected = authorized
    now = authorized.expires_at
    expired = await server.call_tool(case.name, arguments)
    assert isinstance(expired, CallToolResult) and expired.is_error
    assert expired.structured_content is not None
    RESULT_MODELS[case.name].model_validate(expired.structured_content)
    assert expired.structured_content["data"] is None
    assert expired.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert observed.mock_calls == []


@pytest.mark.parametrize("case", LEGACY_CASES, ids=lambda case: case.name)
async def test_original_nine_enforce_owner_and_account_in_canonical_service(
    case: RegistryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _principal(frozenset(Scope))

    async def resolve(_resolver: PrincipalResolver) -> Principal:
        return selected

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)
    server = _runtime().server
    arguments = {
        **copy.deepcopy(case.arguments),
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
    }
    positive = await server.call_tool(case.name, arguments)
    assert isinstance(positive, CallToolResult) and not positive.is_error
    selected = replace(selected, owner_id="63891f9c-ee24-446f-8509-6f71c2b9d87b")
    denied = await server.call_tool(case.name, arguments)
    assert isinstance(denied, CallToolResult) and denied.is_error
    assert denied.structured_content is not None
    assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert denied.structured_content["data"] is None

    selected = _principal(frozenset(Scope))
    foreign_account = await server.call_tool(
        case.name,
        {**arguments, "account_id": "eae02284-1c91-43b9-9cc7-656122ed16fb"},
    )
    assert isinstance(foreign_account, CallToolResult) and foreign_account.is_error
    assert foreign_account.structured_content is not None
    assert foreign_account.structured_content["data"] is None
    assert foreign_account.structured_content["error"]["code"] == "ACCESS_DENIED"


class _Bearer:
    token = "_".join(("REGISTRY", "TRANSPORT", "CANARY"))

    async def authenticate(self, token: str) -> Principal:
        if token != self.token:
            raise AuthenticationError("Invalid test credential.")
        return _principal(frozenset(Scope))


def test_every_registered_name_fails_closed_without_a_valid_transport_principal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bearer = _Bearer()
    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            issuer="https://issuer.example",
            allowed_hosts=("localhost",),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        bearer_authenticator=bearer,
        clock=lambda: NOW,
    )
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:

        def call(name: str, arguments: dict[str, Any], authorization: str | None) -> Any:
            return client.post(
                "/mcp",
                headers={
                    **headers,
                    **({"Authorization": authorization} if authorization else {}),
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )

        positive = call(
            "get_account_summary",
            {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
            f"Bearer {bearer.token}",
        )
        assert positive.status_code == 200
        assert positive.json()["result"]["isError"] is False
        for case in CASES:
            for authorization in (None, "Bearer invalid-registry-token"):
                denied = call(case.name, case.arguments, authorization)
                assert denied.status_code == 401, case.name
                assert bearer.token not in denied.text
        assert bearer.token not in positive.text + caplog.text
