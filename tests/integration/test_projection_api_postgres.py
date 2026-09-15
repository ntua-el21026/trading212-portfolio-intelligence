"""Real JWT and PostgreSQL projection replay, worker publication, paging and current grants."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from trading212_api.main import create_app
from trading212_api_contracts.projections import ProjectionRunResponse
from trading212_application.projection import ProjectionPointPageQuery
from trading212_domain.serialization import to_primitive
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
from tests.integration.real_jwt_mcp_support import SecretGuard
from tests.integration.test_projection_jobs_postgres import store
from tests.integration.test_real_jwt_mcp_postgres import guard as guard
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.jwt_support import JwtTestSigner

pytestmark = pytest.mark.integration
ORIGIN = "https://projection.example.test"
AUDIENCE = ORIGIN + "/api"


async def test_signed_projection_lifecycle_whole_pages_and_revoked_grants(
    projection_job_case: ProjectionJobCase, guard: SecretGuard
) -> None:
    __tracebackhide__ = True
    case = projection_job_case
    principal = case.principal
    signer = JwtTestSigner.generate("ES256")

    def headers(**changes: object) -> dict[str, str]:
        claims = {
            "iss": principal.issuer,
            "aud": AUDIENCE,
            "sub": principal.subject,
            "owner_id": principal.owner_id,
            "principal_id": principal.principal_id,
            "scope": " ".join(sorted(scope.value for scope in principal.scopes)),
            "iat": int(case.now.timestamp()) - 1,
            "exp": int(case.now.timestamp()) + 3600,
            **changes,
        }
        token = signer.sign_raw_claims(claims)
        guard.remember(token)
        return {
            "Authorization": "Bearer " + token,
            "X-Idempotency-Key": case.command.idempotency_key,
        }

    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("projection.example.test",),
            local_synthetic_auth_enabled=False,
        ),
        service=PostgresPortfolioService(
            sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now
        ),
        projection_service=case.service,
        bearer_authenticator=JwtAuthenticator(
            issuer=principal.issuer,
            audience=AUDIENCE,
            public_key=signer.public_key,
            clock=lambda: case.now,
            clock_skew_seconds=0,
        ),
        clock=lambda: case.now,
    )
    body = to_primitive(case.command.selection)
    del body["account_id"]
    body["initial_basis"] = body.pop("initial")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url=ORIGIN, follow_redirects=False, trust_env=False
    ) as client:
        path = f"/api/v1/accounts/{case.command.selection.account_id}/projection-runs"
        admission = await client.post(path, json=body, headers=headers())
        guard.check(admission.text)
        assert admission.status_code == 202 and admission.json()["id"] == str(case.run.id)
        assert admission.json()["result"] is None and admission.json()["state"] == "queued"
        replay = await client.post(
            path, json=body, headers={**headers(), "X-Correlation-ID": "projection-api-retry"}
        )
        assert replay.status_code == 202 and replay.json()["id"] == str(case.run.id)
        worker = store(case)
        (dispatch,) = await worker.claim_projection_dispatches(dispatcher_id="projection-api-test")
        assert await worker.acknowledge_projection_dispatch(dispatch)
        assert (
            await execute_projection_message(
                worker, dispatch.message, consumer_id="projection-api-test", clock=lambda: case.now
            )
            is ProjectionExecutionState.SUCCEEDED
        )
        detail_path = f"/api/v1/projection-runs/{case.run.id}"
        query = ProjectionPointPageQuery(point_limit=3)
        observed: list[tuple[str, int, int]] = []
        first_etag = None
        while True:
            parameters = {"point_limit": "3"}
            if query.point_cursor is not None:
                parameters["point_cursor"] = query.point_cursor
            detail = await client.get(detail_path, params=parameters, headers=headers())
            guard.check(detail.text)
            assert detail.status_code == 200 and len(detail.content) <= 2 * 1024 * 1024
            expected = await case.service.get_run(principal, case.run.id, query)
            assert detail.json() == ProjectionRunResponse.model_validate(
                to_primitive(expected)
            ).model_dump(mode="json")
            page = detail.json()["result"]["points"]
            assert 1 <= len(page["items"]) <= 3
            observed.extend(
                (row["variant"], row["path_index"], row["point_index"]) for row in page["items"]
            )
            if first_etag is None:
                first_etag = detail.headers["etag"]
            if page["next_cursor"] is None:
                assert len(observed) == page["total"] and len(set(observed)) == len(observed)
                break
            query = ProjectionPointPageQuery(point_limit=3, point_cursor=page["next_cursor"])
        unchanged = await client.get(
            detail_path,
            params={"point_limit": "3"},
            headers={**headers(), "If-None-Match": first_etag},
        )
        assert unchanged.status_code == 304
        listing = await client.get(path, headers=headers())
        guard.check(listing.text)
        assert listing.status_code == 200 and listing.json()["items"][0]["result"] is None
        assert listing.json()["items"][0]["result_availability"] == "not_loaded"
        goal = await client.get(detail_path + "/goal-analysis", headers=headers())
        guard.check(goal.text)
        assert goal.status_code == 200
        assert goal.json()["availability"] == "unavailable"
        assert goal.json()["reason"] == "no_goal_pinned"
        assert goal.json()["context"] is None and goal.json()["variants"] == []
        for changes, status in (
            ({"aud": AUDIENCE + "/"}, 401),
            ({"owner_id": str(uuid4())}, 404),
            ({"scope": "projections:write"}, 403),
        ):
            denied = await client.get(
                detail_path, headers={**headers(**changes), "If-None-Match": "*"}
            )
            guard.check(denied.text)
            assert denied.status_code == status
        with case.sessions() as session, session.begin():
            identity = session.scalar(
                select(PrincipalModel).where(
                    PrincipalModel.issuer == principal.issuer,
                    PrincipalModel.subject == principal.subject,
                )
            )
            assert identity is not None
            grant = session.get_one(
                PrincipalScopeGrantModel, (identity.id, Scope.ANALYTICS_READ.value)
            )
            grant.revoked_at = case.now
        denied = await client.get(
            detail_path,
            params={"point_limit": "3", "point_cursor": "malformed"},
            headers={**headers(), "If-None-Match": "*"},
        )
        guard.check(denied.text)
        assert denied.status_code == 403
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionResultModel)
                .where(ProjectionResultModel.run_id == case.run.id)
            )
            == 1
        )
    guard.finish()
