"""Persisted P2-01 HTTP lifecycle, ownership and replay security regressions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from starlette.testclient import TestClient
from trading212_api.main import create_app
from trading212_domain import build_synthetic_identity
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.seed import seed_synthetic
from trading212_persistence.target_models import TargetCommandIdentityModel
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ORIGIN = "https://testserver"


@pytest.fixture(scope="module")
def target_api_database() -> Iterator[Engine]:
    parsed = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
        ).replace("postgresql://", "postgresql+psycopg://", 1)
    )
    database_name = f"t212pi_targetapi_{uuid4().hex[:12]}"
    admin_dsn = (
        parsed.set(database="postgres")
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    database_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    engine: Engine | None = None
    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        seed_synthetic(database_url, app_environment="test")
        engine = create_database_engine(database_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_targetapi_"):
            raise RuntimeError("Refusing to remove an unexpected test database.")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


class TargetBearer:
    async def authenticate(self, token: str) -> Principal:
        if token not in {
            "owner-read",
            "owner-write",
            "owner-targets",
            "foreign-owner",
            "owner-all",
        }:
            raise AuthenticationError("Invalid test credential.")
        scopes = {
            "owner-read": frozenset({Scope.TARGETS_READ}),
            "owner-write": frozenset({Scope.TARGETS_WRITE}),
            "owner-targets": frozenset({Scope.TARGETS_READ, Scope.TARGETS_WRITE}),
            "foreign-owner": frozenset(
                {Scope.TARGETS_READ, Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ}
            ),
            "owner-all": frozenset({Scope.TARGETS_READ, Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ}),
        }[token]
        return Principal(
            principal_id="target-api-test-principal",
            owner_id=(
                "cb89363d-ee85-4aad-8f0a-29b5aa787c27"
                if token == "foreign-owner"
                else LOCAL_SYNTHETIC_OWNER_ID
            ),
            issuer="target-api-test",
            subject="target-api-test",
            scopes=scopes,
            authenticated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


@pytest.fixture
def target_api_client(target_api_database: Engine) -> Iterator[TestClient]:
    sessions = create_session_factory(target_api_database)
    service = PostgresPortfolioService(
        sessions=sessions,
        cursor_signing_key=b"target-api-test-cursor-signing-key",
        clock=lambda: NOW,
    )
    targets = PostgresTargetService(
        sessions=sessions,
        cursor_signing_key=b"target-api-test-cursor-signing-key",
        clock=lambda: NOW,
    )
    app = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            allowed_hosts=("testserver",),
            allowed_origins=(ORIGIN,),
        ),
        service=service,
        target_service=targets,
        bearer_authenticator=TargetBearer(),
        clock=lambda: NOW,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


def _headers(
    identity: str = "owner-targets", *, key: str | None = None, etag: str | None = None
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {identity}", "X-Idempotency-Key": key or str(uuid4())}
    if etag is not None:
        headers["If-Match"] = etag
    return headers


def _create(client: TestClient, *, account_id: str | None = None) -> tuple[str, str]:
    response = client.post(
        "/api/v1/virtual-portfolios",
        json={
            "name": f"API target {uuid4()}",
            "reporting_currency": "EUR",
            "account_id": account_id,
        },
        headers=_headers("owner-all"),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], response.headers["etag"]


def _content(weight: str = "1") -> dict[str, Any]:
    return {
        "nodes": [
            {
                "key": "cash",
                "parent_key": None,
                "kind": "cash",
                "name": "Cash",
                "order": 0,
                "weight": weight,
            }
        ],
        "constraints": [],
        "exclusions": [],
    }


def test_target_persisted_lifecycle_replays_and_conditional_get(
    target_api_client: TestClient,
) -> None:
    client = target_api_client
    portfolio_id, portfolio_etag = _create(client)
    path = f"/api/v1/virtual-portfolios/{portfolio_id}"
    changed = {"description": "Retained owner-private metadata"}
    metadata_key = str(uuid4())
    missing = client.patch(path, json=changed, headers=_headers(key=metadata_key))
    assert missing.status_code == 428
    assert missing.json()["error"]["code"] == "REVISION_REQUIRED"
    updated = client.patch(
        path, json=changed, headers=_headers(key=metadata_key, etag=portfolio_etag)
    )
    assert updated.status_code == 200, updated.text
    replay = client.patch(
        path, json=changed, headers=_headers(key=metadata_key, etag=portfolio_etag)
    )
    assert replay.status_code == 200
    assert replay.json() == updated.json()
    assert client.patch(path, json=changed, headers=_headers(key=metadata_key)).status_code == 200
    changed_key = client.patch(
        path,
        json={"description": "Different payload"},
        headers=_headers(key=metadata_key, etag=portfolio_etag),
    )
    assert changed_key.status_code == 409
    assert changed_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (
        client.patch(
            path, json={"name": "Stale revision"}, headers=_headers(etag=portfolio_etag)
        ).status_code
        == 412
    )

    version_key = str(uuid4())
    version_body = {"effective_at": "2026-09-07T12:00:00Z", "content": _content()}
    draft = client.post(
        f"{path}/target-versions",
        json=version_body,
        headers=_headers(key=version_key, etag=updated.headers["etag"]),
    )
    assert draft.status_code == 201, draft.text
    version_id = draft.json()["id"]
    version_path = f"/api/v1/target-versions/{version_id}"
    assert draft.json()["state"] == "draft"
    assert draft.json()["content"]["nodes"][0]["weight"] == "1"
    assert (
        client.post(
            f"{path}/target-versions", json=version_body, headers=_headers(key=version_key)
        ).json()["id"]
        == version_id
    )
    validation = client.post(
        f"{version_path}/validate",
        json={"normalize": False},
        headers=_headers(etag=draft.headers["etag"]),
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is True
    assert validation.json()["result_revision"] > validation.json()["input_revision"]
    changed_validation = client.get(
        version_path,
        headers={**_headers(), "If-None-Match": draft.headers["etag"]},
    )
    assert changed_validation.status_code == 200
    assert changed_validation.json()["latest_validation"]["id"] == validation.json()["id"]
    publish_key = str(uuid4())
    published = client.post(
        f"{version_path}/publish",
        json={"validation_id": validation.json()["id"]},
        headers=_headers(key=publish_key, etag=validation.headers["etag"]),
    )
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "active"
    digest = published.json()["content_digest"]
    assert len(digest) == 64
    read = client.get(version_path, headers=_headers())
    conditional = client.get(
        version_path, headers={**_headers(), "If-None-Match": read.headers["etag"]}
    )
    assert conditional.status_code == 304
    immutable = client.patch(
        version_path, json=version_body, headers=_headers(etag=read.headers["etag"])
    )
    assert immutable.status_code == 409
    assert immutable.json()["error"]["code"] == "IMMUTABLE_VERSION"
    for resource in (version_path, path):
        deletion = client.delete(resource, headers=_headers(etag=read.headers["etag"]))
        assert deletion.status_code == 405
        assert "DELETE" not in deletion.headers.get("allow", "")
    retained = client.get(version_path, headers=_headers())
    assert retained.json() == read.json()
    assert retained.headers["etag"] == read.headers["etag"]
    assert retained.json()["content_digest"] == digest
    nodes = client.get(f"{version_path}/nodes?limit=1", headers=_headers())
    assert nodes.status_code == 200, nodes.text
    assert nodes.json()["items"][0]["node"]["key"] == "cash"
    events = client.get(f"{version_path}/events?limit=1", headers=_headers())
    assert events.status_code == 200, events.text
    assert events.json()["total"] >= 3
    assert events.json()["next_cursor"] is not None
    comparison = client.get(
        f"{path}/target-comparison",
        params={"left_version_id": version_id, "right_version_id": version_id},
        headers=_headers(),
    )
    assert comparison.status_code == 200
    assert comparison.json()["comparison"]["node_changes"] == []
    archived = client.post(
        f"{version_path}/archive", json={}, headers=_headers(etag=read.headers["etag"])
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["state"] == "archived"
    assert archived.json()["content_digest"] == digest
    after = client.get(version_path, headers={**_headers(), "If-None-Match": read.headers["etag"]})
    assert after.status_code == 200
    assert after.headers["etag"] != read.headers["etag"]
    current = client.get(path, headers=_headers())
    portfolio_archive = client.post(
        f"{path}/archive", json={}, headers=_headers(etag=current.headers["etag"])
    )
    assert portfolio_archive.status_code == 200
    assert portfolio_archive.json()["state"] == "archived"


def test_target_owner_and_account_scopes_fail_closed(target_api_client: TestClient) -> None:
    client = target_api_client
    portfolio_id, etag = _create(client)
    path = f"/api/v1/virtual-portfolios/{portfolio_id}"
    assert client.get(path, headers=_headers("owner-read")).status_code == 200
    assert client.get(path, headers=_headers("owner-write")).status_code == 403
    foreign = client.get(path, headers=_headers("foreign-owner"))
    missing = client.get(f"/api/v1/virtual-portfolios/{uuid4()}", headers=_headers("foreign-owner"))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"] == "NOT_FOUND"
    assert portfolio_id not in foreign.text
    assert (
        client.patch(
            path, json={"name": "Denied"}, headers=_headers("foreign-owner", etag=etag)
        ).status_code
        == 404
    )
    account_id = str(build_synthetic_identity().account.id)
    account_portfolio, _ = _create(client, account_id=account_id)
    backed_path = f"/api/v1/virtual-portfolios/{account_portfolio}"
    assert client.get(backed_path, headers=_headers("owner-read")).status_code == 403
    assert client.get(backed_path, headers=_headers("owner-all")).status_code == 200
    assert (
        client.post(
            "/api/v1/virtual-portfolios",
            json={
                "name": "Missing account scope",
                "reporting_currency": "EUR",
                "account_id": account_id,
            },
            headers=_headers("owner-write"),
        ).status_code
        == 403
    )


def test_target_invalid_content_is_persisted_as_failed_validation(
    target_api_client: TestClient,
) -> None:
    client = target_api_client
    portfolio_id, etag = _create(client)
    draft = client.post(
        f"/api/v1/virtual-portfolios/{portfolio_id}/target-versions",
        json={"effective_at": "2026-09-07T12:00:00Z", "content": _content("0.9")},
        headers=_headers(etag=etag),
    )
    assert draft.status_code == 201, draft.text
    path = f"/api/v1/target-versions/{draft.json()['id']}"
    validation = client.post(
        f"{path}/validate", json={"normalize": False}, headers=_headers(etag=draft.headers["etag"])
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is False
    assert validation.json()["issues"]
    publish = client.post(
        f"{path}/publish",
        json={"validation_id": validation.json()["id"]},
        headers=_headers(etag=validation.headers["etag"]),
    )
    assert publish.status_code == 422
    assert publish.json()["error"]["code"] == "TARGET_VALIDATION_FAILED"
    assert client.get(path, headers=_headers()).json()["state"] == "draft"


def test_rejected_http_input_and_csrf_create_no_command_identity(
    target_api_client: TestClient, target_api_database: Engine
) -> None:
    client = target_api_client
    sessions = create_session_factory(target_api_database)
    with sessions() as session:
        before = session.scalar(select(func.count()).select_from(TargetCommandIdentityModel))
    body = {"name": "Private target", "reporting_currency": "EUR"}
    unknown = client.post(
        "/api/v1/virtual-portfolios",
        json={**body, "provider_url": "target-secret-canary"},
        headers=_headers(),
    )
    assert unknown.status_code == 422
    assert "target-secret-canary" not in unknown.text
    login = client.post("/api/v1/auth/local-session")
    csrf = login.json()["csrf_token"]
    denied = client.post(
        "/api/v1/virtual-portfolios",
        json=body,
        headers={
            "X-Idempotency-Key": str(uuid4()),
            "X-CSRF-Token": csrf,
            "Origin": "https://foreign.invalid",
        },
    )
    assert denied.status_code == 401
    oversized = client.post(
        "/api/v1/virtual-portfolios",
        content=b" " * (64 * 1024 + 1),
        headers={**_headers(), "Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    with sessions() as session:
        after = session.scalar(select(func.count()).select_from(TargetCommandIdentityModel))
    assert after == before


def test_normalization_revision_pin_and_template_clone_are_enforced(
    target_api_client: TestClient,
) -> None:
    client = target_api_client
    portfolio_id, etag = _create(client)
    portfolio_path = f"/api/v1/virtual-portfolios/{portfolio_id}"
    draft = client.post(
        f"{portfolio_path}/target-versions",
        json={"effective_at": "2026-09-07T12:00:00Z", "content": _content("0.999999999999999999")},
        headers=_headers(etag=etag),
    )
    assert draft.status_code == 201, draft.text
    version_id = draft.json()["id"]
    path = f"/api/v1/target-versions/{version_id}"
    normalized = client.post(
        f"{path}/validate",
        json={"normalize": True},
        headers=_headers(etag=draft.headers["etag"]),
    )
    assert normalized.status_code == 200, normalized.text
    assert normalized.json()["valid"] is True
    assert normalized.json()["normalization_applied"] is True
    assert normalized.json()["input_digest"] != normalized.json()["result_digest"]
    assert normalized.json()["adjustments"][0]["normalized_weight"] == "1"
    replacement: dict[str, Any] = {"effective_at": "2026-09-07T12:00:00Z", "content": _content()}
    replacement["content"]["nodes"][0]["name"] = "Renamed cash"
    updated = client.patch(
        path, json=replacement, headers=_headers(etag=normalized.headers["etag"])
    )
    assert updated.status_code == 200, updated.text
    stale = client.post(
        f"{path}/publish",
        json={"validation_id": normalized.json()["id"]},
        headers=_headers(etag=updated.headers["etag"]),
    )
    assert stale.status_code == 422
    assert stale.json()["error"]["code"] == "TARGET_VALIDATION_FAILED"
    validation = client.post(
        f"{path}/validate", json={}, headers=_headers(etag=updated.headers["etag"])
    )
    assert validation.status_code == 200
    latest = client.get(path, headers=_headers()).json()["latest_validation"]
    assert latest["id"] == validation.json()["id"]
    assert latest["result_revision"] > normalized.json()["result_revision"]
    portfolio = client.get(portfolio_path, headers=_headers())
    clone_body = {"effective_at": "2026-09-08T12:00:00Z", "source_version_id": version_id}
    denied = client.post(
        f"{portfolio_path}/target-versions",
        json=clone_body,
        headers=_headers("owner-write", etag=portfolio.headers["etag"]),
    )
    assert denied.status_code == 403
    cloned = client.post(
        f"{portfolio_path}/target-versions",
        json=clone_body,
        headers=_headers(etag=portfolio.headers["etag"]),
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["id"] != version_id
    assert cloned.json()["source_version_id"] == version_id
    assert cloned.json()["content"]["nodes"][0]["name"] == "Renamed cash"
    comparison = client.get(
        f"{portfolio_path}/target-comparison",
        params={"left_version_id": version_id, "right_version_id": cloned.json()["id"]},
        headers=_headers(),
    )
    assert comparison.status_code == 200
    assert comparison.json()["comparison"]["effective_time_changed"] is True
