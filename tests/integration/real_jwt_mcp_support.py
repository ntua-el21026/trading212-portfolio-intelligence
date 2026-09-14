"""Real signed identities and SDK transport; synthetic data preparation only is reused."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import anyio
import httpx2
import jwt
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from sqlalchemy import select
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_persistence.base import Base
from trading212_persistence.models import PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator

from tests.integration.phase2_authorization_cases import (
    REPORT_STATE,
    AccountPin,
    retained_state,
)
from tests.integration.phase2_mcp_owner_resources import IntelligenceOwners
from tests.integration.test_phase2_intelligence_mcp_owners_postgres import STATE as PLANNING_STATE
from tests.jwt_support import JwtTestSigner

ISSUER = "https://identity.example.test/tenant"
ORIGIN = "https://portfolio.example"
RESOURCE = ORIGIN + "/mcp"
METADATA = "/.well-known/oauth-protected-resource/mcp"
PLAN = "create_contribution_plan"
REPORT = "generate_portfolio_report"
COMMAND_SCOPES = {
    PLAN: frozenset(
        {Scope.PORTFOLIO_READ, Scope.TARGETS_READ, Scope.ANALYTICS_READ, Scope.PLANS_WRITE}
    ),
    REPORT: frozenset(
        {
            Scope.PORTFOLIO_READ,
            Scope.ACTIVITY_READ,
            Scope.TARGETS_READ,
            Scope.ANALYTICS_READ,
            Scope.REPORTS_WRITE,
        }
    ),
}
STATE = tuple(
    dict.fromkeys(
        (
            *REPORT_STATE,
            *PLANNING_STATE,
            "contribution_plan_catalog",
            "contribution_plan_request_constraints",
            "contribution_plan_selections",
            "contribution_plan_holding_constraints",
            "contribution_plan_sources",
            "contribution_plan_attempts",
            "principals",
            "principal_scope_grants",
        )
    )
)


@dataclass(repr=False)
class SecretGuard:
    """Check before assertions can reflect data; never include a needle in a failure."""

    caplog: pytest.LogCaptureFixture
    capsys: pytest.CaptureFixture[str]
    _needles: list[str] = field(default_factory=list, repr=False)
    _log_leak: bool = field(default=False, repr=False)

    def __repr__(self) -> str:
        return "SecretGuard(redacted=True)"

    def remember(self, *values: str) -> None:
        self._needles.extend(value for value in values if value)

    def contains_secret(self, rendered: str) -> bool:
        markers = tuple(
            f"-----BEGIN {kind} KEY-----" for kind in ("PRIVATE", "RSA PRIVATE", "EC PRIVATE")
        )
        return any(value in rendered for value in (*self._needles, *markers))

    def protect_log(self, record: logging.LogRecord) -> logging.LogRecord:
        """Fail on a leak, but redact before pytest/file/console handlers can retain it."""
        __tracebackhide__ = True
        rendered = record.getMessage()
        if record.exc_info:
            rendered += logging.Formatter().formatException(record.exc_info)
        if self.contains_secret(rendered + (record.stack_info or "")):
            self._log_leak = True
            record.msg = "Sensitive authentication material withheld; canary check will fail."
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return record

    def check(self, rendered: str) -> None:
        __tracebackhide__ = True
        if self.contains_secret(rendered):
            # Do not let pytest turn a detected leak into a persisted failure artifact.
            for phase in ("setup", "call", "teardown"):
                self.caplog.get_records(phase).clear()
            self.caplog.clear()
            self.capsys.readouterr()
            pytest.fail("Sensitive authentication material escaped its boundary.", pytrace=False)

    def finish(self) -> None:
        __tracebackhide__ = True
        captured = self.capsys.readouterr()
        self.check(captured.out + captured.err + self.caplog.text)
        for phase in ("setup", "call", "teardown"):
            for record in self.caplog.get_records(phase):
                self.check(repr(record.__dict__))
        if self._log_leak:
            pytest.fail(
                "Sensitive authentication material reached logging; output redacted.", pytrace=False
            )


@dataclass(frozen=True, repr=False)
class SignedOwner:
    principal_id: UUID
    owner_id: UUID
    subject: str
    accounts: tuple[AccountPin, AccountPin]

    def __repr__(self) -> str:
        return "SignedOwner(redacted=True)"


def provision_owners(case: IntelligenceOwners) -> tuple[SignedOwner, SignedOwner]:
    """Provision trusted mappings, never derive an owner/grant from a bearer claim."""
    owners = [
        SignedOwner(
            uuid4(),
            UUID(actor.principal.owner_id),
            "provider|mcp-" + uuid4().hex,
            actor.accounts,
        )
        for actor in case.grid.actors
    ]
    with case.grid.sessions() as session, session.begin():
        for owner in owners:
            session.add(
                PrincipalModel(
                    id=owner.principal_id,
                    owner_id=owner.owner_id,
                    issuer=ISSUER,
                    subject=owner.subject,
                    status="active",
                    last_authenticated_at=None,
                )
            )
            session.flush()
            provision_principal_scopes(
                session,
                principal_id=owner.principal_id,
                scopes=frozenset(Scope),
                now=case.grid.at - timedelta(seconds=1),
            )
    return owners[0], owners[1]


def command_arguments(
    case: IntelligenceOwners,
    owner: SignedOwner,
    tool: str,
    *,
    key: str | None = None,
) -> dict[str, Any]:
    pin = owner.accounts[0]
    common = {
        "account_id": str(pin.account_id),
        "snapshot_id": str(pin.snapshot_id),
        "idempotency_key": key or uuid4().hex,
    }
    if tool == PLAN:
        target = case.plans[pin.account_id].target
        return {
            **common,
            "virtual_portfolio_id": target.portfolio.id,
            "target_version_id": target.version.id,
            "contribution": {"amount": "20", "currency": "EUR"},
            "mode": "global",
            "coverage_policy": "allow_degraded",
        }
    assert tool == REPORT
    return {
        **common,
        "start_date": case.grid.at.date().isoformat(),
        "end_date": case.grid.at.date().isoformat(),
        "source_cutoff_at": case.grid.at.isoformat(),
        "reporting_currency": "EUR",
        "report_type": "portfolio_summary",
        "format": "json",
        "sections": ["overview", "allocation", "quality"],
    }


def persistence(case: IntelligenceOwners) -> tuple[tuple[str, int, str], ...]:
    return retained_state(case.grid, STATE)


def check_persisted_canaries(case: IntelligenceOwners, guard: SecretGuard) -> None:
    __tracebackhide__ = True
    # Include payload chunks, command inputs and audit metadata, not just job counts.
    with case.grid.sessions() as session:
        for name in (*STATE, "audit_events", "planning_audit_events"):
            table = Base.metadata.tables[name]
            if name == "principals":
                # These are deliberately provisioned exact issuer/subject mappings.
                continue
            for row in session.execute(select(table)):
                guard.check(repr(tuple(row)))


@contextmanager
def unavailable_grant(
    case: IntelligenceOwners, owner: SignedOwner, scope: Scope, state: str
) -> Iterator[None]:
    with case.grid.sessions() as session, session.begin():
        row = session.get_one(PrincipalScopeGrantModel, (owner.principal_id, scope.value))
        previous = (row.granted_at, row.expires_at, row.revoked_at)
        if state == "revoked":
            row.revoked_at = case.grid.at
        elif state == "expired":
            row.expires_at = case.grid.at
        else:
            assert state == "missing"
            session.delete(row)
    try:
        yield
    finally:
        with case.grid.sessions() as session, session.begin():
            restored = session.get(PrincipalScopeGrantModel, (owner.principal_id, scope.value))
            if restored is None:
                restored = PrincipalScopeGrantModel(
                    principal_id=owner.principal_id, scope=scope.value
                )
                session.add(restored)
            restored.granted_at, restored.expires_at, restored.revoked_at = previous


def mint(
    signer: JwtTestSigner,
    owner: SignedOwner,
    guard: SecretGuard,
    *,
    scopes: frozenset[Scope],
    fault: str | None,
) -> str | None:
    __tracebackhide__ = True
    if fault == "anonymous":
        return None
    now = int(datetime.now(UTC).timestamp())
    marker = "jwt-private-claim-" + uuid4().hex
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": RESOURCE,
        "sub": owner.subject,
        "owner_id": str(owner.owner_id),
        "principal_id": str(owner.principal_id),
        "iat": now - 60,
        "nbf": now - 60,
        "exp": now + 3600,
        "scope": " ".join(sorted(scope.value for scope in scopes)),
        "private_canary": marker,
    }
    guard.remember(marker, owner.subject, signer.public_key.decode())
    mutations: dict[str, tuple[str, Any]] = {
        "wrong-issuer": ("iss", ISSUER + "/other"),
        "issuer-slash": ("iss", ISSUER + "/"),
        "issuer-case": ("iss", ISSUER.replace("identity", "Identity")),
        "wrong-audience": ("aud", RESOURCE + "/other"),
        "expired": ("exp", now - 120),
        "future-not-before": ("nbf", now + 3600),
        "future-issued": ("iat", now + 3600),
        "malformed-expiry": ("exp", {"private": marker}),
        "overflow-expiry": ("exp", 10**100),
        "malformed-issued": ("iat", {"private": marker}),
        "malformed-not-before": ("nbf", {"private": marker}),
        "malformed-subject": ("sub", {"private": marker}),
        "control-subject": ("sub", owner.subject + "\n"),
        "invalid-owner": ("owner_id", "invalid/owner"),
        "invalid-principal": ("principal_id", "invalid/principal"),
        "unknown-scope": ("scope", "portfolio:read trade:write"),
        "malformed-scope": ("scope", ["portfolio:read"]),
        "empty-scope": ("scope", ""),
        "oversized-token": ("private_canary", marker + "x" * 17_000),
    }
    if fault in mutations:
        name, value = mutations[fault]
        claims[name] = value
    elif fault and fault.startswith("missing-"):
        del claims[fault.removeprefix("missing-")]
    elif fault not in (None, "wrong-key", "unsigned", "symmetric", "untrusted-key-hint"):
        raise AssertionError("Unknown static authentication case.")
    try:
        if fault == "wrong-key":
            token = JwtTestSigner.generate(signer.algorithm).sign(claims)
        elif fault == "unsigned":
            token = jwt.encode(claims, key="", algorithm="none")
        elif fault == "symmetric":
            key = uuid4().hex + uuid4().hex
            guard.remember(key)
            token = jwt.encode(claims, key=key, algorithm="HS256")
        else:
            headers = (
                {"jku": "https://untrusted-key.example.test/keys", "kid": marker}
                if fault == "untrusted-key-hint"
                else None
            )
            token = signer.sign(claims, headers=headers)
    except Exception:
        raise AssertionError("Ephemeral test signing failed.") from None
    # Cover the complete bearer, encoded payload and decoded payload independently.
    guard.remember(token, token.split(".")[1], json.dumps(claims, separators=(",", ":")))
    return token


def safe_failure_location(error: BaseException) -> str:
    """Expose bounded exception classes and authored test lines, never error text/locals."""
    __tracebackhide__ = True
    pending = [error]
    locations: list[str] = []
    while pending and len(locations) < 4:
        current = pending.pop()
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions[:4])
            continue
        name = type(current).__name__
        if not name.isascii() or not name.isidentifier() or len(name) > 64:
            name = "Exception"
        location = "test-line-unavailable"
        traceback = current.__traceback__
        while traceback is not None:
            filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
            if filename == "test_real_jwt_mcp_postgres.py":
                location = f"{filename}:{traceback.tb_lineno}"
            traceback = traceback.tb_next
        locations.append(f"{name} at {location}")
    return "; ".join(locations) or "Exception at test-line-unavailable"


@dataclass(repr=False)
class SignedTransport:
    client: httpx2.AsyncClient
    guard: SecretGuard

    def __repr__(self) -> str:
        return "SignedTransport(redacted=True)"

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        __tracebackhide__ = True
        try:
            async with (
                streamable_http_client(
                    RESOURCE, http_client=self.client, terminate_on_close=False
                ) as (read, write),
                ClientSession(read, write, read_timeout_seconds=20) as session,
            ):
                initialized = await session.initialize()
                self.guard.check(initialized.model_dump_json())
                yield session
        except Exception as error:
            self.guard.finish()
            raise AssertionError(
                f"Signed MCP SDK exchange failed: {safe_failure_location(error)}."
            ) from None

    async def call(
        self, session: ClientSession, name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        __tracebackhide__ = True
        result = await session.call_tool(name, arguments)
        self.guard.check(result.model_dump_json())
        assert result.structured_content is not None, "Missing MCP structured result."
        RESULT_MODELS[name].model_validate(result.structured_content)
        return result

    async def raw(self, method: str, params: dict[str, Any]) -> httpx2.Response:
        __tracebackhide__ = True
        try:
            response = await self.client.post(
                RESOURCE,
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
        except Exception as error:
            self.guard.finish()
            raise AssertionError(
                f"MCP HTTP exchange failed: {safe_failure_location(error)}."
            ) from None
        self.guard.check(response.text + str(response.headers))
        return response


@asynccontextmanager
async def signed_transport(
    case: IntelligenceOwners,
    owner: SignedOwner,
    signer: JwtTestSigner,
    guard: SecretGuard,
    *,
    scopes: frozenset[Scope] = frozenset(Scope),
    fault: str | None = None,
) -> AsyncIterator[SignedTransport]:
    __tracebackhide__ = True
    token = mint(signer, owner, guard, scopes=scopes, fault=fault)
    authenticator = JwtAuthenticator(
        issuer=ISSUER,
        audience=RESOURCE,
        public_key=signer.public_key,
        clock_skew_seconds=30,
    )
    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=False,
            issuer=ISSUER,
            audience=RESOURCE,
            allowed_hosts=("portfolio.example",),
            allowed_origins=(ORIGIN,),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": ORIGIN}),
        service=case.grid.portfolio,
        target_service=case.targets,
        planning_service=case.planning,
        historical_service=case.history,
        report_service=case.grid.reports,
        alert_service=case.grid.alerts,
        bearer_authenticator=authenticator,
    )
    application = runtime.asgi_app()
    # ASGITransport does not drive lifespan. Use this exact SDK manager once per runtime.
    try:
        with anyio.fail_after(60):
            async with (
                runtime.server.session_manager.run(),
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(application),
                    base_url=ORIGIN,
                    headers={} if token is None else {"Authorization": "Bearer " + token},
                    follow_redirects=False,
                    trust_env=False,
                    timeout=20,
                ) as client,
            ):
                yield SignedTransport(client, guard)
    finally:
        # Inspect while still in pytest's call phase, before reports capture stdout/logs.
        guard.finish()
