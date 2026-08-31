from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import SESSION_COOKIE, create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_observability import (
    AuthenticationMethod,
    SecurityAuditAction,
    SecurityAuditEvent,
    SecurityAuditOutcome,
    configure_logging,
)
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import (
    LOCAL_SYNTHETIC_OWNER_ID,
    LOCAL_SYNTHETIC_PRINCIPAL_ID,
)

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
TOKEN_CANARY = "API-AUDIT-BEARER-CANARY"
CSRF_CANARY = "API-AUDIT-CSRF-CANARY"


@dataclass(slots=True)
class RecordingAuditSink:
    events: list[SecurityAuditEvent] = field(default_factory=list)

    async def record(self, event: SecurityAuditEvent) -> None:
        self.events.append(event)


class FailingAuditSink:
    async def record(self, event: SecurityAuditEvent) -> None:
        del event
        raise RuntimeError("Bearer API-AUDIT-SINK-FAILURE-CANARY")


def _app(audit_sink: RecordingAuditSink | FailingAuditSink | None = None) -> FastAPI:
    return create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            cookie_secure=True,
            allowed_hosts=("localhost",),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        clock=lambda: NOW,
        audit_sink=audit_sink,
    )


@pytest.mark.asyncio
async def test_local_session_creation_and_revocation_emit_privacy_preserving_events() -> None:
    sink = RecordingAuditSink()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(sink)),
        base_url="https://localhost",
    ) as client:
        login = await client.post(
            "/api/v1/auth/local-session",
            headers={"X-Correlation-ID": "local-session-create"},
        )
        cookie = client.cookies.get(SESSION_COOKIE)
        csrf = login.json()["csrf_token"]
        logout = await client.post(
            "/api/v1/auth/logout",
            headers={
                "X-Correlation-ID": "local-session-revoke",
                "X-CSRF-Token": csrf,
            },
        )

    assert login.status_code == 201
    assert logout.status_code == 204
    assert [event.action for event in sink.events] == [
        SecurityAuditAction.LOCAL_SESSION_CREATED,
        SecurityAuditAction.SESSION_REVOKED,
    ]
    assert [event.outcome for event in sink.events] == [
        SecurityAuditOutcome.SUCCEEDED,
        SecurityAuditOutcome.SUCCEEDED,
    ]
    assert [event.authentication_method for event in sink.events] == [
        AuthenticationMethod.LOCAL_SYNTHETIC,
        AuthenticationMethod.SESSION,
    ]
    assert [event.correlation_id for event in sink.events] == [
        "local-session-create",
        "local-session-revoke",
    ]
    assert all(event.actor_ref and event.actor_ref.startswith("sha256:") for event in sink.events)
    assert all(event.owner_ref and event.owner_ref.startswith("sha256:") for event in sink.events)

    rendered = repr(sink.events)
    assert csrf not in rendered
    assert cookie is not None and cookie not in rendered
    assert LOCAL_SYNTHETIC_PRINCIPAL_ID not in rendered
    assert LOCAL_SYNTHETIC_OWNER_ID not in rendered


@pytest.mark.asyncio
async def test_denial_audits_never_capture_credentials_or_resource_ids() -> None:
    sink = RecordingAuditSink()
    hostile_account_id = "private-account-canary"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(sink)),
        base_url="https://localhost",
    ) as client:
        authentication_denied = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary",
            headers={
                "Authorization": f"Bearer {TOKEN_CANARY}",
                "X-Correlation-ID": "authentication-denial",
            },
        )
        login = await client.post("/api/v1/auth/local-session")
        authorization_denied = await client.get(
            f"/api/v1/accounts/{hostile_account_id}/summary",
            headers={"X-Correlation-ID": "authorization-denial"},
        )
        csrf_denied = await client.post(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/refresh",
            headers={
                "X-Correlation-ID": "csrf-denial",
                "X-CSRF-Token": CSRF_CANARY,
                "X-Idempotency-Key": "audit-negative",
            },
            json={},
        )

    assert authentication_denied.status_code == 401
    assert login.status_code == 201
    assert authorization_denied.status_code == 403
    assert csrf_denied.status_code == 401

    denied = [
        event
        for event in sink.events
        if event.action
        in {SecurityAuditAction.AUTHENTICATION_DENIED, SecurityAuditAction.AUTHORIZATION_DENIED}
    ]
    assert [(event.action, event.authentication_method) for event in denied] == [
        (SecurityAuditAction.AUTHENTICATION_DENIED, AuthenticationMethod.BEARER),
        (SecurityAuditAction.AUTHORIZATION_DENIED, AuthenticationMethod.SESSION),
        (SecurityAuditAction.AUTHENTICATION_DENIED, AuthenticationMethod.SESSION),
    ]
    assert [event.operation for event in denied] == [
        "account_summary",
        "account_summary",
        "refresh_account",
    ]
    assert denied[0].actor_ref is None
    assert denied[0].owner_ref is None
    assert denied[1].actor_ref is not None
    assert denied[1].owner_ref is not None

    rendered = repr(sink.events)
    assert TOKEN_CANARY not in rendered
    assert CSRF_CANARY not in rendered
    assert hostile_account_id not in rendered
    assert SESSION_COOKIE not in rendered
    assert LOCAL_SYNTHETIC_PRINCIPAL_ID not in rendered
    assert LOCAL_SYNTHETIC_OWNER_ID not in rendered


@pytest.mark.asyncio
async def test_audit_sink_failure_does_not_weaken_authentication_denial(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("ERROR", logger="trading212_api.security_audit")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(FailingAuditSink())),
        base_url="https://localhost",
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary",
            headers={"Authorization": f"Bearer {TOKEN_CANARY}"},
        )

    assert response.status_code == 401
    assert "security_audit_delivery_failed" in caplog.text
    assert TOKEN_CANARY not in caplog.text
    assert "API-AUDIT-SINK-FAILURE-CANARY" not in caplog.text


@pytest.mark.asyncio
async def test_default_structured_audit_log_is_redacted_and_schema_bounded() -> None:
    configure_logging(
        service="api-audit-test",
        secret_canaries=(TOKEN_CANARY, CSRF_CANARY),
    )
    output = io.StringIO()
    with redirect_stdout(output):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()),
            base_url="https://localhost",
        ) as client:
            response = await client.get(
                f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary",
                headers={"Authorization": f"Bearer {TOKEN_CANARY}"},
            )

    rendered = output.getvalue()
    assert response.status_code == 401
    assert "security_audit_event" in rendered
    assert '"audit_action": "authentication.denied"' in rendered
    assert '"authentication_method": "bearer"' in rendered
    assert TOKEN_CANARY not in rendered
    assert CSRF_CANARY not in rendered
    assert "authorization" not in rendered.casefold()
    assert "cookie" not in rendered.casefold()
