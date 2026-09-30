"""Closed aggregate ports and current authorization before parsing/conditional output."""

from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_application import aggregation as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain.aggregation_codec import aggregation_record_digest
from trading212_domain.serialization import to_primitive
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.analytics.test_aggregation import NOW, holdings

pytestmark = pytest.mark.unit
ID = UUID(int=99)
HEADERS = {"Authorization": "Bearer aggregate-test", "X-Idempotency-Key": "aggregate-command"}


class Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "aggregate-test"
        return Principal(
            str(ID),
            str(UUID(int=90)),
            "aggregate-test",
            "aggregate-test",
            self.scopes,
            NOW - timedelta(minutes=1),
            NOW + timedelta(hours=1),
        )


def application(scopes: frozenset[Scope] = app.AGGREGATE_WRITE_SCOPES) -> tuple[FastAPI, AsyncMock]:
    service = AsyncMock(spec=app.AggregateService)
    content = holdings().selection
    selected = app.AggregateSelectionView(
        selection_id=ID,
        content=content,
        content_digest=aggregation_record_digest(content),
        revision=1,
        created_at=NOW,
    )
    service.create_selection.return_value = service.get_selection.return_value = selected
    service.list_selections.return_value = Page(
        items=(selected,), next_cursor=None, limit=25, total=1
    )
    service.list_runs.return_value = Page(items=(), next_cursor=None, limit=25, total=0)
    service.create_run.return_value = app.AggregateRunReceipt(
        run_id=UUID(int=100),
        selection_id=ID,
        selection_revision=2,
        holdings_input_digest="a" * 64,
        holdings_result_digest="b" * 64,
        activity_input_digest=None,
        activity_result_digest=None,
        activity_requested=False,
        state="succeeded",
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    api = create_app(
        service=SyntheticPortfolioService(clock=lambda: NOW),
        aggregate_service=cast(app.AggregateService, service),
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
            allowed_origins=("https://testserver",),
            local_synthetic_auth_enabled=True,
        ),
        bearer_authenticator=Bearer(scopes),
        clock=lambda: NOW,
    )
    return api, service


async def test_current_selection_etag_cannot_bypass_service_denial() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        current = await client.get(f"/api/v1/aggregate-selections/{ID}", headers=HEADERS)
        assert current.status_code == 200
        conditional = await client.get(
            f"/api/v1/aggregate-selections/{ID}",
            headers={**HEADERS, "If-None-Match": current.headers["etag"]},
        )
        assert conditional.status_code == 304 and not conditional.content
        service.get_selection.side_effect = app.AggregateServiceError(
            app.AggregateErrorCode.ACCESS_DENIED
        )
        denied = await client.get(
            f"/api/v1/aggregate-selections/{ID}",
            headers={**HEADERS, "If-None-Match": current.headers["etag"]},
        )
        assert denied.status_code == 403


async def test_two_commands_have_explicit_content_ids_and_current_if_match() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        selected = await client.post(
            "/api/v1/aggregate-selections",
            headers=HEADERS,
            json={"content": to_primitive(holdings().selection)},
        )
        assert selected.status_code == 201
        for header, status in (
            (None, 428),
            ('"wrong"', 422),
            (f'"{UUID(int=101)}:1"', 412),
            (f'"{ID}:1"', 201),
        ):
            headers = HEADERS if header is None else {**HEADERS, "If-Match": header}
            response = await client.post(
                f"/api/v1/aggregate-selections/{ID}/runs",
                headers=headers,
                json={"fx_bindings": [], "activity_window": None},
            )
            assert response.status_code == status
        service.create_run.assert_awaited_once()
        assert service.create_run.call_args.args[1].expected_revision == 1
        forged = await client.post(
            f"/api/v1/aggregate-selections/{ID}/runs",
            headers={**HEADERS, "If-Match": f'"{ID}:1"'},
            json={"fx_bindings": [], "amount": "999"},
        )
        assert forged.status_code == 422


async def test_missing_scope_rejects_invalid_body_before_admission() -> None:
    api, service = application(frozenset({Scope.PORTFOLIO_READ}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="https://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/aggregate-selections",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=b"{" * 70000,
        )
    assert response.status_code == 403
    service.create_selection.assert_not_awaited()


def test_six_operations_four_paths_remain_exact() -> None:
    api, _ = application()
    actual = {
        (method, path, operation["operationId"])
        for path, methods in api.openapi()["paths"].items()
        for method, operation in methods.items()
        if "aggregate" in operation.get("tags", [])
    }
    from trading212_api_contracts.aggregation_typescript import AGGREGATE_OPERATIONS

    assert actual == AGGREGATE_OPERATIONS
    assert len({path for _, path, _ in actual}) == 4
