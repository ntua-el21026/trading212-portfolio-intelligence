"""Real PostgreSQL reference API provenance, licensing and immutable benchmark commands."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from psycopg import sql
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from trading212_api.main import create_app
from trading212_application.source_providers import (
    BenchmarkSeriesPage,
    BenchmarkSeriesRequest,
    SourceCapability,
)
from trading212_domain import build_synthetic_identity
from trading212_domain.sources import LicensePermission
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.source_models import (
    BenchmarkComponentModel,
    BenchmarkSnapshotModel,
    BenchmarkVersionModel,
    FxSnapshotModel,
    MarketSourceSeriesModel,
    PriceSnapshotModel,
    SourceCommandIdentityModel,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_provider.client import Trading212Client
from trading212_reference_data.replay import (
    ReplayBenchmarkProvider,
    ReplayContext,
    ReplayFxReferenceProvider,
    ReplayMarketPriceHistoryProvider,
)
from trading212_reference_data.synthetic import (
    CALENDAR_ID,
    CALENDAR_VERSION,
    FIXTURE_PERIOD,
    PROVIDER_ID,
    synthetic_license,
    synthetic_series,
)
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.seed import seed_materialized_synthetic
from trading212_worker.source_seed import collect_source_pages

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ORIGIN = "https://testserver"
ACCOUNT = str(build_synthetic_identity().account.id)
KEY = b"source-api-synthetic-cursor-signing-v1"


@pytest.fixture
def source_api_database() -> Iterator[Engine]:
    parsed = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
        ).replace("postgresql://", "postgresql+psycopg://", 1)
    )
    name = "t212pi_sourceapi_" + uuid4().hex[:12]
    admin = (
        parsed.set(database="postgres")
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = parsed.set(database=name).render_as_string(hide_password=False)
    engine = None
    try:
        configuration = Config("alembic.ini")
        configuration.set_main_option("sqlalchemy.url", url)
        command.upgrade(configuration, "head")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if not name.startswith("t212pi_sourceapi_"):
            raise RuntimeError("Unexpected disposable source API database.")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


class _Bearer:
    async def authenticate(self, token: str) -> Principal:
        if token != "foreign-source-owner":
            raise AuthenticationError("Invalid synthetic credential.")
        return Principal(
            "foreign-source-owner",
            str(uuid4()),
            "test",
            "test",
            frozenset(Scope),
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )


def _runtime(
    engine: Engine, *, clock: Callable[[], datetime] | None = None
) -> tuple[FastAPI, PostgresSourceService]:
    runtime_clock = clock or (lambda: NOW)
    sessions = create_session_factory(engine)
    sources = PostgresSourceService(sessions=sessions, cursor_signing_key=KEY, clock=runtime_clock)
    application = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=PostgresPortfolioService(
            sessions=sessions, cursor_signing_key=KEY, clock=runtime_clock
        ),
        source_service=sources,
        bearer_authenticator=_Bearer(),
        clock=runtime_clock,
    )
    return application, sources


def _principal() -> Principal:
    identity = build_synthetic_identity()
    return Principal(
        str(identity.principal.id),
        str(identity.owner.id),
        "test",
        "test",
        frozenset(Scope),
        NOW - timedelta(hours=1),
        NOW + timedelta(hours=1),
    )


def _source_ids(engine: Engine) -> dict[str, str]:
    with create_session_factory(engine)() as session:
        price = session.scalar(
            select(PriceSnapshotModel.id)
            .join(
                MarketSourceSeriesModel, PriceSnapshotModel.series_id == MarketSourceSeriesModel.id
            )
            .where(MarketSourceSeriesModel.basis == "raw_close")
        )
        fx = session.scalar(select(FxSnapshotModel.id))
        benchmark = session.scalar(
            select(BenchmarkSnapshotModel.id)
            .join(
                MarketSourceSeriesModel,
                BenchmarkSnapshotModel.series_id == MarketSourceSeriesModel.id,
            )
            .where(MarketSourceSeriesModel.basis == "raw_close")
        )
        series = session.scalar(
            select(MarketSourceSeriesModel.id).where(
                MarketSourceSeriesModel.kind == "benchmark_level",
                MarketSourceSeriesModel.basis == "raw_close",
            )
        )
        assert price is not None and fx is not None and benchmark is not None and series is not None
        return {
            "price": str(price),
            "fx": str(fx),
            "benchmark": str(benchmark),
            "series": str(series),
        }


def _body(series: str) -> dict[str, Any]:
    return {
        "name": "Source API private benchmark",
        "content": {
            "reporting_currency": "EUR",
            "effective_at": NOW.isoformat(),
            "return_basis": "raw_close",
            "calendar_id": CALENDAR_ID,
            "calendar_version": CALENDAR_VERSION,
            "rebalance_rule": "buy_and_hold",
            "components": [{"source_id": series, "weight": "1"}],
        },
    }


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/local-session")
    assert response.status_code == 201
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


async def test_retained_source_http_pages_preserve_exact_values_and_never_dispatch_providers(
    source_api_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, _ = _runtime(source_api_database)
    ids = _source_ids(source_api_database)
    spies = []
    for owner, name in (
        (Trading212Client, "_send_with_retry"),
        (ReplayMarketPriceHistoryProvider, "get_price_history"),
        (ReplayFxReferenceProvider, "get_rates"),
        (ReplayBenchmarkProvider, "get_series"),
    ):
        spy = AsyncMock(
            side_effect=AssertionError("Public retained reads must not dispatch providers.")
        )
        monkeypatch.setattr(owner, name, spy)
        spies.append(spy)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        await _login(client)
        for path in ("market-sources", "fx-sources", "benchmark-sources"):
            response = await client.get(f"/api/v1/accounts/{ACCOUNT}/{path}", params={"limit": 1})
            assert response.status_code == 200, response.text
            configured = next(
                item
                for item in response.json()["providers"]
                if item["configuration_state"] == "configured"
            )
            external = next(
                item
                for item in response.json()["providers"]
                if item["configuration_state"] == "not_configured"
            )
            assert set(configured["capabilities"]) == {item.value for item in SourceCapability}
            assert external["availability"] == "unavailable" and external["capabilities"] == []
            assert external["reason"] == "not_configured"
            page = response.json()["pairs" if path == "fx-sources" else "series"]
            assert len(page["items"]) == 1 and page["total"] >= 2 and page["next_cursor"]
            next_page = await client.get(
                f"/api/v1/accounts/{ACCOUNT}/{path}",
                params={"limit": 1, "cursor": page["next_cursor"]},
            )
            assert next_page.status_code == 200
            assert (
                next_page.json()["pairs" if path == "fx-sources" else "series"]["total"]
                == page["total"]
            )
        for kind in ("price", "fx", "benchmark"):
            path = f"/api/v1/{kind}-snapshots/{ids[kind]}"
            header = await client.get(path)
            assert header.status_code == 200, header.text
            assert header.json()["provenance"]["synthetic"] is True
            assert header.json()["provenance"]["revision_order"] == "1"
            assert (
                await client.get(path, headers={"If-None-Match": header.headers["etag"]})
            ).status_code == 304
            if kind == "benchmark":
                assert header.json()["kind"] == "provider_series"
                assert header.json()["benchmark_version_id"] is None
            if kind == "price":
                assert header.json()["coverage"]["gap_count"] > 0
                assert (
                    header.json()["coverage"]["available_count"]
                    < header.json()["coverage"]["expected_count"]
                )
            page = await client.get(path + "/observations", params={"limit": 3})
            assert page.status_code == 200 and page.json()["total"] > 3
            field = {"price": "value", "fx": "rate", "benchmark": "level"}[kind]
            assert all(
                item[field] is None or isinstance(item[field], str) for item in page.json()["items"]
            )
            second = await client.get(
                path + "/observations", params={"limit": 3, "cursor": page.json()["next_cursor"]}
            )
            assert second.status_code == 200 and second.json()["total"] == page.json()["total"]
            assert page.json()["items"] != second.json()["items"]
    assert all(spy.await_count == 0 for spy in spies)


async def test_foreign_owner_and_account_cannot_read_header_pages_or_benchmark_definitions(
    source_api_database: Engine,
) -> None:
    application, _ = _runtime(source_api_database)
    ids = _source_ids(source_api_database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        csrf = await _login(client)
        created = await client.post(
            "/api/v1/benchmark-definitions",
            json=_body(ids["series"]),
            headers={**csrf, "X-Idempotency-Key": "source-owner-definition"},
        )
        assert created.status_code == 201
        definition = created.json()["definition"]["id"]
        for kind in ("price", "fx", "benchmark"):
            for suffix in ("", "/observations"):
                denied = await client.get(
                    f"/api/v1/{kind}-snapshots/{ids[kind]}{suffix}",
                    headers={"Authorization": "Bearer foreign-source-owner", "If-None-Match": "*"},
                )
                assert denied.status_code == 404
        foreign_account = await client.get(
            f"/api/v1/price-snapshots/{ids['price']}", params={"account_id": str(uuid4())}
        )
        assert foreign_account.status_code == 404
        denied = await client.get(
            f"/api/v1/benchmark-definitions/{definition}",
            headers={"Authorization": "Bearer foreign-source-owner", "If-None-Match": "*"},
        )
        assert denied.status_code == 404
        replay = await client.post(
            "/api/v1/benchmark-definitions",
            json=_body(ids["series"]),
            headers={
                "Authorization": "Bearer foreign-source-owner",
                "X-Idempotency-Key": "source-owner-definition",
            },
        )
        assert replay.status_code == 404


async def test_benchmark_http_idempotency_concurrency_history_and_archive_use_real_persistence(
    source_api_database: Engine,
) -> None:
    application, _ = _runtime(source_api_database)
    body = _body(_source_ids(source_api_database)["series"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        csrf = await _login(client)
        headers = {**csrf, "X-Idempotency-Key": "source-benchmark-create"}
        created = await client.post("/api/v1/benchmark-definitions", json=body, headers=headers)
        assert created.status_code == 201, created.text
        first = created.json()
        definition = first["definition"]["id"]
        oldest = first["selected_version"]["id"]
        old_digest = first["selected_version"]["content_digest"]
        replay = await client.post("/api/v1/benchmark-definitions", json=body, headers=headers)
        assert replay.json() == first
        conflict = await client.post(
            "/api/v1/benchmark-definitions",
            json={**body, "name": "Changed payload"},
            headers=headers,
        )
        assert conflict.status_code == 409
        version_path = f"/api/v1/benchmark-definitions/{definition}/versions"
        absent = await client.post(
            version_path,
            json={"content": body["content"]},
            headers={**csrf, "X-Idempotency-Key": "source-version-missing"},
        )
        assert absent.status_code == 428
        current = first
        for number in range(2, 27):
            content = {
                **body["content"],
                "effective_at": (NOW + timedelta(seconds=number)).isoformat(),
            }
            response = await client.post(
                version_path,
                json={"content": content},
                headers={
                    **csrf,
                    "X-Idempotency-Key": f"source-version-{number}",
                    "If-Match": current["definition"]["revision_etag"],
                },
            )
            assert response.status_code == 201, response.text
            current = response.json()
        detail_path = f"/api/v1/benchmark-definitions/{definition}"
        old_selection = await client.get(detail_path, params={"selected_version_id": oldest})
        assert old_selection.status_code == 200
        selected = old_selection.json()
        assert selected["selected_version"]["id"] == oldest
        assert selected["selected_version"]["content_digest"] == old_digest
        assert selected["versions"]["total"] == 26 and len(selected["versions"]["items"]) == 25
        assert oldest not in {item["id"] for item in selected["versions"]["items"]}
        tail = await client.get(
            detail_path,
            params={"selected_version_id": oldest, "cursor": selected["versions"]["next_cursor"]},
        )
        assert tail.status_code == 200 and [
            item["id"] for item in tail.json()["versions"]["items"]
        ] == [oldest]
        requests = [
            client.post(
                version_path,
                json={"content": body["content"]},
                headers={
                    **csrf,
                    "X-Idempotency-Key": f"source-concurrent-{index}",
                    "If-Match": current["definition"]["revision_etag"],
                },
            )
            for index in range(2)
        ]
        outcomes = await asyncio.gather(*requests)
        assert sorted(response.status_code for response in outcomes) == [201, 412]
        winner_index = next(
            index for index, response in enumerate(outcomes) if response.status_code == 201
        )
        current = outcomes[winner_index].json()
        replay = await client.post(
            version_path,
            json={"content": body["content"]},
            headers={**csrf, "X-Idempotency-Key": f"source-concurrent-{winner_index}"},
        )
        assert (
            replay.status_code == 201
            and replay.json()["selected_version"]["id"] == current["selected_version"]["id"]
        )
        archive_headers = {
            **csrf,
            "X-Idempotency-Key": "source-archive",
            "If-Match": current["definition"]["revision_etag"],
        }
        archived = await client.post(detail_path + "/archive", json={}, headers=archive_headers)
        assert archived.status_code == 200 and archived.json()["definition"]["state"] == "archived"
        assert archived.json()["definition"]["version_count"] == 27
        archive_replay = await client.post(
            detail_path + "/archive",
            json={},
            headers={**csrf, "X-Idempotency-Key": "source-archive"},
        )
        assert archive_replay.status_code == 200 and archive_replay.json() == archived.json()
        immutable = await client.get(detail_path, params={"selected_version_id": oldest})
        assert (
            immutable.status_code == 200
            and immutable.json()["selected_version"]["content_digest"] == old_digest
        )
        assert (await client.delete(detail_path, headers=csrf)).status_code == 405
    with create_session_factory(source_api_database)() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(BenchmarkVersionModel)
                .where(BenchmarkVersionModel.definition_id == UUID(definition))
            )
            == 27
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(BenchmarkComponentModel)
                .join(
                    BenchmarkVersionModel,
                    BenchmarkComponentModel.version_id == BenchmarkVersionModel.id,
                )
                .where(BenchmarkVersionModel.definition_id == UUID(definition))
            )
            == 27
        )


@pytest.mark.parametrize("permission", [LicensePermission.DENIED, LicensePermission.UNKNOWN])
async def test_current_license_revocation_precedes_304_cursor_and_exact_command_replay(
    source_api_database: Engine,
    permission: LicensePermission,
) -> None:
    application, service = _runtime(source_api_database)
    ids = _source_ids(source_api_database)
    body = _body(ids["series"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        csrf = await _login(client)
        headers = {**csrf, "X-Idempotency-Key": "source-license-command"}
        created = await client.post("/api/v1/benchmark-definitions", json=body, headers=headers)
        assert created.status_code == 201
        snapshot_path = f"/api/v1/benchmark-snapshots/{ids['benchmark']}"
        header = await client.get(snapshot_path)
        page = await client.get(snapshot_path + "/observations", params={"limit": 1})
        assert header.status_code == page.status_code == 200
        revoked = replace(
            synthetic_license(),
            id=str(uuid4()),
            version="api-license-revocation-v2",
            effective_at=NOW,
            display=permission,
        )
        await service.register_source_license(
            _principal(),
            revoked,
            idempotency_key="source-license-revoke",
            correlation_id="source-license-audit",
        )
        denied_header = await client.get(
            snapshot_path, headers={"If-None-Match": header.headers["etag"]}
        )
        denied_page = await client.get(
            snapshot_path + "/observations",
            params={"limit": 1, "cursor": page.json()["next_cursor"]},
        )
        denied_replay = await client.post(
            "/api/v1/benchmark-definitions", json=body, headers=headers
        )
        assert (
            denied_header.status_code == denied_page.status_code == denied_replay.status_code == 403
        )
        status = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/benchmark-sources", params={"provider_id": PROVIDER_ID}
        )
        assert status.status_code == 200
        assert all(
            item["latest_snapshot"] is None and item["reason"] == "license_denied"
            for item in status.json()["series"]["items"]
        )
    with create_session_factory(source_api_database)() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceCommandIdentityModel)
                .where(SourceCommandIdentityModel.idempotency_key == "source-license-command")
            )
            == 1
        )


async def test_reference_freshness_boundary_and_new_receipt_never_freshen_old_values(
    source_api_database: Engine,
) -> None:
    ids = _source_ids(source_api_database)
    with create_session_factory(source_api_database)() as session:
        reference_at = session.scalar(
            select(BenchmarkSnapshotModel.effective_at).where(
                BenchmarkSnapshotModel.id == UUID(ids["benchmark"])
            )
        )
        assert reference_at is not None
    time = [reference_at + timedelta(days=7) - timedelta(microseconds=1)]
    application, service = _runtime(source_api_database, clock=lambda: time[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url=ORIGIN
    ) as client:
        await _login(client)
        path = f"/api/v1/benchmark-snapshots/{ids['benchmark']}"
        first = await client.get(path)
        assert first.status_code == 200, first.text
        assert first.json()["freshness"]["state"] == "fresh"
        assert first.json()["freshness"]["max_age_seconds"] == 604800
        assert first.json()["coverage"]["quality"] == "fresh"
        conditional = {"If-None-Match": first.headers["etag"]}
        assert (await client.get(path, headers=conditional)).status_code == 304
        time[0] += timedelta(microseconds=1)
        stale = await client.get(path, headers=conditional)
        assert stale.status_code == 200
        assert stale.json()["freshness"]["state"] == "stale"
        assert (
            stale.json()["freshness"]["reference_at"] == first.json()["freshness"]["reference_at"]
        )
        assert stale.json()["content_digest"] == first.json()["content_digest"]
        assert stale.json()["coverage"]["quality"] == "fresh"
        identity = build_synthetic_identity()
        all_series = synthetic_series(
            owner_id=str(identity.owner.id),
            instrument_id=str(identity.instrument.id),
            listing_id=str(identity.listing.id),
        )
        series = next(item for item in all_series if item.id == ids["series"])
        provider = ReplayBenchmarkProvider(
            ReplayContext(license=synthetic_license(), series=all_series, clock=lambda: time[0])
        )
        request = BenchmarkSeriesRequest(
            series=series, period=FIXTURE_PERIOD, source_cutoff_at=time[0]
        )
        pages = await collect_source_pages(
            lambda cursor: provider.get_series(replace(request, continuation=cursor)),
            page_type=BenchmarkSeriesPage,
            next_cursor=lambda item: item.continuation,
            row_count=lambda item: len(item.observations),
        )
        principal = replace(
            _principal(),
            authenticated_at=time[0] - timedelta(hours=1),
            expires_at=time[0] + timedelta(hours=1),
        )
        reread = await service.ingest_benchmark_series(
            principal,
            request,
            pages,
            idempotency_key="source-freshness-reread",
            correlation_id="source-freshness-audit",
        )
        assert reread.id == ids["benchmark"]
        reread_header = await client.get(path)
        assert reread_header.status_code == 200
        assert reread_header.json()["freshness"] == stale.json()["freshness"]
        assert reread_header.json()["content_digest"] == first.json()["content_digest"]
        assert (
            reread_header.json()["latest_retrieval"]["id"] != first.json()["latest_retrieval"]["id"]
        )
        assert (
            reread_header.json()["provenance"]["first_observed_at"]
            == first.json()["provenance"]["first_observed_at"]
        )
