"""Exact alert surface, scopes, concurrency and privacy at the HTTP boundary."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import alerts as app
from trading212_application.services import SyntheticPortfolioService
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.alert_factories import ACCOUNT, EVENT, NOW, RULE, body, event, rule

ORIGIN = "https://testserver"
SCOPES = frozenset(
    {Scope.PORTFOLIO_READ, Scope.ALERTS_READ, Scope.ALERTS_WRITE, Scope.ANALYTICS_READ}
)


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "synthetic-alert-test"
        return Principal(
            "alert-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "alert-test",
            "alert-test",
            self.scopes,
            NOW,
            NOW + timedelta(hours=1),
        )


def application(scopes: frozenset[Scope] = SCOPES) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.AlertService)
    service.create_rule.return_value = service.get_rule.return_value = rule()
    service.create_rule_version.return_value = app.AlertRuleVersionDetail(
        version=rule().latest_version, rule_revision=2
    )
    service.get_event.return_value = event()
    service.pause_rule.return_value = replace(rule(), revision=2)
    service.activate_rule.return_value = replace(rule(), revision=2)
    service.archive_rule.return_value = replace(rule(), revision=2)
    return create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        alert_service=cast(app.AlertService, service),
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    ), service


def headers(**extra: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer synthetic-alert-test",
        "X-Idempotency-Key": "alert:one",
        **extra,
    }


async def test_thirteen_routes_creation_and_immutable_version_do_not_activate() -> None:
    api, service = application()
    operations = [
        operation
        for path in api.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "alerts" in operation.get("tags", [])
    ]
    assert len(operations) == 13
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        created = await client.post("/api/v1/alert-rules", json=body(), headers=headers())
        assert created.status_code == 201
        assert created.json()["lifecycle"] == "draft" and created.json()["active_version"] is None
        saved = await client.post(
            f"/api/v1/alert-rules/{RULE}/versions",
            json={"definition": body()["definition"]},
            headers=headers(**{"If-Match": created.headers["etag"]}),
        )
        assert saved.status_code == 201 and saved.headers["etag"] == f'"{RULE}:2"'
    service.activate_rule.assert_not_awaited()
    assert service.create_rule_version.await_args.kwargs["expected_revision"] == 1
    assert "owner_id" not in created.text and "comparison_basis" not in created.text


@pytest.mark.parametrize(
    "missing", [Scope.PORTFOLIO_READ, Scope.ALERTS_WRITE, Scope.ANALYTICS_READ]
)
async def test_command_scope_denial_precedes_service(missing: Scope) -> None:
    api, service = application(SCOPES - {missing})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.post("/api/v1/alert-rules", json=body(), headers=headers())
    assert result.status_code == 403
    service.create_rule.assert_not_awaited()


async def test_write_scope_does_not_allow_reads_or_conditional_disclosure() -> None:
    api, service = application(SCOPES - {Scope.ALERTS_READ})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.get(
            f"/api/v1/alert-rules/{RULE}", headers=headers(**{"If-None-Match": "*"})
        )
    assert result.status_code == 403
    service.get_rule.assert_not_awaited()


@pytest.mark.parametrize(
    "revision,status", [(None, 428), ('W/"old"', 422), ('"invalid"', 422), (f'"{EVENT}:1"', 412)]
)
async def test_mutation_requires_exact_current_aggregate_revision(
    revision: str | None, status: int
) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.post(
            f"/api/v1/alert-rules/{RULE}/pause",
            json={},
            headers=headers(**({"If-Match": revision} if revision else {})),
        )
    assert result.status_code == status
    service.pause_rule.assert_not_awaited()


async def test_detail_etag_is_for_actions_and_never_hides_mutable_children() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        first = await client.get(f"/api/v1/alert-rules/{RULE}", headers=headers())
        second = await client.get(
            f"/api/v1/alert-rules/{RULE}",
            headers=headers(**{"If-None-Match": first.headers["etag"]}),
        )
    assert first.status_code == second.status_code == 200
    assert second.headers["cache-control"] == "private, no-store"
    assert service.get_rule.await_count == 2


async def test_session_commands_require_origin_csrf_and_idempotency() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        csrf = session.json()["csrf_token"]
        for command_headers in (
            {},
            {"Origin": ORIGIN},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": csrf},
        ):
            result = await client.post(
                "/api/v1/alert-rules",
                json=body(),
                headers={"X-Idempotency-Key": "session-alert", **command_headers},
            )
            assert result.status_code == 401
        service.create_rule.assert_not_awaited()
        result = await client.post(
            "/api/v1/alert-rules",
            json=body(),
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "X-Idempotency-Key": "session-alert"},
        )
    assert result.status_code == 201


@pytest.mark.parametrize(
    "code,status",
    [
        (app.AlertServiceErrorCode.IDEMPOTENCY_KEY_REUSED, 409),
        (app.AlertServiceErrorCode.REVISION_MISMATCH, 412),
        (app.AlertServiceErrorCode.INVALID_STATE_TRANSITION, 409),
        (app.AlertServiceErrorCode.RATE_LIMITED, 429),
    ],
)
async def test_safe_distinct_errors_never_reflect_service_payload(
    code: app.AlertServiceErrorCode, status: int
) -> None:
    api, service = application()
    service.pause_rule.side_effect = app.AlertServiceError(
        code, "private-alert-error-canary", retryable=code is app.AlertServiceErrorCode.RATE_LIMITED
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        result = await client.post(
            f"/api/v1/alert-rules/{RULE}/pause",
            json={},
            headers=headers(**{"If-Match": f'"{RULE}:1"'}),
        )
    assert result.status_code == status and result.json()["error"]["code"] == code.value
    assert "private-alert-error-canary" not in result.text


async def test_unknown_duplicate_and_oversized_inputs_fail_before_service() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        for suffix in (
            f"account_id={ACCOUNT}&account_id={ACCOUNT}",
            f"account_id={ACCOUNT}&token=private-alert-canary",
        ):
            denied = await client.get(f"/api/v1/alert-rules?{suffix}", headers=headers())
            assert denied.status_code == 422 and "private-alert-canary" not in denied.text
        denied = await client.post(
            "/api/v1/alert-rules",
            json={**body(), "webhook_url": "private-alert-canary"},
            headers=headers(),
        )
        assert denied.status_code == 422 and "private-alert-canary" not in denied.text
        denied = await client.post(
            "/api/v1/alert-rules",
            content=b" " * (65536 + 1),
            headers=headers(**{"Content-Type": "application/json"}),
        )
        assert denied.status_code == 413
    service.create_rule.assert_not_awaited()
    service.list_rules.assert_not_awaited()
