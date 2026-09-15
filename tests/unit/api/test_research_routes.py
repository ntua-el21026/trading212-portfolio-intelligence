"""Research HTTP adapters preserve exact ports, current authority and inert prose."""

from dataclasses import replace
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import research as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.domain.research_factories import (
    AT,
    acknowledgment,
    event,
    note,
    pin,
    portfolio,
    uid,
)

pytestmark = pytest.mark.unit
ORIGIN = "https://testserver"
SCOPES = app.RESEARCH_WRITE_SCOPES
HEADERS = {"Authorization": "Bearer synthetic-research-test", "X-Idempotency-Key": "research-one"}
ACCOUNT, ITEM = uid(2), uid(85000)
EVENT, NOTE = event(), note(event())
SUMMARY_QUERY = {"xray_run_id": str(pin().run_id), "source_cutoff_at": AT.isoformat()}


def item() -> app.ResearchItemView:
    return app.ResearchItemView(
        item_id=ITEM,
        source_cutoff_at=AT,
        source=EVENT,
        portfolio=app.preview_research_portfolio(portfolio(EVENT, "100.000000000000000001")),
        owner_revisions=(NOTE,),
        review=acknowledgment(EVENT),
    )


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "synthetic-research-test"
        return Principal(
            "research-test", str(uid(1)), "test", "test", self.scopes, AT, AT + timedelta(hours=1)
        )


def application(
    scopes: frozenset[Scope] = SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.ResearchService)
    service.get_research_summary.return_value = app.ResearchSummary(
        pin=pin(),
        source_cutoff_at=AT,
        items=(item(),),
        next_cursor=None,
        limit=25,
        total=1,
        unknown_exposure_total=0,
    )
    service.get_research_item.return_value = item()
    service.list_research_notes.return_value = Page((NOTE,), None, 25, 1)
    service.create_research_note.return_value = service.get_research_note.return_value = NOTE
    service.list_research_note_versions.return_value = Page((NOTE,), None, 25, 1)
    service.create_research_note_version.return_value = replace(
        NOTE, revision_id=uid(72), revision=2, previous_revision_id=NOTE.revision_id
    )
    service.review_research_event.return_value = acknowledgment(EVENT)
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
            local_synthetic_auth_enabled=True,
        ),
        service=SyntheticPortfolioService(clock=lambda: AT),
        research_service=cast(app.ResearchService, service) if available else None,
        bearer_authenticator=Bearer(scopes),
        clock=lambda: AT,
    )
    return api, service


OPERATIONS = (
    ("get", f"/accounts/{ACCOUNT}/research", "get_research_summary", 200),
    ("get", f"/research/items/{ITEM}", "get_research_item", 200),
    ("get", f"/accounts/{ACCOUNT}/research/notes", "list_research_notes", 200),
    ("post", f"/accounts/{ACCOUNT}/research/notes", "create_research_note", 201),
    ("get", f"/research/notes/{NOTE.note_id}", "get_research_note", 200),
    ("get", f"/research/notes/{NOTE.note_id}/versions", "list_research_note_versions", 200),
    ("post", f"/research/notes/{NOTE.note_id}/versions", "create_research_note_version", 201),
    ("post", f"/research/events/{EVENT.event_id}/review", "review_research_event", 200),
)


def body(name: str) -> dict[str, Any] | None:
    if name == "create_research_note":
        return {"entity_id": str(EVENT.entity_id), "content": to_primitive(NOTE.content)}
    if name == "create_research_note_version":
        return {"content": to_primitive(NOTE.content)}
    if name == "review_research_event":
        return {"revision_id": str(EVENT.revision_id), "revision_digest": EVENT.content_digest}
    return None


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_all_eight_operations_delegate_exact_owned_ports(
    method: str, path: str, name: str, status: int
) -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.request(
            method,
            "/api/v1" + path,
            json=body(name),
            params=SUMMARY_QUERY if name == "get_research_summary" else None,
            headers={**HEADERS, "If-Match": f'"{NOTE.note_id}:1"'},
        )
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert len(service.mock_calls) == 1
    operation = getattr(service, name)
    principal = operation.call_args.args[0]
    assert (
        principal.owner_id == str(uid(1))
        and principal.principal_id == "research-test"
        and principal.subject == "test"
    )
    if method == "post":
        command = operation.call_args.args[1]
        assert command.idempotency_key == "research-one" and command.correlation_id
        if name != "review_research_event":
            assert command.content == NOTE.content
            assert response.json()["content_digest"] == operation.return_value.content_digest
        if name == "create_research_note":
            assert (command.account_id, command.entity_id) == (ACCOUNT, EVENT.entity_id)
        if name == "create_research_note_version":
            assert command.note_id == NOTE.note_id and command.expected_revision == 1
            assert response.headers["etag"] == f'"{NOTE.note_id}:2"'
        if name == "review_research_event":
            assert (command.event_id, command.revision_id, command.revision_digest) == (
                EVENT.event_id,
                EVENT.revision_id,
                EVENT.content_digest,
            )
    elif name == "get_research_summary":
        query = operation.call_args.args[1]
        assert query == app.ResearchSummaryQuery(
            account_id=ACCOUNT, xray_run_id=pin().run_id, source_cutoff_at=AT
        )
    elif name == "get_research_item":
        assert operation.call_args.args[1] == ITEM and not operation.call_args.kwargs


async def test_complete_item_keeps_exact_source_digests_clocks_and_financial_strings() -> None:
    api, _ = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/research/items/{ITEM}", headers=HEADERS)
    assert response.status_code == 200
    value = response.json()
    assert value["source"]["content_digest"] == EVENT.content_digest
    citation = value["source"]["citations"][0]
    assert citation["content_digest"] == EVENT.citations[0].content_digest
    assert citation["source"]["content_digest"] == EVENT.citations[0].source.content_digest
    assert citation["source"]["license"] == to_primitive(EVENT.citations[0].source.license)
    assert value["portfolio"]["effective_exposure"] == {
        "amount": "100.000000000000000001",
        "currency": "EUR",
    }
    assert value["portfolio"]["canonical_facts_digest"] == item().portfolio.canonical_facts_digest
    assert value["owner_revisions"][0]["content_digest"] == NOTE.content_digest
    assert value["synthesis"] == {
        "availability": "unavailable",
        "reason": "disabled",
        "content_type": "optional_synthesis",
    }
    assert value["review"]["revision_digest"] == EVENT.content_digest


@pytest.mark.parametrize("method,path,name,status", OPERATIONS)
async def test_auth_and_all_read_scopes_precede_body_query_and_resource_parsing(
    method: str, path: str, name: str, status: int
) -> None:
    for scopes, headers, expected in (
        (SCOPES, {}, 401),
        *((SCOPES - {scope}, HEADERS, 403) for scope in app.RESEARCH_READ_SCOPES),
    ):
        api, service = application(scopes)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
            response = await client.request(
                method,
                "/api/v1" + path + "?private-canary=hidden",
                content=b"invalid-json",
                headers=headers,
            )
        assert response.status_code == expected and not service.mock_calls
        assert "canary" not in response.text


@pytest.mark.parametrize(
    "method,path,name,status", [entry for entry in OPERATIONS if entry[0] == "post"]
)
async def test_research_write_is_required_without_replacing_read_scopes(
    method: str, path: str, name: str, status: int
) -> None:
    api, service = application(app.RESEARCH_READ_SCOPES)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post("/api/v1" + path, content=b"broken", headers=HEADERS)
    assert response.status_code == 403 and not service.mock_calls


@pytest.mark.parametrize(
    "revision,status",
    [(None, 428), ('W/"old"', 422), ('"{id}:513"', 422), ('"{id}:01"', 422), (f'"{ITEM}:1"', 412)],
)
async def test_note_versions_require_exact_matching_revision(
    revision: str | None, status: int
) -> None:
    api, service = application()
    header = None if revision is None else revision.replace("{id}", str(NOTE.note_id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.post(
            f"/api/v1/research/notes/{NOTE.note_id}/versions",
            json=body("create_research_note_version"),
            headers={**HEADERS, **({"If-Match": header} if header is not None else {})},
        )
    assert response.status_code == status and not service.mock_calls


@pytest.mark.parametrize(
    "name,path",
    [
        ("get_research_summary", f"/accounts/{ACCOUNT}/research"),
        ("get_research_item", f"/research/items/{ITEM}"),
        ("get_research_note", f"/research/notes/{NOTE.note_id}"),
    ],
)
async def test_current_service_denial_precedes_conditional_304(name: str, path: str) -> None:
    api, service = application()
    params = SUMMARY_QUERY if name == "get_research_summary" else None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        first = await client.get("/api/v1" + path, params=params, headers=HEADERS)
        same = await client.get(
            "/api/v1" + path,
            params=params,
            headers={**HEADERS, "If-None-Match": first.headers["etag"]},
        )
        assert first.status_code == 200 and same.status_code == 304
        assert getattr(service, name).await_count == 2
        getattr(service, name).side_effect = app.ResearchServiceError(
            app.ResearchErrorCode.SOURCE_UNAVAILABLE, "private-capability-canary"
        )
        denied = await client.get(
            "/api/v1" + path, params=params, headers={**HEADERS, "If-None-Match": "*"}
        )
    assert denied.status_code == 503 and denied.headers["cache-control"] == "private, no-store"
    assert "canary" not in denied.text and denied.json()["error"]["retryable"] is True


@pytest.mark.parametrize(
    "code,status",
    [
        (app.ResearchErrorCode.NOT_FOUND, 404),
        (app.ResearchErrorCode.ACCESS_DENIED, 403),
        (app.ResearchErrorCode.CONFLICT, 409),
        (app.ResearchErrorCode.CURSOR_INVALID, 400),
        (app.ResearchErrorCode.RATE_LIMITED, 429),
    ],
)
async def test_service_errors_are_fixed_and_do_not_reflect_prose(
    code: app.ResearchErrorCode, status: int
) -> None:
    api, service = application()
    service.get_research_item.side_effect = app.ResearchServiceError(code, "private-owner-canary")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/research/items/{ITEM}", headers={**HEADERS, "If-None-Match": "*"}
        )
    assert response.status_code == status and "canary" not in response.text
    if status == 429:
        assert response.headers["retry-after"] == "60"


@pytest.mark.parametrize(
    "query,expected_status",
    [
        ("limit=0", 422),
        ("limit=101", 422),
        ("limit=true", 422),
        ("limit=1&limit=2", 422),
        ("cursor=" + "x" * 2049, 400),
        ("cursor=a&cursor=b", 422),
        ("private-canary=hidden", 422),
        ("event_kind=price", 422),
        ("review_state=latest", 422),
        ("source_cutoff_at=2026-09-15", 422),
    ],
)
async def test_summary_selectors_are_closed_before_service(
    query: str, expected_status: int
) -> None:
    api, service = application()
    params = str(httpx.QueryParams(SUMMARY_QUERY)) + "&" + query
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/research?{params}", headers=HEADERS
        )
    assert (
        response.status_code == expected_status
        and not service.mock_calls
        and "canary" not in response.text
    )


async def test_body_headers_identifiers_and_utf8_byte_bound_fail_closed() -> None:
    api, service = application()
    path = f"/api/v1/accounts/{ACCOUNT}/research/notes"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        for changes in (
            {"owner_id": str(uid(1))},
            {"url": "https://private-canary.invalid"},
            {"entity_id": True},
        ):
            response = await client.post(
                path,
                json={**cast(dict[str, Any], body("create_research_note")), **changes},
                headers=HEADERS,
            )
            assert response.status_code == 422 and "canary" not in response.text
        for key in (None, "", "x" * 181):
            response = await client.post(
                path,
                json=body("create_research_note"),
                headers={
                    "Authorization": HEADERS["Authorization"],
                    **({"X-Idempotency-Key": key} if key is not None else {}),
                },
            )
            assert response.status_code == 422
        for header in ("X-Idempotency-Key", "If-Match", "If-None-Match", "Origin", "X-CSRF-Token"):
            response = await client.post(
                path,
                json=body("create_research_note"),
                headers=[*HEADERS.items(), (header, "one"), (header, "two")],
            )
            assert response.status_code == 422
        for identifier in ("not-a-uuid", str(ACCOUNT).replace("-", ""), "{" + str(ACCOUNT) + "}"):
            response = await client.get(
                f"/api/v1/accounts/{identifier}/research/notes", headers=HEADERS
            )
            assert response.status_code == 422
        response = await client.post(
            path,
            content=("€" * 22000).encode(),
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        assert response.status_code == 413
    assert not service.mock_calls


async def test_cookie_commands_require_actual_csrf_and_configured_origin() -> None:
    api, service = application()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        assert session.status_code == 201
        csrf = session.json()["csrf_token"]
        for headers in (
            {"X-Idempotency-Key": "session-one"},
            {
                "X-Idempotency-Key": "session-one",
                "X-CSRF-Token": csrf,
                "Origin": "https://foreign.invalid",
            },
        ):
            response = await client.post(
                f"/api/v1/accounts/{ACCOUNT}/research/notes",
                json=body("create_research_note"),
                headers=headers,
            )
            assert response.status_code == 401 and not service.mock_calls
        accepted = await client.post(
            f"/api/v1/accounts/{ACCOUNT}/research/notes",
            json=body("create_research_note"),
            headers={"X-Idempotency-Key": "session-one", "X-CSRF-Token": csrf, "Origin": ORIGIN},
        )
    assert accepted.status_code == 201 and service.create_research_note.await_count == 1


async def test_missing_concrete_service_has_explicit_unavailable_response() -> None:
    api, service = application(available=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        response = await client.get(f"/api/v1/research/items/{ITEM}", headers=HEADERS)
    assert response.status_code == 503 and not service.mock_calls
