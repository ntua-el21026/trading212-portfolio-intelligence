"""Exact bounded reference identities, authority before parsing and safe conditionals."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from trading212_api_contracts import sources as wire
from trading212_application import sources as app
from trading212_domain.serialization import to_primitive
from trading212_domain.sources import ObservationState
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Scope

from tests.unit.api.test_source_routes import (
    ACCOUNT,
    ALL_SCOPES,
    NOW,
    ORIGIN,
    SNAPSHOT,
    _app,
    _headers,
)

PATH = f"/api/v1/fx-snapshots/{SNAPSHOT}/observation-references"
QUERY = {
    "account_id": ACCOUNT,
    "base": "EUR",
    "quote": "USD",
    "source_cutoff_at": NOW.isoformat(),
    "effective_at_lte": (NOW - timedelta(days=1)).isoformat(),
}


def page() -> app.FxObservationReferencePage:
    at = NOW - timedelta(days=1)
    return app.FxObservationReferencePage(
        account_id=ACCOUNT,
        snapshot_id=SNAPSHOT,
        content_digest="b" * 64,
        base=CurrencyCode("EUR"),
        quote=CurrencyCode("USD"),
        source_cutoff_at=NOW,
        effective_at_lte=at,
        first_observed_at=NOW,
        expires_at=NOW + timedelta(days=1),
        items=(
            app.FxObservationReference(
                observation_id=str(uuid4()),
                session_date=at.date(),
                effective_at=at,
                rate=Decimal("1.123456789123456789"),
                state=ObservationState.AVAILABLE,
            ),
        ),
        next_cursor=None,
        limit=25,
    )


async def test_reference_route_keeps_exact_identity_and_final_authorized_conditional() -> None:
    application, service = _app()
    expected = page()
    service.list_fx_observation_references.return_value = expected
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        first = await client.get(PATH, params=QUERY, headers=_headers())
        assert first.status_code == 200
        assert first.json()["items"][0]["rate"] == "1.123456789123456789"
        assert first.json()["items"][0]["observation_id"] == expected.items[0].observation_id
        assert first.json()["effective_at_lte"].startswith("2026-09-06T12:00:00")
        assert first.headers["cache-control"] == "private, no-store"
        conditional = await client.get(
            PATH, params=QUERY, headers=_headers(**{"If-None-Match": first.headers["etag"]})
        )
        assert conditional.status_code == 304
        service.list_fx_observation_references.side_effect = app.SourceServiceError(
            app.SourceServiceErrorCode.ACCESS_DENIED, "private source canary"
        )
        denied = await client.get(PATH, params=QUERY, headers=_headers(**{"If-None-Match": "*"}))
        assert denied.status_code == 403 and "private source canary" not in denied.text
    assert service.list_fx_observation_references.await_count == 3
    query = service.list_fx_observation_references.call_args.kwargs["query"]
    assert query.base == CurrencyCode("EUR") and query.effective_at_lte == NOW - timedelta(days=1)


@pytest.mark.parametrize("missing", [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ])
async def test_fixed_reference_scopes_precede_missing_or_malformed_query(missing: Scope) -> None:
    application, service = _app(ALL_SCOPES - {missing})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        for path in (PATH, PATH.replace(SNAPSHOT, "invalid") + "?private-canary=bad"):
            denied = await client.get(path, headers=_headers())
            assert denied.status_code == 403 and "private-canary" not in denied.text
    service.list_fx_observation_references.assert_not_awaited()


@pytest.mark.parametrize(
    "updates",
    [
        {"limit": "26"},
        {"limit": "0"},
        {"base": "USD"},
        {"source_cutoff_at": "2026-09-07"},
        {"effective_at_lte": (NOW + timedelta(seconds=1)).isoformat()},
        {"cursor": "x" * 2049},
        {"url": "https://private.invalid"},
    ],
)
async def test_bounded_reference_query_rejects_before_service(updates: dict[str, str]) -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(PATH, params={**QUERY, **updates}, headers=_headers())
    # The shared source cursor boundary uses400 before the typed query decoder.
    assert response.status_code == (400 if "cursor" in updates else 422)
    service.list_fx_observation_references.assert_not_awaited()


async def test_duplicate_reference_query_is_not_silently_selected() -> None:
    application, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        response = await client.get(
            PATH, params=[*QUERY.items(), ("base", "GBP")], headers=_headers()
        )
    assert response.status_code == 422
    service.list_fx_observation_references.assert_not_awaited()


def test_reference_schema_rejects_unbounded_or_inconsistent_financial_pages() -> None:
    value = page()
    wire.FxObservationReferencePage.model_validate(to_primitive(value))
    for invalid in (
        replace(value, items=value.items * 26),
        replace(value, items=(replace(value.items[0], rate=None),)),
        replace(value, effective_at_lte=NOW - timedelta(days=2)),
        replace(value, first_observed_at=NOW + timedelta(seconds=1)),
        replace(value, next_cursor="opaque"),
    ):
        with pytest.raises(ValidationError):
            wire.FxObservationReferencePage.model_validate(to_primitive(invalid))
    query = app.FxObservationReferenceQuery(
        account_id=ACCOUNT,
        base=CurrencyCode("EUR"),
        quote=CurrencyCode("USD"),
        source_cutoff_at=NOW,
    )
    assert query.effective_at_lte == NOW
    with pytest.raises(ValueError):
        replace(query, limit=26)
