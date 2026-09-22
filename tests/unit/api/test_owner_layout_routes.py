"""Five exact owner-preference ports, early auth/CSRF bounds and current conditional reads."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import owner_layouts as app
from trading212_application.services import SyntheticPortfolioService
from trading212_domain.owner_layout_codec import owner_layout_digest
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.domain.test_owner_layouts import AT, content

pytestmark = pytest.mark.unit
ID, VERSION = UUID(int=41), UUID(int=42)
HEADERS = {"Authorization": "Bearer layout-test", "X-Idempotency-Key": "layout-command-1"}


def view() -> app.OwnerLayoutView:
    version = app.OwnerLayoutVersionHeader(
        id=VERSION, number=1, created_at=AT, content_digest=owner_layout_digest(content())
    )
    return app.OwnerLayoutView(
        id=ID, revision=1, state="active", version=version, content=content(), versions=(version,)
    )


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "layout-test"
        return Principal(
            "layout-test",
            str(UUID(int=1)),
            "test-layouts",
            "test-layouts",
            self.scopes,
            AT,
            AT + timedelta(hours=1),
        )


def application(scopes: frozenset[Scope] = app.LAYOUT_WRITE_SCOPES) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.OwnerLayoutService)
    service.create_owner_layout.return_value = service.update_owner_layout.return_value = (
        service.get_owner_layout.return_value
    ) = view()
    service.list_owner_layouts.return_value = app.OwnerLayoutPage(
        items=(), total=0, limit=25, next_cursor=None, read_cutoff_at=AT
    )
    service.archive_owner_layout.return_value = app.OwnerLayoutArchiveReceipt(
        id=ID, revision=2, state="archived", archived_at=AT
    )
    api = create_app(
        service=SyntheticPortfolioService(clock=lambda: AT),
        owner_layout_service=cast(app.OwnerLayoutService, service),
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=("https://testserver",),
            local_synthetic_auth_enabled=True,
        ),
        bearer_authenticator=Bearer(scopes),
        clock=lambda: AT,
    )
    return api, service


@pytest.mark.parametrize(
    "method,path,operation,status",
    [
        ("GET", "/preferences/layouts", "list_owner_layouts", 200),
        ("GET", f"/preferences/layouts/{ID}", "get_owner_layout", 200),
        ("POST", "/preferences/layouts", "create_owner_layout", 201),
        ("PATCH", f"/preferences/layouts/{ID}", "update_owner_layout", 200),
        ("POST", f"/preferences/layouts/{ID}/archive", "archive_owner_layout", 200),
    ],
)
async def test_exact_owner_ports_without_invented_account(
    method: str, path: str, operation: str, status: int
) -> None:
    api, service = application()
    body = (
        {"content": to_primitive(content())}
        if operation in {"create_owner_layout", "update_owner_layout"}
        else {}
        if method == "POST"
        else None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        response = await client.request(
            method, "/api/v1" + path, headers={**HEADERS, "If-Match": f'"{ID}:1"'}, json=body
        )
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    selected = getattr(service, operation)
    selected.assert_awaited_once()
    assert selected.call_args.args[0].scopes == app.LAYOUT_WRITE_SCOPES
    if operation in {"create_owner_layout", "update_owner_layout"}:
        assert selected.call_args.args[1].content == content()


@pytest.mark.parametrize(
    "scopes",
    [
        frozenset({Scope.PREFERENCES_WRITE}),
        frozenset({Scope.PREFERENCES_READ}),
        frozenset({Scope.PORTFOLIO_READ}),
    ],
)
async def test_write_does_not_imply_read_and_scope_rejection_precedes_body(
    scopes: frozenset[Scope],
) -> None:
    api, service = application(scopes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/preferences/layouts", headers=HEADERS, content=b"{" + b"x" * 65537
        )
    assert response.status_code == 403
    service.create_owner_layout.assert_not_awaited()


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, 428),
        ({"If-Match": '"other:1"'}, 422),
        ({"If-Match": f'"{UUID(int=99)}:1"'}, 412),
        ({"If-Match": f'"{ID}:130"'}, 422),
    ],
)
async def test_update_requires_exact_closed_revision(
    headers: dict[str, str], expected: int
) -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        response = await client.patch(
            f"/api/v1/preferences/layouts/{ID}",
            headers={**HEADERS, **headers},
            json={"content": to_primitive(content())},
        )
    assert response.status_code == expected
    service.update_owner_layout.assert_not_awaited()


async def test_authorization_rechecked_before304_and_history_response_has_distinct_etag() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        first = await client.get(f"/api/v1/preferences/layouts/{ID}", headers=HEADERS)
        assert first.headers["etag"] == f'"{ID}:1"'
        same = await client.get(
            f"/api/v1/preferences/layouts/{ID}",
            headers={**HEADERS, "If-None-Match": first.headers["etag"]},
        )
        assert same.status_code == 304
        service.get_owner_layout.side_effect = app.OwnerLayoutServiceError(
            app.OwnerLayoutErrorCode.ACCESS_DENIED
        )
        denied = await client.get(
            f"/api/v1/preferences/layouts/{ID}",
            headers={**HEADERS, "If-None-Match": first.headers["etag"]},
        )
        assert denied.status_code == 403 and "widgets" not in denied.text
    assert service.get_owner_layout.await_count == 3
    original = view()
    newest = replace(
        original.version, id=UUID(int=43), number=2, created_at=AT + timedelta(microseconds=1)
    )
    service.get_owner_layout.side_effect = None
    service.get_owner_layout.return_value = replace(
        original, revision=2, versions=(original.version, newest)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        historical = await client.get(
            f"/api/v1/preferences/layouts/{ID}?version_id={VERSION}", headers=HEADERS
        )
    assert historical.status_code == 200
    assert historical.headers["etag"] not in {f'"{ID}:1"', f'"{ID}:2"'}
    assert historical.json()["version"]["id"] == str(VERSION)


async def test_repeated_selectors_unknown_fields_and_body_limit_fail_closed() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        for query in ("cursor=a&cursor=b", "account_id=secret", "include_archived=1", "limit=101"):
            response = await client.get("/api/v1/preferences/layouts?" + query, headers=HEADERS)
            assert response.status_code in {400, 422}
        for extra in ("query", "url", "token", "financial_value"):
            body = {"content": {**to_primitive(content()), extra: "never reflect this"}}
            response = await client.post("/api/v1/preferences/layouts", headers=HEADERS, json=body)
            assert response.status_code == 422 and "never reflect this" not in response.text
        large = await client.post(
            "/api/v1/preferences/layouts", headers=HEADERS, content=b" " * 65537
        )
        assert large.status_code == 413
    service.list_owner_layouts.assert_not_awaited()
    service.create_owner_layout.assert_not_awaited()


async def test_session_commands_reject_missing_or_foreign_csrf_before_body() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        session = await client.post("/api/v1/auth/local-session")
        assert session.status_code == 201
        csrf = session.json()["csrf_token"]
        for headers in (
            {"X-Idempotency-Key": "once"},
            {
                "X-Idempotency-Key": "once",
                "X-CSRF-Token": csrf,
                "Origin": "https://foreign.invalid",
            },
        ):
            denied = await client.post(
                "/api/v1/preferences/layouts", content=b"{" + b"x" * 65537, headers=headers
            )
            assert denied.status_code == 401
            service.create_owner_layout.assert_not_awaited()
        accepted = await client.post(
            "/api/v1/preferences/layouts",
            json={"content": to_primitive(content())},
            headers={
                "X-Idempotency-Key": "once",
                "X-CSRF-Token": csrf,
                "Origin": "https://testserver",
            },
        )
        assert accepted.status_code == 201
        duplicate = await client.post(
            "/api/v1/preferences/layouts",
            content=b"{",
            headers=[
                ("Authorization", "Bearer layout-test"),
                ("X-Idempotency-Key", "first"),
                ("X-Idempotency-Key", "second"),
            ],
        )
        assert duplicate.status_code == 422
    assert service.create_owner_layout.await_count == 1


@pytest.mark.parametrize("schema_version", [True, False, 1.0, "1", 2])
async def test_layout_schema_version_rejects_coercion(schema_version: object) -> None:
    api, service = application()
    body = {"content": {**to_primitive(content()), "schema_version": schema_version}}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        response = await client.post("/api/v1/preferences/layouts", headers=HEADERS, json=body)
    assert response.status_code == 422
    service.create_owner_layout.assert_not_awaited()
