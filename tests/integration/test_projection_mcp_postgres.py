"""Real signed SDK transport over saved PostgreSQL projections and current grants."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import func, select
from trading212_api_contracts.projections import ProjectionRunResponse
from trading212_application.projection import ProjectionPointPageQuery
from trading212_domain.serialization import to_primitive
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_persistence import PostgresPortfolioService
from trading212_persistence.models import PrincipalModel
from trading212_persistence.projection_models import ProjectionResultModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator
from trading212_worker.projection_tasks import ProjectionExecutionState, execute_projection_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.real_jwt_mcp_support import (
    ISSUER,
    ORIGIN,
    RESOURCE,
    SecretGuard,
    SignedTransport,
)
from tests.integration.test_projection_jobs_postgres import store
from tests.integration.test_real_jwt_mcp_postgres import guard as guard
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.jwt_support import JwtTestSigner
from tests.mcp_discovery import assert_current_tool_inventory

pytestmark = pytest.mark.integration


async def test_signed_projection_sdk_replay_whole_pages_and_current_account_grants(
    projection_job_case: ProjectionJobCase, guard: SecretGuard
) -> None:
    __tracebackhide__ = True
    case = projection_job_case
    principal = replace(
        case.principal,
        principal_id=str(uuid4()),
        issuer=ISSUER,
        subject="projection-mcp-owner-" + uuid4().hex,
    )
    with case.sessions() as session, session.begin():
        session.add(
            PrincipalModel(
                id=UUID(principal.principal_id),
                owner_id=UUID(principal.owner_id),
                issuer=principal.issuer,
                subject=principal.subject,
                status="active",
            )
        )
        session.flush()
        for scope in principal.scopes:
            session.add(
                PrincipalScopeGrantModel(
                    principal_id=UUID(principal.principal_id),
                    scope=scope.value,
                    granted_at=case.now,
                    expires_at=None,
                    revoked_at=None,
                )
            )
    case.principal = principal
    signer = JwtTestSigner.generate("ES256")

    def authorization(**changes: object) -> str:
        now = int(datetime.now(UTC).timestamp())
        value = signer.sign_raw_claims(
            {
                "iss": principal.issuer,
                "aud": RESOURCE,
                "sub": principal.subject,
                "owner_id": principal.owner_id,
                "principal_id": principal.principal_id,
                "scope": " ".join(sorted(scope.value for scope in principal.scopes)),
                "iat": now - 1,
                "exp": now + 3600,
                **changes,
            }
        )
        guard.remember(value)
        return "Bearer " + value

    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=False,
            issuer=principal.issuer,
            audience=RESOURCE,
            allowed_hosts=("portfolio.example",),
            allowed_origins=(ORIGIN,),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": ORIGIN}),
        service=PostgresPortfolioService(
            sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
        ),
        projection_service=case.service,
        bearer_authenticator=JwtAuthenticator(
            issuer=principal.issuer,
            audience=RESOURCE,
            public_key=signer.public_key,
            clock_skew_seconds=0,
        ),
        clock=lambda: case.now,
    )
    arguments = cast(dict[str, Any], to_primitive(case.command.selection))
    arguments["initial_basis"] = arguments.pop("initial")
    arguments["idempotency_key"] = case.command.idempotency_key
    application = runtime.asgi_app()
    async with (
        runtime.server.session_manager.run(),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(application),
            base_url=ORIGIN,
            headers={"Authorization": authorization()},
            follow_redirects=False,
            trust_env=False,
            timeout=20,
        ) as http,
    ):
        connection = SignedTransport(http, guard)
        async with connection.session() as client:
            descriptors = await client.list_tools()
            guard.check(descriptors.model_dump_json())
            assert_current_tool_inventory(descriptors.tools)
            created = await connection.call(client, "create_projection_run", arguments)
            assert not created.is_error and created.structured_content is not None
            queued = created.structured_content["data"]
            assert queued["id"] == str(case.run.id) and queued["state"] == "queued"
            assert queued["result"] is None
            replay = await connection.call(client, "create_projection_run", arguments)
            assert replay.structured_content == created.structured_content
            conflict = await connection.call(
                client, "create_projection_run", {**arguments, "seed": arguments["seed"] + 1}
            )
            assert conflict.is_error and conflict.structured_content is not None
            assert conflict.structured_content["error"]["code"] == "CONFLICT"
            worker = store(case)
            (dispatch,) = await worker.claim_projection_dispatches(dispatcher_id="projection-mcp")
            assert await worker.acknowledge_projection_dispatch(dispatch)
            assert (
                await execute_projection_message(
                    worker, dispatch.message, consumer_id="projection-mcp", clock=lambda: case.now
                )
                is ProjectionExecutionState.SUCCEEDED
            )
            query = ProjectionPointPageQuery(point_limit=3)
            identity = {
                "account_id": str(case.command.selection.account_id),
                "run_id": str(case.run.id),
            }
            rows: list[tuple[str, int, int]] = []
            while True:
                result = await connection.call(
                    client,
                    "get_projection",
                    {
                        **identity,
                        "point_limit": 3,
                        "point_cursor": query.point_cursor,
                    },
                )
                assert not result.is_error and result.structured_content is not None
                assert len(result.model_dump_json().encode()) <= 2 * 1024 * 1024
                expected = await case.service.get_run(principal, case.run.id, query)
                assert result.structured_content["data"] == ProjectionRunResponse.model_validate(
                    to_primitive(expected)
                ).model_dump(mode="json")
                page = result.structured_content["data"]["result"]["points"]
                rows.extend(
                    (p["variant"], p["path_index"], p["point_index"]) for p in page["items"]
                )
                if page["next_cursor"] is None:
                    assert len(rows) == len(set(rows)) == page["total"] == 28
                    break
                query = ProjectionPointPageQuery(point_limit=3, point_cursor=page["next_cursor"])
            goals = await connection.call(
                client, "list_goals", {"account_id": identity["account_id"]}
            )
            assert not goals.is_error and goals.structured_content is not None
            assert goals.structured_content["data"]["items"] == []
            goal = await connection.call(client, "get_goal_analysis", identity)
            assert not goal.is_error and goal.structured_content is not None
            assert goal.structured_content["data"]["reason"] == "no_goal_pinned"
            assert goal.structured_content["data"]["context"] is None
            foreign = await connection.call(
                client,
                "get_projection",
                {**identity, "account_id": str(uuid4()), "point_cursor": "malformed"},
            )
            assert foreign.is_error and foreign.structured_content is not None
            assert foreign.structured_content["error"]["code"] == "NOT_FOUND"
            with case.sessions() as session, session.begin():
                actual_principal = session.scalar(
                    select(PrincipalModel).where(
                        PrincipalModel.issuer == principal.issuer,
                        PrincipalModel.subject == principal.subject,
                    )
                )
                assert actual_principal is not None
                session.get_one(
                    PrincipalScopeGrantModel,
                    (
                        actual_principal.id,
                        Scope.ANALYTICS_READ.value,
                    ),
                ).revoked_at = case.now
            denied = await connection.call(
                client, "get_projection", {**identity, "point_cursor": "malformed"}
            )
            assert denied.is_error and denied.structured_content is not None
            assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
            assert denied.structured_content["data"] is None
        http.headers["Authorization"] = authorization(aud=RESOURCE + "/wrong")
        rejected = await connection.raw("tools/list", {})
        assert rejected.status_code == 401
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionResultModel)
                .where(ProjectionResultModel.run_id == UUID(str(case.run.id)))
            )
            == 1
        )
    guard.finish()
