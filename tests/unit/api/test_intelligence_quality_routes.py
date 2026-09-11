"""Bounded intelligence quality route authorization and schemas."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from pydantic import ValidationError
from trading212_api.intelligence_quality_routes import register_intelligence_quality_routes
from trading212_api.target_routes import _error
from trading212_api_contracts import intelligence_quality as wire
from trading212_application import intelligence_quality as q
from trading212_domain.serialization import to_primitive
from trading212_persistence.intelligence_quality_projection import empty_metrics
from trading212_security.principals import AuthenticationError, AuthorizationError, Principal, Scope

NOW = datetime(2026, 9, 11, tzinfo=UTC)
ACCOUNT = uuid4()


def value() -> q.IntelligenceDataQuality:
    return q.IntelligenceDataQuality(
        account_id=ACCOUNT,
        analytics_kind=q.IntelligenceKind.VALUATION,
        checked_at=NOW,
        selection_at=NOW,
        selection=None,
        selection_state="not_available",
        metrics=empty_metrics(q.IntelligenceKind.VALUATION, q.QualityReason.NOT_CALCULATED),
        reconciliation=q.QualityReconciliation(visibility="permission_required"),
        sources=q.QualitySourcePage(
            items=(), exact_total=0, limit=25, next_cursor=None, expires_at=None
        ),
        activity_visibility="permission_required",
        targets_visibility="permission_required",
    )


def application(
    scopes: frozenset[Scope] = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
) -> tuple[FastAPI, AsyncMock]:
    api = FastAPI()
    service = AsyncMock(spec=q.IntelligenceDataQualityService)
    service.get_intelligence_data_quality.return_value = value()
    principal = Principal(
        str(uuid4()),
        str(uuid4()),
        "quality-test",
        "owner",
        scopes,
        NOW - timedelta(seconds=1),
        NOW + timedelta(hours=1),
    )

    async def authenticate(request: Request) -> Principal:
        if request.headers.get("Authorization") != "Bearer quality-test":
            raise AuthenticationError("Authentication is required.")
        return principal

    @api.exception_handler(AuthenticationError)
    async def unauthenticated(request: Request, error: Exception) -> Response:
        return _error(request, 401, "AUTHENTICATION_REQUIRED", "Authentication is required.")

    @api.exception_handler(AuthorizationError)
    async def forbidden(request: Request, error: Exception) -> Response:
        return _error(request, 403, "ACCESS_DENIED", "Access denied.")

    context = SimpleNamespace(intelligence_quality_service=service, clock=lambda: NOW)
    register_intelligence_quality_routes(api, authenticate, lambda request: context)
    return api, service


async def test_fixed_route_baseline_auth_query_and_no_conditional_cache() -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/intelligence-data-quality",
            headers={"Authorization": "Bearer quality-test", "If-None-Match": "*"},
        )
    assert response.status_code == 200
    assert (
        response.headers["cache-control"] == "private, no-store" and "etag" not in response.headers
    )
    assert (
        service.get_intelligence_data_quality.call_args.kwargs["query"]
        == q.IntelligenceDataQualityQuery()
    )
    assert response.json()["activity_visibility"] == "permission_required"
    operation = api.openapi()["paths"]["/api/v1/accounts/{account_id}/intelligence-data-quality"][
        "get"
    ]
    assert operation["operationId"] == "get_intelligence_data_quality"
    assert operation["tags"] == ["sources", "intelligence-quality"]


@pytest.mark.parametrize(
    "query",
    (
        "analytics_kind=all",
        "table=analytics_runs",
        "limit=0",
        "limit=101",
        "limit=1&limit=2",
        "analytics_kind=valuation&analytics_kind=income",
        "cursor=" + "x" * 2049,
    ),
)
async def test_strict_query_fails_without_calling_service(query: str) -> None:
    api, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/intelligence-data-quality?{query}",
            headers={"Authorization": "Bearer quality-test"},
        )
    assert response.status_code == 422
    service.get_intelligence_data_quality.assert_not_awaited()


@pytest.mark.parametrize(
    ("scopes", "headers", "status"),
    (
        (frozenset(Scope), {}, 401),
        (frozenset({Scope.PORTFOLIO_READ}), {"Authorization": "Bearer quality-test"}, 403),
    ),
)
async def test_auth_precedes_malformed_account_or_query(
    scopes: frozenset[Scope], headers: dict[str, str], status: int
) -> None:
    api, service = application(scopes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/accounts/not-a-uuid/intelligence-data-quality?analytics_kind=all",
            headers=headers,
        )
    assert response.status_code == status
    service.get_intelligence_data_quality.assert_not_awaited()


def test_wire_rejects_reordering_duplicates_cross_family_and_unknown_fields() -> None:
    data = to_primitive(value())
    wire.IntelligenceDataQuality.model_validate(data)
    for mutation in ("order", "duplicate", "family", "extra"):
        bad = to_primitive(value())
        if mutation == "order":
            bad["metrics"].reverse()
        elif mutation == "duplicate":
            bad["metrics"][1] = bad["metrics"][0]
        elif mutation == "family":
            bad["metrics"][0]["key"] = "ending_value"
        else:
            bad["protected_source_count"] = 17
        with pytest.raises(ValidationError):
            wire.IntelligenceDataQuality.model_validate(bad)


async def test_permission_branch_is_constant_and_has_no_hidden_counts_or_identity_fields() -> None:
    api, service = application()
    service.get_intelligence_data_quality.return_value = q.IntelligenceQualityPermissionRequired(
        account_id=ACCOUNT,
        analytics_kind=q.IntelligenceKind.INCOME,
        checked_at=NOW,
        missing_scope=Scope.ACTIVITY_READ,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/intelligence-data-quality?analytics_kind=income",
            headers={"Authorization": "Bearer quality-test"},
        )
    assert response.status_code == 200
    assert set(response.json()) == {
        "state",
        "account_id",
        "analytics_kind",
        "checked_at",
        "missing_scope",
        "supported_kinds",
    }


async def test_transport_enforces_output_byte_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    api, _ = application()
    monkeypatch.setattr(q, "MAX_QUALITY_BYTES", 100)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/intelligence-data-quality",
            headers={"Authorization": "Bearer quality-test"},
        )
    assert response.status_code == 422 and response.json()["error"]["code"] == "RESULT_TOO_LARGE"
