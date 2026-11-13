"""Signed-token PostgreSQL MCP regressions; no real IdP, sockets or auth stubs."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import httpx2
import pytest
from mcp.types import TextResourceContents
from sqlalchemy import func, select
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.widget import SNAPSHOT_WIDGET_URI
from trading212_persistence.planning_models import (
    ContributionPlanJobModel,
    ContributionPlanModel,
    ContributionPlanOutboxModel,
)
from trading212_persistence.report_models import ReportDispatchOutboxModel, ReportJobModel
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_mcp_owner_resources import IntelligenceOwners
from tests.integration.phase2_mcp_owner_resources import intelligence_owners as intelligence_owners
from tests.integration.phase2_mcp_owner_transport import denied, mapping, payload
from tests.integration.real_jwt_mcp_support import (
    COMMAND_SCOPES,
    ISSUER,
    METADATA,
    ORIGIN,
    PLAN,
    REPORT,
    RESOURCE,
    SecretGuard,
    SignedOwner,
    check_persisted_canaries,
    command_arguments,
    persistence,
    provision_owners,
    signed_transport,
    unavailable_grant,
)
from tests.integration.test_alert_postgres import alert_database as alert_database
from tests.jwt_support import JwtTestSigner
from tests.mcp_discovery import assert_current_tool_inventory
from tests.mcp_registry_cases import CASES

pytestmark = pytest.mark.integration
ALGORITHMS = ("RS256", "ES256", "EdDSA")


@pytest.fixture(scope="module")
def signed_owners(intelligence_owners: IntelligenceOwners) -> tuple[SignedOwner, SignedOwner]:
    return provision_owners(intelligence_owners)


@pytest.fixture(scope="module")
def signers() -> dict[str, JwtTestSigner]:
    return {algorithm: JwtTestSigner.generate(algorithm) for algorithm in ALGORITHMS}


@pytest.fixture
def guard(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SecretGuard]:
    caplog.set_level(logging.INFO)
    value = SecretGuard(caplog, capsys)

    async def no_async_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Real JWT MCP tests forbid outbound HTTP.")

    def no_sync_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Real JWT MCP tests forbid outbound HTTP.")

    # The actual ASGI transports remain intact; trusted keys never require a fetch.
    for library in (httpx, httpx2):
        monkeypatch.setattr(library.AsyncHTTPTransport, "handle_async_request", no_async_network)
        monkeypatch.setattr(library.HTTPTransport, "handle_request", no_sync_network)
    original_factory = logging.getLogRecordFactory()

    def protect_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
        return value.protect_log(original_factory(*args, **kwargs))

    logging.setLogRecordFactory(protect_record)
    try:
        yield value
    finally:
        try:
            value.finish()
        finally:
            logging.setLogRecordFactory(original_factory)


@pytest.fixture
def command_calls(
    intelligence_owners: IntelligenceOwners, monkeypatch: pytest.MonkeyPatch
) -> dict[str, int]:
    """Observe invocation without replacing the real PostgreSQL command implementations."""
    counts = {PLAN: 0, REPORT: 0}
    planning = intelligence_owners.planning.create_contribution_plan
    reporting = intelligence_owners.grid.reports.generate_report

    async def plan(*args: Any, **kwargs: Any) -> Any:
        counts[PLAN] += 1
        return await planning(*args, **kwargs)

    async def report(*args: Any, **kwargs: Any) -> Any:
        counts[REPORT] += 1
        return await reporting(*args, **kwargs)

    monkeypatch.setattr(intelligence_owners.planning, "create_contribution_plan", plan)
    monkeypatch.setattr(intelligence_owners.grid.reports, "generate_report", report)
    return counts


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=("rsa", "ec", "edwards"))
async def test_real_jwt_discovery_resources_and_original_phase2_reads(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
    algorithm: str,
) -> None:
    case = intelligence_owners
    for owner, other in (signed_owners, tuple(reversed(signed_owners))):
        async with signed_transport(case, owner, signers[algorithm], guard) as transport:
            metadata = await transport.client.get(METADATA)
            guard.check(metadata.text)
            assert metadata.status_code == 200
            assert metadata.json() == {
                "resource": RESOURCE,
                "authorization_servers": [ISSUER],
                "scopes_supported": [],
                "bearer_methods_supported": ["header"],
            }
            assert metadata.headers["cache-control"] == "no-store"
            async with transport.session() as session:
                listed = await session.list_tools()
                guard.check(listed.model_dump_json())
                descriptors = {
                    tool.name: tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for tool in listed.tools
                }
                assert_current_tool_inventory(listed.tools)
                assert len(listed.tools) == len(descriptors)
                for expected in CASES:
                    descriptor = descriptors[expected.name]
                    assert descriptor["annotations"] == {
                        "readOnlyHint": not expected.command,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": False,
                    }
                    schemes = descriptor["_meta"]["securitySchemes"]
                    assert len(schemes) == 1 and schemes[0]["type"] == "oauth2"
                    assert set(schemes[0]["scopes"]) == set(expected.scopes)
                    assert len(schemes[0]["scopes"]) == len(expected.scopes)
                    assert descriptor["inputSchema"]["additionalProperties"] is False
                    assert descriptor["outputSchema"] == RESULT_MODELS[
                        expected.name
                    ].model_json_schema(by_alias=True)

                resources = await session.list_resources()
                guard.check(resources.model_dump_json())
                assert SNAPSHOT_WIDGET_URI in {str(item.uri) for item in resources.resources}
                resource = await session.read_resource(SNAPSHOT_WIDGET_URI)
                guard.check(resource.model_dump_json())
                assert len(resource.contents) == 1
                content = resource.contents[0]
                assert isinstance(content, TextResourceContents)
                assert content.meta is not None
                assert content.meta["openai/widgetCSP"] == {
                    "connect_domains": [],
                    "resource_domains": [],
                }
                assert "<html" in content.text

                for pin in owner.accounts:
                    summary = payload(
                        await transport.call(
                            session, "get_account_summary", {"account_id": str(pin.account_id)}
                        )
                    )
                    assert mapping(summary["account"])["id"] == str(pin.account_id)
                    snapshot = payload(
                        await transport.call(
                            session,
                            "get_portfolio_snapshot",
                            {
                                "account_id": str(pin.account_id),
                                "snapshot_id": str(pin.snapshot_id),
                            },
                        )
                    )
                    assert snapshot["id"] == str(pin.snapshot_id)
                    assert str(other.accounts[0].account_id) not in str(snapshot)
                pin = owner.accounts[0]
                saved = case.plans[pin.account_id]
                target = payload(
                    await transport.call(
                        session,
                        "get_virtual_pie",
                        {
                            "account_id": str(pin.account_id),
                            "virtual_portfolio_id": saved.target.portfolio.id,
                            "target_version_id": saved.target.version.id,
                        },
                    )
                )
                assert mapping(target["portfolio"])["account_id"] == str(pin.account_id)
                plan = payload(
                    await transport.call(
                        session,
                        "get_contribution_plan",
                        {"account_id": str(pin.account_id), "plan_id": saved.job.plan_id},
                    )
                )
                assert mapping(plan["job"])["state"] == "succeeded"
                assert plan["result"] is not None
                day = (case.grid.at.date() - timedelta(days=1)).isoformat()
                history = payload(
                    await transport.call(
                        session,
                        "get_performance_summary",
                        {
                            "account_id": str(pin.account_id),
                            "start_date": day,
                            "end_date": day,
                            "source_cutoff_at": case.grid.at.isoformat(),
                            "reporting_currency": "EUR",
                        },
                    )
                )
                # No historical coverage is invented by this identity regression.
                assert mapping(history["context"])["account_id"] == str(pin.account_id)
                assert isinstance(mapping(history["context"])["input_snapshot_id"], str)
    check_persisted_canaries(case, guard)


@pytest.mark.parametrize("algorithm", ALGORITHMS, ids=("rsa", "ec", "edwards"))
@pytest.mark.parametrize("tool", (PLAN, REPORT), ids=("plan", "report"))
async def test_real_jwt_commands_require_exact_scopes_and_semantic_idempotency(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
    command_calls: dict[str, int],
    algorithm: str,
    tool: str,
) -> None:
    case = intelligence_owners
    shared_key = uuid4().hex
    jobs: list[str] = []
    for owner in signed_owners:
        request = command_arguments(case, owner, tool, key=shared_key)
        async with (
            signed_transport(
                case, owner, signers[algorithm], guard, scopes=COMMAND_SCOPES[tool]
            ) as transport,
            transport.session() as session,
        ):
            created = payload(await transport.call(session, tool, request))
            assert created["state"] == "queued"
            assert created["account_id"] == str(owner.accounts[0].account_id)
            job_id = str(created["job_id"])
            jobs.append(job_id)
            with case.grid.sessions() as database:
                if tool == PLAN:
                    plan_job = database.get_one(ContributionPlanJobModel, UUID(job_id))
                    plan_row = database.get_one(
                        ContributionPlanModel, UUID(str(created["plan_id"]))
                    )
                    assert plan_job.owner_id == plan_row.owner_id == owner.owner_id
                    assert str(plan_row.broker_account_id) == request["account_id"]
                    outbox_query = (
                        select(func.count())
                        .select_from(ContributionPlanOutboxModel)
                        .where(ContributionPlanOutboxModel.job_id == plan_job.id)
                    )
                else:
                    report_job = database.get_one(ReportJobModel, UUID(job_id))
                    assert report_job.owner_id == owner.owner_id
                    assert str(report_job.account_id) == request["account_id"]
                    assert report_job.principal_id == owner.principal_id
                    outbox_query = (
                        select(func.count())
                        .select_from(ReportDispatchOutboxModel)
                        .where(ReportDispatchOutboxModel.job_id == report_job.id)
                    )
                assert database.scalar(outbox_query) == 1
            before = persistence(case)
            retry = dict(reversed(tuple(request.items())))
            if tool == PLAN:
                retry["contribution"] = {"amount": "20.000", "currency": "EUR"}
            assert payload(await transport.call(session, tool, retry)) == created
            changed = {
                **request,
                **(
                    {"contribution": {"amount": "21", "currency": "EUR"}}
                    if tool == PLAN
                    # Required sections stay intact: change a valid semantic input.
                    else {"format": "csv"}
                ),
            }
            denied(
                await transport.call(session, tool, changed),
                "IDEMPOTENCY_KEY_REUSED",
                (job_id,),
            )
            assert persistence(case) == before
            # Report creation does not supply the independent reports:read scope.
            read = "get_contribution_plan" if tool == PLAN else "get_report_status"
            read_args = {
                "account_id": request["account_id"],
                **({"plan_id": created["plan_id"]} if tool == PLAN else {"report_job_id": job_id}),
            }
            if tool == REPORT:
                denied(await transport.call(session, read, read_args), "ACCESS_DENIED", (job_id,))
        if tool == REPORT:
            async with (
                signed_transport(case, owner, signers[algorithm], guard) as transport,
                transport.session() as session,
            ):
                status = payload(await transport.call(session, "get_report_status", read_args))
                assert status["job_id"] == job_id and status["state"] == "queued"
    assert jobs[0] != jobs[1]
    assert command_calls[tool] == 6
    assert command_calls[REPORT if tool == PLAN else PLAN] == 0
    check_persisted_canaries(case, guard)


@pytest.mark.parametrize("tool", (PLAN, REPORT), ids=("plan", "report"))
async def test_real_jwt_each_missing_command_scope_blocks_before_service(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
    command_calls: dict[str, int],
    tool: str,
) -> None:
    case, owner = intelligence_owners, signed_owners[0]
    request = command_arguments(case, owner, tool)
    before = persistence(case)
    for omitted in sorted(COMMAND_SCOPES[tool], key=lambda scope: scope.value):
        async with (
            signed_transport(
                case, owner, signers["RS256"], guard, scopes=COMMAND_SCOPES[tool] - {omitted}
            ) as transport,
            transport.session() as session,
        ):
            denied(
                await transport.call(session, tool, request),
                "ACCESS_DENIED",
                (str(owner.accounts[0].account_id),),
            )
        assert persistence(case) == before
    assert command_calls == {PLAN: 0, REPORT: 0}


@pytest.mark.parametrize(
    "fault",
    (
        "anonymous",
        "wrong-issuer",
        "issuer-slash",
        "issuer-case",
        "wrong-audience",
        "wrong-key",
        "unsigned",
        "symmetric",
        "expired",
        "future-not-before",
        "future-issued",
        "missing-exp",
        "missing-iat",
        "missing-iss",
        "missing-aud",
        "missing-sub",
        "missing-owner_id",
        "missing-principal_id",
        "malformed-expiry",
        "overflow-expiry",
        "malformed-issued",
        "malformed-not-before",
        "malformed-subject",
        "control-subject",
        "invalid-owner",
        "invalid-principal",
        "unknown-scope",
        "malformed-scope",
        "empty-scope",
        "oversized-token",
    ),
)
async def test_invalid_real_bearer_never_executes_or_persists_commands(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
    command_calls: dict[str, int],
    fault: str,
) -> None:
    case, owner = intelligence_owners, signed_owners[0]
    before = persistence(case)
    async with signed_transport(case, owner, signers["RS256"], guard, fault=fault) as transport:
        for method, params in (
            ("tools/list", {}),
            ("resources/list", {}),
            *(
                ("tools/call", {"name": tool, "arguments": command_arguments(case, owner, tool)})
                for tool in (PLAN, REPORT)
            ),
        ):
            response = await transport.raw(method, params)
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
            challenge = 'resource_metadata="' + ORIGIN + METADATA + '"'
            assert challenge in response.headers["www-authenticate"]
            assert "traceback" not in response.text.lower()
    assert command_calls == {PLAN: 0, REPORT: 0}
    assert persistence(case) == before
    check_persisted_canaries(case, guard)


async def test_signed_claims_cannot_cross_owner_account_or_selected_snapshot(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
) -> None:
    case = intelligence_owners
    for owner, other in (signed_owners, tuple(reversed(signed_owners))):
        async with (
            signed_transport(case, owner, signers["RS256"], guard) as transport,
            transport.session() as session,
        ):
            own = owner.accounts[0]
            for tool in (PLAN, REPORT):
                before = persistence(case)
                foreign = command_arguments(case, other, tool)
                denied(
                    await transport.call(session, tool, foreign),
                    "NOT_FOUND" if tool == PLAN else "ACCESS_DENIED",
                    (str(other.accounts[0].account_id), str(other.owner_id)),
                )
                for bad in (owner.accounts[1].snapshot_id, other.accounts[0].snapshot_id):
                    request = {**command_arguments(case, owner, tool), "snapshot_id": str(bad)}
                    denied(await transport.call(session, tool, request), "NOT_FOUND", (str(bad),))
                assert persistence(case) == before
            before = persistence(case)
            for account in (other.accounts[0].account_id, uuid4()):
                denied(
                    await transport.call(
                        session, "get_account_summary", {"account_id": str(account)}
                    ),
                    "ACCESS_DENIED",
                    (str(account),),
                )
            denied(
                await transport.call(
                    session,
                    "get_portfolio_snapshot",
                    {
                        "account_id": str(own.account_id),
                        "snapshot_id": str(owner.accounts[1].snapshot_id),
                    },
                ),
                "NOT_FOUND",
                (str(owner.accounts[1].snapshot_id),),
            )
            assert persistence(case) == before


@pytest.mark.parametrize("grant_state", ("missing", "revoked", "expired"))
async def test_signed_token_cannot_override_current_postgres_report_grants(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
    grant_state: str,
) -> None:
    case, owner = intelligence_owners, signed_owners[0]
    async with (
        signed_transport(case, owner, signers["RS256"], guard) as transport,
        transport.session() as session,
    ):
        request = command_arguments(case, owner, REPORT)
        created = payload(await transport.call(session, REPORT, request))
        selected = {"account_id": request["account_id"], "report_job_id": created["job_id"]}
        status = payload(await transport.call(session, "get_report_status", selected))
        assert status["job_id"] == created["job_id"]
        with unavailable_grant(case, owner, Scope.REPORTS_READ, grant_state):
            before = persistence(case)
            denied(
                await transport.call(session, "get_report_status", selected),
                "ACCESS_DENIED",
                (str(created["job_id"]),),
            )
            assert persistence(case) == before
        status = payload(await transport.call(session, "get_report_status", selected))
        assert status["job_id"] == created["job_id"]
        with unavailable_grant(case, owner, Scope.REPORTS_WRITE, grant_state):
            before = persistence(case)
            denied(
                await transport.call(session, REPORT, command_arguments(case, owner, REPORT)),
                "ACCESS_DENIED",
                (str(owner.accounts[0].account_id),),
            )
            assert persistence(case) == before
    check_persisted_canaries(case, guard)


async def test_signed_key_hint_cannot_fetch_keys_or_change_trusted_key_selection(
    intelligence_owners: IntelligenceOwners,
    signed_owners: tuple[SignedOwner, SignedOwner],
    signers: dict[str, JwtTestSigner],
    guard: SecretGuard,
) -> None:
    case, owner = intelligence_owners, signed_owners[0]
    async with (
        signed_transport(
            case, owner, signers["RS256"], guard, fault="untrusted-key-hint"
        ) as transport,
        transport.session() as session,
    ):
        value = payload(
            await transport.call(
                session,
                "get_account_summary",
                {"account_id": str(owner.accounts[0].account_id)},
            )
        )
        assert mapping(value["account"])["id"] == str(owner.accounts[0].account_id)
