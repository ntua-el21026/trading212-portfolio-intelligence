"""Source authorization order, bounded views and safe benchmark command transport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from trading212_api.main import create_app
from trading212_api.source_schemas import benchmark_content
from trading212_api_contracts import sources as wire
from trading212_application import sources as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain import sources as domain
from trading212_domain.enums import QualityState
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ORIGIN = "https://testserver"
ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
SOURCE = "19751815-c671-47c4-a42c-1e619a037234"
SNAPSHOT = "2f34c23a-3798-4d4a-9133-9cd47639dd37"
PROVIDER = "7cd43322-221c-4003-9bd3-ebd5bc97f99a"
LICENSE = "63ff03be-c9f5-49aa-aa3d-122b7c99900d"
DEFINITION = "858c4e1b-9df6-462d-9482-08f405d7e895"
VERSION = "1f0d0a41-8395-48b7-b6ca-0ee93eebecfe"
ALL_SCOPES = frozenset({Scope.ANALYTICS_READ, Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ})
BODY: dict[str, Any] = {
    "name": "Synthetic benchmark",
    "content": {
        "reporting_currency": "EUR",
        "effective_at": "2026-09-07T12:00:00Z",
        "return_basis": "raw_close",
        "calendar_id": "weekday",
        "calendar_version": "v1",
        "rebalance_rule": "buy_and_hold",
        "components": [{"source_id": SOURCE, "weight": "1"}],
    },
}
OPERATIONS = [
    ("get_market_source_status", "GET", f"/api/v1/accounts/{ACCOUNT}/market-sources", None),
    ("get_fx_source_status", "GET", f"/api/v1/accounts/{ACCOUNT}/fx-sources", None),
    ("get_benchmark_source_status", "GET", f"/api/v1/accounts/{ACCOUNT}/benchmark-sources", None),
    ("get_price_snapshot", "GET", f"/api/v1/price-snapshots/{SNAPSHOT}", None),
    ("get_fx_snapshot", "GET", f"/api/v1/fx-snapshots/{SNAPSHOT}", None),
    ("get_benchmark_snapshot", "GET", f"/api/v1/benchmark-snapshots/{SNAPSHOT}", None),
    ("list_price_observations", "GET", f"/api/v1/price-snapshots/{SNAPSHOT}/observations", None),
    ("list_fx_observations", "GET", f"/api/v1/fx-snapshots/{SNAPSHOT}/observations", None),
    (
        "list_benchmark_observations",
        "GET",
        f"/api/v1/benchmark-snapshots/{SNAPSHOT}/observations",
        None,
    ),
    ("list_benchmark_definitions", "GET", "/api/v1/benchmark-definitions", None),
    ("create_benchmark_definition", "POST", "/api/v1/benchmark-definitions", BODY),
    ("get_benchmark_definition", "GET", f"/api/v1/benchmark-definitions/{DEFINITION}", None),
    (
        "create_benchmark_version",
        "POST",
        f"/api/v1/benchmark-definitions/{DEFINITION}/versions",
        {"content": BODY["content"]},
    ),
    (
        "archive_benchmark_definition",
        "POST",
        f"/api/v1/benchmark-definitions/{DEFINITION}/archive",
        {},
    ),
]


class _Bearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes

    async def authenticate(self, token: str) -> Principal:
        assert token == "source-test-token"
        return Principal(
            "source-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            self.scopes,
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )


def _definition() -> app.BenchmarkDefinitionDetailView:
    version = app.BenchmarkVersionView(
        id=VERSION,
        definition_id=DEFINITION,
        version_number=1,
        content=benchmark_content(wire.BenchmarkContent.model_validate(BODY["content"])),
        content_digest="a" * 64,
        published_at=NOW,
    )
    return app.BenchmarkDefinitionDetailView(
        definition=app.BenchmarkDefinitionSummaryView(
            id=DEFINITION,
            name="Synthetic benchmark",
            reporting_currency=CurrencyCode("EUR"),
            revision=1,
            state=app.BenchmarkDefinitionState.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            latest_version_id=VERSION,
            version_count=1,
        ),
        versions=Page((version,), None, 25, 1),
        selected_version=version,
    )


def _service() -> AsyncMock:
    service = AsyncMock(spec=app.SourceService)
    common: dict[str, Any] = {
        "id": SNAPSHOT,
        "content_digest": "b" * 64,
        "period": domain.SourcePeriod(start=date(2026, 9, 7), end=date(2026, 9, 7)),
        "provenance": domain.SourceProvenance(
            provider_id=PROVIDER,
            license_version_id=LICENSE,
            adapter_version="v1",
            schema_version="v1",
            source_revision="v1",
            revision_order=1,
            effective_at=NOW,
            first_observed_at=NOW,
            synthetic=True,
        ),
        "coverage": app.SourceCoverageView.from_coverage(
            domain.SourceCoverage(
                expected_count=1, available_count=1, gaps=(), quality=QualityState.FRESH
            )
        ),
        "license": domain.SourceLicense(
            id=LICENSE,
            provider_id=PROVIDER,
            version="v1",
            effective_at=NOW,
            store=domain.LicensePermission.ALLOWED,
            display=domain.LicensePermission.ALLOWED,
            report=domain.LicensePermission.DENIED,
            export=domain.LicensePermission.UNKNOWN,
            retention_days=365,
            attribution="Synthetic",
            evidence_key="synthetic-license",
        ),
        "latest_retrieval": None,
    }
    series = app.SourceSeriesView(
        id=SOURCE,
        provider_id=PROVIDER,
        license_version_id=LICENSE,
        kind=domain.SourceSeriesKind.BENCHMARK_LEVEL,
        provider_key="synthetic",
        mapping_version="v1",
        basis=domain.PriceBasis.RAW_CLOSE,
        currency=CurrencyCode("EUR"),
        calendar_id="weekday",
        calendar_version="v1",
    )
    service.get_benchmark_snapshot.return_value = app.BenchmarkSnapshotHeaderView(
        **common, series=series
    )
    service.get_fx_snapshot.return_value = app.FxSnapshotHeaderView(
        **common, calendar_id="weekday", calendar_version="v1"
    )
    service.get_price_snapshot.return_value = app.PriceSnapshotHeaderView(
        **common,
        series=replace(
            series,
            kind=domain.SourceSeriesKind.SECURITY_PRICE,
            mapping_id=SOURCE,
            instrument_id=VERSION,
        ),
    )
    service.get_market_source_status.return_value = app.MarketSourceStatusView(
        account_id=ACCOUNT, providers=(), series=Page((), None, 25, 0)
    )
    service.get_benchmark_source_status.return_value = app.BenchmarkSourceStatusView(
        account_id=ACCOUNT, providers=(), series=Page((), None, 25, 0)
    )
    service.get_fx_source_status.return_value = app.FxSourceStatusView(
        account_id=ACCOUNT, providers=(), pairs=Page((), None, 25, 0)
    )
    observation: dict[str, Any] = {"session_date": date(2026, 9, 7), "effective_at": NOW}
    service.list_price_observations.return_value = Page(
        (domain.PriceObservation(**observation, value=Decimal("125.000000000000000001")),),
        None,
        25,
        1,
    )
    service.list_fx_observations.return_value = Page(
        (
            domain.FxObservation(
                **observation,
                base=CurrencyCode("EUR"),
                quote=CurrencyCode("USD"),
                rate=Decimal("1.12"),
                batch_key="fixing-v1",
            ),
        ),
        None,
        25,
        1,
    )
    service.list_benchmark_observations.return_value = Page(
        (domain.BenchmarkObservation(**observation, level=Decimal("100")),), None, 25, 1
    )
    detail = _definition()
    service.list_benchmark_definitions.return_value = Page((detail.definition,), None, 25, 1)
    for name in (
        "get_benchmark_definition",
        "create_benchmark_definition",
        "create_benchmark_version",
        "archive_benchmark_definition",
    ):
        getattr(service, name).return_value = detail
    return service


def _app(
    scopes: frozenset[Scope] = ALL_SCOPES, *, available: bool = True
) -> tuple[FastAPI, AsyncMock]:
    service = _service()
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=SyntheticPortfolioService(clock=lambda: NOW),
        source_service=cast(app.SourceService, service) if available else None,
        bearer_authenticator=_Bearer(scopes),
        clock=lambda: NOW,
    )
    return application, service


def _headers(**extra: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer source-test-token",
        "X-Idempotency-Key": "source-command-one",
        **extra,
    }


@pytest.mark.parametrize(("name", "method", "path", "body"), OPERATIONS)
async def test_fourteen_fixed_operations_return_closed_authorized_views(
    name: str, method: str, path: str, body: Any
) -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.request(method, path, json=body, headers=_headers())
    assert response.status_code == (
        201 if name in {"create_benchmark_definition", "create_benchmark_version"} else 200
    ), response.text
    assert response.headers["cache-control"] == "private, no-store" and response.headers["etag"]
    getattr(service, name).assert_awaited_once()
    assert "owner_id" not in response.text and "credential" not in response.text


@pytest.mark.parametrize(("name", "method", "path", "body"), OPERATIONS)
async def test_authentication_precedes_malformed_path_query_body_and_service(
    name: str, method: str, path: str, body: Any
) -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        malformed_path = path
        for identifier in (ACCOUNT, SNAPSHOT, DEFINITION):
            malformed_path = malformed_path.replace(identifier, "not-a-uuid")
        response = await client.request(
            method, malformed_path + "?source-canary-unknown=private", content=b"{invalid"
        )
    assert response.status_code == 401 and "source-canary" not in response.text
    getattr(service, name).assert_not_awaited()


@pytest.mark.parametrize("missing", [Scope.ANALYTICS_READ, Scope.TARGETS_WRITE])
async def test_benchmark_write_scopes_precede_invalid_json(missing: Scope) -> None:
    application, service = _app(ALL_SCOPES - {missing})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        denied = await client.post(
            "/api/v1/benchmark-definitions", content=b"{", headers=_headers()
        )
    assert denied.status_code == 403
    service.create_benchmark_definition.assert_not_awaited()


async def test_snapshot_optional_account_reference_requires_portfolio_scope() -> None:
    application, service = _app(frozenset({Scope.ANALYTICS_READ}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        allowed = await client.get(f"/api/v1/benchmark-snapshots/{SNAPSHOT}", headers=_headers())
        denied = await client.get(
            f"/api/v1/benchmark-snapshots/{SNAPSHOT}?account_id={ACCOUNT}", headers=_headers()
        )
    assert allowed.status_code == 200 and denied.status_code == 403
    assert service.get_benchmark_snapshot.await_count == 1


async def test_cookie_commands_require_csrf_trusted_origin_and_preserve_bearer_precedence() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        session = await client.post("/api/v1/auth/local-session")
        token = session.json()["csrf_token"]
        for headers in (
            {},
            {"Origin": ORIGIN},
            {"X-CSRF-Token": token},
            {"Origin": "https://foreign.invalid", "X-CSRF-Token": token},
            {"Origin": ORIGIN, "X-CSRF-Token": "invalid"},
        ):
            denied = await client.post(
                "/api/v1/benchmark-definitions", content=b"{", headers=headers
            )
            assert denied.status_code == 401
        service.create_benchmark_definition.assert_not_awaited()
        allowed = await client.post(
            "/api/v1/benchmark-definitions",
            json=BODY,
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": token,
                "X-Idempotency-Key": "source-cookie-command",
            },
        )
        bearer = await client.post("/api/v1/benchmark-definitions", json=BODY, headers=_headers())
    assert allowed.status_code == bearer.status_code == 201


@pytest.mark.parametrize("key", [None, "", "x" * 181, "invalid space"])
async def test_idempotency_identity_is_required_and_bounded(key: str | None) -> None:
    application, service = _app()
    headers = _headers()
    headers.pop("X-Idempotency-Key")
    if key is not None:
        headers["X-Idempotency-Key"] = key
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post("/api/v1/benchmark-definitions", json=BODY, headers=headers)
    assert response.status_code == 422
    service.create_benchmark_definition.assert_not_awaited()


async def test_command_revision_is_passed_unchanged_for_authorized_service_replay() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        for token in (None, '"stale"', _definition().definition.etag):
            response = await client.post(
                f"/api/v1/benchmark-definitions/{DEFINITION}/versions",
                json={"content": BODY["content"]},
                headers=_headers(**({"If-Match": token} if token else {})),
            )
            assert response.status_code == 201
            assert service.create_benchmark_version.call_args.kwargs["if_match"] == token
            assert response.json()["definition"]["revision_etag"] == _definition().definition.etag


async def test_license_is_rechecked_before_304_and_changed_receipt_changes_header_validator() -> (
    None
):
    application, service = _app()
    path = f"/api/v1/benchmark-snapshots/{SNAPSHOT}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        first = await client.get(path, headers=_headers())
        headers = _headers(**{"If-None-Match": first.headers["etag"]})
        repeated = await client.get(path, headers=headers)
        assert repeated.status_code == 304
        original = service.get_benchmark_snapshot.return_value
        service.get_benchmark_snapshot.return_value = replace(
            original,
            latest_retrieval=domain.RetrievalOccurrence(
                id=VERSION, snapshot_id=SNAPSHOT, retrieved_at=NOW + timedelta(seconds=1)
            ),
        )
        changed = await client.get(path, headers=headers)
        assert changed.status_code == 200 and changed.headers["etag"] != first.headers["etag"]
        assert changed.json()["content_digest"] == first.json()["content_digest"]
        service.get_benchmark_snapshot.side_effect = app.SourceServiceError(
            app.SourceServiceErrorCode.ACCESS_DENIED, "source-canary-private-reason"
        )
        denied = await client.get(path, headers=headers)
    assert denied.status_code == 403 and "source-canary" not in denied.text
    assert service.get_benchmark_snapshot.await_count == 4


@pytest.mark.parametrize(
    "suffix",
    [
        "?limit=101",
        "?limit=1&limit=2",
        "?source-canary-unknown=private",
        "?cursor=bad%20cursor",
        "?start=2026-09-07",
        "?sort=unknown",
    ],
)
async def test_source_query_boundaries_fail_before_service_without_echo(suffix: str) -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/market-sources{suffix}", headers=_headers()
        )
    assert response.status_code in {400, 422} and "source-canary" not in response.text
    service.get_market_source_status.assert_not_awaited()


async def test_streamed_body_bound_ignores_forged_content_length() -> None:
    application, service = _app()

    async def chunks() -> AsyncIterator[bytes]:
        yield b"{" + b" " * 40000
        yield b" " * 40000 + b"}"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post(
            "/api/v1/benchmark-definitions",
            content=chunks(),
            headers=_headers(**{"Content-Length": "1"}),
        )
    assert response.status_code == 413 and response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    service.create_benchmark_definition.assert_not_awaited()


async def test_invalid_results_cannot_be_hidden_by_304_and_large_gap_preview_remains_readable() -> (
    None
):
    application, service = _app()
    path = f"/api/v1/fx-snapshots/{SNAPSHOT}"
    original = service.get_fx_snapshot.return_value
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        service.get_fx_snapshot.return_value = {"source-canary-private": "private"}
        invalid = await client.get(path, headers=_headers(**{"If-None-Match": "*"}))
        assert invalid.status_code == 500 and "source-canary" not in invalid.text
        period_start = date(2018, 1, 1)
        gaps = tuple(
            domain.SourceGap(
                session_date=period_start + timedelta(days=index // 32),
                source_key=f"pair-{index % 32}",
                reason=domain.SourceReason.MISSING_SESSION,
            )
            for index in range(100000)
        )
        service.get_fx_snapshot.return_value = replace(
            original,
            period=domain.SourcePeriod(start=period_start, end=gaps[-1].session_date),
            coverage=app.SourceCoverageView.from_coverage(
                domain.SourceCoverage(
                    expected_count=100000,
                    available_count=0,
                    gaps=gaps,
                    quality=QualityState.PARTIAL,
                )
            ),
        )
        large = await client.get(path, headers=_headers())
    assert large.status_code == 200
    coverage = large.json()["coverage"]
    assert coverage["gap_count"] == 100000 and coverage["gaps_truncated"] is True
    assert len(coverage["gaps"]) == 100 and len(large.content) < 20000


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (app.SourceServiceErrorCode.REVISION_REQUIRED, 428),
        (app.SourceServiceErrorCode.REVISION_MISMATCH, 412),
        (app.SourceServiceErrorCode.IDEMPOTENCY_KEY_REUSED, 409),
        (app.SourceServiceErrorCode.NOT_FOUND, 404),
        (app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE, 503),
    ],
)
async def test_source_service_error_envelopes_are_fixed_safe_messages(
    code: app.SourceServiceErrorCode, expected: int
) -> None:
    application, service = _app()
    service.create_benchmark_definition.side_effect = app.SourceServiceError(
        code, "source-canary-private-error"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.post("/api/v1/benchmark-definitions", json=BODY, headers=_headers())
    assert response.status_code == expected and response.json()["error"]["code"] == code
    assert "source-canary" not in response.text


async def test_source_unavailable_runtime_fails_after_authentication() -> None:
    application, _ = _app(available=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        assert (await client.get("/api/v1/benchmark-definitions")).status_code == 401
        assert (
            await client.get("/api/v1/benchmark-definitions", headers=_headers())
        ).status_code == 503


async def test_no_unsupported_source_or_benchmark_mutation_route_is_exposed() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        for method, path in (
            ("DELETE", f"/api/v1/benchmark-definitions/{DEFINITION}"),
            ("PATCH", f"/api/v1/benchmark-definitions/{DEFINITION}"),
            ("POST", f"/api/v1/price-snapshots/{SNAPSHOT}"),
            ("POST", f"/api/v1/accounts/{ACCOUNT}/market-sources"),
        ):
            response = await client.request(method, path, headers=_headers())
            assert response.status_code == 405
    assert service.mock_calls == []


async def test_full_response_byte_bound_is_enforced_before_wildcard_conditional_success() -> None:
    application, service = _app()
    original = _definition()
    assert original.selected_version is not None
    components = tuple(
        domain.BenchmarkComponent(source_id=str(UUID(int=index + 1)), weight=Decimal("0.00390625"))
        for index in range(256)
    )
    adjustments = tuple(
        domain.BenchmarkNormalizationAdjustment(
            source_id=item.source_id,
            original_weight=Decimal("0.003906249999999999"),
            normalized_weight=item.weight,
        )
        for item in components
    )
    version = replace(
        original.selected_version,
        content=replace(original.selected_version.content, components=components),
        normalization_adjustments=adjustments,
    )
    versions = tuple(
        replace(version, id=str(UUID(int=1000 + index)), version_number=index + 1)
        for index in range(100)
    )
    service.get_benchmark_definition.return_value = replace(
        original,
        definition=replace(original.definition, version_count=100),
        versions=Page(versions, None, 100, 100),
        selected_version=versions[-1],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(
            f"/api/v1/benchmark-definitions/{DEFINITION}?limit=100",
            headers=_headers(**{"If-None-Match": "*"}),
        )
    assert response.status_code == 422 and response.json()["error"]["code"] == "RESULT_TOO_LARGE"


async def test_maximum_provider_revision_order_preserves_all_digits_for_javascript_clients() -> (
    None
):
    application, service = _app()
    original = service.get_benchmark_snapshot.return_value
    service.get_benchmark_snapshot.return_value = replace(
        original, provenance=replace(original.provenance, revision_order=2**63 - 1)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(f"/api/v1/benchmark-snapshots/{SNAPSHOT}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["provenance"]["revision_order"] == "9223372036854775807"
