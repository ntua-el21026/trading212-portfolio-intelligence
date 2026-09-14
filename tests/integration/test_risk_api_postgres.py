"""Actual signed JWT, PostgreSQL authority and subprocess-to-HTTP canonical parity."""

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from trading212_api.main import create_app
from trading212_api_contracts.risk import RiskRunResponse
from trading212_domain.serialization import to_primitive
from trading212_persistence import PostgresPortfolioService
from trading212_persistence.models import PrincipalModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.risk_models import RiskResultModel
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator
from trading212_worker.historical_seed import CURSOR_KEY
from trading212_worker.risk_tasks import RiskExecutionState, execute_risk_message

from tests.integration.real_jwt_mcp_support import SecretGuard
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_real_jwt_mcp_postgres import guard as guard
from tests.integration.test_risk_jobs_postgres import store
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case
from tests.jwt_support import JwtTestSigner

pytestmark = pytest.mark.integration
ORIGIN = "https://risk.example.test"
AUDIENCE = ORIGIN + "/api"


async def test_signed_risk_lifecycle_current_grants_and_canonical_parity(
    run_case: RunCase, guard: SecretGuard
) -> None:
    __tracebackhide__ = True
    case = run_case
    signer = JwtTestSigner.generate("ES256")
    principal = case.principal

    def headers(**changes: object) -> dict[str, str]:
        claims = {
            "iss": principal.issuer,
            "aud": AUDIENCE,
            "sub": principal.subject,
            "owner_id": principal.owner_id,
            "principal_id": principal.principal_id,
            "scope": " ".join(sorted(s.value for s in principal.scopes)),
            "iat": int(NOW.timestamp()) - 1,
            "exp": int(NOW.timestamp()) + 3600,
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
            allowed_hosts=("risk.example.test",),
            local_synthetic_auth_enabled=False,
        ),
        service=PostgresPortfolioService(
            sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
        ),
        risk_service=case.service,
        bearer_authenticator=JwtAuthenticator(
            issuer=principal.issuer,
            audience=AUDIENCE,
            public_key=signer.public_key,
            clock=lambda: NOW,
            clock_skew_seconds=0,
        ),
        clock=lambda: NOW,
    )
    body = to_primitive(case.command)
    for field in ("account_id", "idempotency_key", "correlation_id"):
        del body[field]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url=ORIGIN, follow_redirects=False, trust_env=False
    ) as client:
        admission = await client.post(
            f"/api/v1/accounts/{case.command.account_id}/risk-runs", json=body, headers=headers()
        )
        guard.check(admission.text)
        assert admission.status_code == 202
        run_id = UUID(admission.json()["id"])
        assert admission.json()["state"] == "queued" and admission.json()["result"] is None
        replay = await client.post(
            f"/api/v1/accounts/{case.command.account_id}/risk-runs",
            json=body,
            headers={**headers(), "X-Correlation-ID": "new-risk-trace"},
        )
        guard.check(replay.text)
        assert replay.json()["id"] == str(run_id)
        worker = store(case)
        claims = await worker.claim_risk_dispatches(dispatcher_id="risk-api-test")
        assert len(claims) == 1 and claims[0].message.run_id == str(run_id)
        assert await worker.acknowledge_risk_dispatch(claims[0])
        outcome = await execute_risk_message(
            worker, claims[0].message, consumer_id="risk-api-test", clock=lambda: NOW
        )
        assert outcome is RiskExecutionState.SUCCEEDED
        detail = await client.get(f"/api/v1/risk-runs/{run_id}", headers=headers())
        guard.check(detail.text)
        assert detail.status_code == 200
        canonical = await case.service.get_run(principal, run_id)
        assert detail.json() == RiskRunResponse.model_validate(to_primitive(canonical)).model_dump(
            mode="json"
        )
        matrix = await client.get(f"/api/v1/risk-runs/{run_id}/matrix", headers=headers())
        guard.check(matrix.text)
        assert matrix.status_code == 200
        assert matrix.json()["matrix"] == detail.json()["result"]["matrix"]
        assert matrix.json()["content_digest"] == detail.json()["result"]["content_digest"]
        assert matrix.json()["definition"] == detail.json()["result"]["definition"]
        unchanged = await client.get(
            f"/api/v1/risk-runs/{run_id}",
            headers={**headers(), "If-None-Match": detail.headers["etag"]},
        )
        assert unchanged.status_code == 304
        listing = await client.get(
            f"/api/v1/accounts/{case.command.account_id}/risk-runs", headers=headers()
        )
        guard.check(listing.text)
        assert (
            listing.status_code == 200
            and listing.json()["items"][0]["result_availability"] == "not_loaded"
        )
        assert listing.json()["items"][0]["result"] is None
        for claims_change, status in (
            ({"aud": AUDIENCE + "/"}, 401),
            ({"iss": principal.issuer + "/"}, 401),
            ({"owner_id": None}, 401),
            ({"owner_id": str(uuid4())}, 404),
            ({"scope": "risk:write"}, 403),
            ({"exp": int(NOW.timestamp()) - 1}, 401),
        ):
            denied = await client.get(
                f"/api/v1/risk-runs/{run_id}", headers=headers(**claims_change)
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
            grant.revoked_at = NOW
        for suffix in ("", "/matrix"):
            denied = await client.get(
                f"/api/v1/risk-runs/{run_id}" + suffix, headers={**headers(), "If-None-Match": "*"}
            )
            guard.check(denied.text)
            assert (
                denied.status_code == 403 and denied.headers["cache-control"] == "private, no-store"
            )
        replay = await client.post(
            f"/api/v1/accounts/{case.command.account_id}/risk-runs", json=body, headers=headers()
        )
        guard.check(replay.text)
        assert replay.status_code == 403
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RiskResultModel)
                .where(RiskResultModel.run_id == run_id)
            )
            == 1
        )
    guard.finish()
