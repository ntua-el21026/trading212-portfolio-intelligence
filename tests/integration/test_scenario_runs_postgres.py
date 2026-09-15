"""Real saved X-ray scenario admission, current authority and stable metadata pages."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.scenario_replay import resolve_scenario_replay
from trading212_application import scenario as app
from trading212_application.risk import PremiumJobState
from trading212_application.scenario_views import ScenarioRunView
from trading212_domain import CurrencyCode
from trading212_domain.scenario import (
    ScenarioEntitySelector,
    ScenarioPriceShock,
    ScenarioVersionContent,
)
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    PrincipalScopeGrantModel,
)
from trading212_persistence.scenario_models import ScenarioRunPayloadModel
from trading212_persistence.scenario_service import PostgresScenarioService
from trading212_security.principals import Principal, Scope
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@dataclass
class ScenarioCase:
    sessions: sessionmaker[Session]
    service: PostgresScenarioService
    principal: Principal
    command: app.CreateScenarioRun
    run: ScenarioRunView
    xray: XrayReadCase

    @property
    def now(self) -> datetime:
        return self.xray.now[0]

    @now.setter
    def now(self, value: datetime) -> None:
        self.xray.now[0] = value

    @property
    def engine(self) -> Engine:
        return self.xray.engine


def grant_scenario_identity(
    sessions: sessionmaker[Session], principal: Principal, at: datetime
) -> None:
    """Give a synthetic stable identity explicit durable grants, as local provisioning does."""
    with sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == principal.issuer,
                PrincipalModel.subject == principal.subject,
            )
        )
        if identity is None:
            identity = PrincipalModel(
                id=uuid4(),
                owner_id=UUID(principal.owner_id),
                issuer=principal.issuer,
                subject=principal.subject,
                status="active",
            )
            session.add(identity)
            session.flush()
        assert identity.owner_id == UUID(principal.owner_id)
        identity.status = "active"
        for scope in principal.scopes:
            grant = session.get(PrincipalScopeGrantModel, (identity.id, scope.value))
            if grant is None:
                session.add(
                    PrincipalScopeGrantModel(
                        principal_id=identity.id,
                        scope=scope.value,
                        granted_at=at - timedelta(days=1),
                        expires_at=None,
                        revoked_at=None,
                    )
                )
            else:
                grant.revoked_at = None
                grant.expires_at = None


@pytest.fixture
async def scenario_case(xray_read_case: XrayReadCase) -> ScenarioCase:
    """One queued run through real immutable parents and admission; shared disposable DB only."""
    case = xray_read_case
    grant_scenario_identity(case.sessions, case.principal, case.now[0])
    saved = await company(case)
    service = PostgresScenarioService(
        case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.now[0],
        replay_resolver=resolve_scenario_replay,
    )
    definition = await service.create_definition(
        case.principal,
        app.CreateScenario(
            account_id=UUID(XRAY_ACCOUNT_ID),
            content=ScenarioVersionContent(
                name="Synthetic stress",
                description="Saved canonical X-ray inputs",
                mode="compounded",
                shocks=(
                    ScenarioPriceShock(
                        selector=ScenarioEntitySelector(entity_id=UUID(xray_id("entity/alpha"))),
                        size=Decimal("-0.1"),
                    ),
                ),
            ),
            idempotency_key=str(uuid4()),
            correlation_id="scenario-fixture",
        ),
    )
    command = app.CreateScenarioRun(
        account_id=UUID(XRAY_ACCOUNT_ID),
        scenario_version_id=definition.current_version_id,
        portfolio_snapshot_id=UUID(case.seed["snapshot_id"]),
        xray_run_id=UUID(saved.context.run_id),
        reporting_currency=CurrencyCode("EUR"),
        source_cutoff_at=datetime.fromisoformat(case.seed["source_cutoff_at"]),
        idempotency_key=str(uuid4()),
        correlation_id="scenario-fixture",
    )
    queued = await service.create_run(case.principal, command)
    return ScenarioCase(case.sessions, service, case.principal, command, queued, case)


async def cancel_scenario(case: ScenarioCase, identifier: UUID) -> ScenarioRunView:
    return await case.service.cancel_run(
        case.principal,
        app.CancelScenarioRun(
            run_id=identifier,
            idempotency_key=str(uuid4()),
            correlation_id="scenario-test-cancel",
        ),
    )


async def test_atomic_admission_and_exact_semantic_retry(scenario_case: ScenarioCase) -> None:
    case = scenario_case
    with (
        patch.object(
            case.service, "persist_capture", side_effect=AssertionError("new capture on retry")
        ),
        patch.object(
            case.service,
            "reserve_run_capacity",
            side_effect=AssertionError("new reservation on retry"),
        ),
    ):
        again = await case.service.create_run(
            case.principal, replace(case.command, correlation_id="refreshed-trace")
        )
        with pytest.raises(app.ScenarioServiceError) as conflict:
            await case.service.create_run(
                case.principal, replace(case.command, xray_run_id=uuid4())
            )
    assert conflict.value.code is app.ScenarioErrorCode.CONFLICT
    assert again == case.run and again.state is PremiumJobState.QUEUED
    assert again.result is None and again.result_availability == "pending"
    with case.sessions() as session:
        root = session.get(PremiumRunModel, again.id)
        assert root is not None and root.reserved_bytes == 33554432 and root.retained_bytes == 0
        identity = session.get(ApplicationCommandIdentityModel, root.command_id)
        assert identity is not None and identity.premium_resource_id == root.id
        assert session.scalar(select(func.count()).select_from(PremiumJobModel)) == 1
        outbox = session.scalar(
            select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == again.job_id)
        )
        assert outbox is not None and outbox.task_name == "scenarios.calculate.v1"
        assert outbox.state == "pending"
        input_bytes = session.scalar(
            select(func.octet_length(ScenarioRunPayloadModel.canonical_input)).where(
                ScenarioRunPayloadModel.run_id == again.id
            )
        )
        assert input_bytes is not None and input_bytes > 0


async def test_cancel_releases_job_and_accounts_retained_input_exactly(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    second = await case.service.create_run(
        case.principal, replace(case.command, idempotency_key=str(uuid4()))
    )
    with pytest.raises(app.ScenarioServiceError) as limited:
        await case.service.create_run(
            case.principal, replace(case.command, idempotency_key=str(uuid4()))
        )
    assert limited.value.code is app.ScenarioErrorCode.RATE_LIMITED
    command = app.CancelScenarioRun(
        run_id=case.run.id, idempotency_key=str(uuid4()), correlation_id="cancel-once"
    )
    first = await case.service.cancel_run(case.principal, command)
    again = await case.service.cancel_run(case.principal, replace(command, correlation_id="again"))
    assert first == again and first.state is PremiumJobState.CANCELLED and first.result is None
    with case.sessions() as session:
        root = session.get(PremiumRunModel, case.run.id)
        capacity = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert root is not None and root.reserved_bytes == 0 and root.retained_bytes > 0
        actual = session.scalar(select(func.scenario_storage_bytes(root.id)))
        assert actual == root.retained_bytes
        assert capacity is not None and capacity.active_jobs == 1
        assert capacity.reserved_bytes == 33554432 and capacity.retained_bytes == actual
    third = await case.service.create_run(
        case.principal, replace(case.command, idempotency_key=str(uuid4()))
    )
    await cancel_scenario(case, second.id)
    await cancel_scenario(case, third.id)


async def test_failed_capture_rolls_back_command_job_and_capacity(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    with case.sessions() as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                ApplicationCommandIdentityModel,
                PremiumRunModel,
                PremiumJobModel,
                PremiumOutboxModel,
            )
        )
    with pytest.raises(app.ScenarioServiceError):
        await case.service.create_run(
            case.principal,
            replace(case.command, portfolio_snapshot_id=uuid4(), idempotency_key=str(uuid4())),
        )
    with case.sessions() as session:
        after = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                ApplicationCommandIdentityModel,
                PremiumRunModel,
                PremiumJobModel,
                PremiumOutboxModel,
            )
        )
        capacity = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert (
            capacity is not None
            and capacity.active_jobs == 1
            and capacity.reserved_bytes == 33554432
        )
    assert before == after


async def test_definition_versions_use_revision_and_exact_retry(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    original = await case.service.get_version(case.principal, case.command.scenario_version_id)
    command = app.CreateScenarioVersion(
        scenario_id=original.definition_id,
        expected_revision=1,
        content=replace(original.content, name="Second version"),
        idempotency_key=str(uuid4()),
        correlation_id="scenario-version-test",
    )
    second = await case.service.create_version(case.principal, command)
    await case.service.create_version(
        case.principal,
        replace(
            command,
            expected_revision=2,
            content=replace(original.content, name="Third version"),
            idempotency_key=str(uuid4()),
        ),
    )
    assert await case.service.create_version(case.principal, command) == second
    with pytest.raises(app.ScenarioServiceError) as stale:
        await case.service.create_version(
            case.principal, replace(command, idempotency_key=str(uuid4()))
        )
    assert stale.value.code is app.ScenarioErrorCode.REVISION_MISMATCH
    with pytest.raises(app.ScenarioServiceError) as changed:
        await case.service.create_version(
            case.principal, replace(command, content=replace(original.content, name="Changed"))
        )
    assert changed.value.code is app.ScenarioErrorCode.CONFLICT


async def test_mutable_pages_freeze_members_and_bind_stable_principal(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    version = await case.service.get_version(case.principal, case.command.scenario_version_id)

    async def create(name: str) -> UUID:
        value = await case.service.create_definition(
            case.principal,
            app.CreateScenario(
                account_id=case.command.account_id,
                content=replace(version.content, name=name),
                idempotency_key=str(uuid4()),
                correlation_id="scenario-list-test",
            ),
        )
        return value.id

    second_id = await create("Second definition")
    page = await case.service.list_definitions(
        case.principal, case.command.account_id, app.ScenarioPageQuery(limit=1)
    )
    assert page.total == 2 and page.next_cursor is not None
    newer = await create("Added after traversal started")
    query = app.ScenarioPageQuery(limit=1, cursor=page.next_cursor)
    refreshed = replace(case.principal, principal_id=str(uuid4()), session_id="fresh-session")
    resumed = await case.service.list_definitions(refreshed, case.command.account_id, query)
    assert resumed.total == 2 and resumed.next_cursor is None
    assert {page.items[0].id, resumed.items[0].id} == {version.definition_id, second_id}
    assert newer not in {page.items[0].id, resumed.items[0].id}
    another = replace(case.principal, principal_id=str(uuid4()), subject="another-synthetic-reader")
    grant_scenario_identity(case.sessions, another, case.now)
    with pytest.raises(app.ScenarioServiceError) as rejected:
        await case.service.list_definitions(another, case.command.account_id, query)
    assert rejected.value.code is app.ScenarioErrorCode.CURSOR_INVALID


async def test_current_grant_denial_precedes_cursor_and_private_decode(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    with case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == case.principal.issuer,
                PrincipalModel.subject == case.principal.subject,
            )
        )
        assert identity is not None
        grant = session.get(PrincipalScopeGrantModel, (identity.id, Scope.ANALYTICS_READ.value))
        assert grant is not None
        grant.revoked_at = case.now
    with (
        patch.object(
            case.service._cursors, "decode", side_effect=AssertionError("cursor before grant")
        ),
        patch.object(
            case.service,
            "read_retained_input",
            side_effect=AssertionError("private decode before grant"),
        ),
        pytest.raises(app.ScenarioServiceError) as denied,
    ):
        await case.service.list_runs(
            case.principal, case.command.account_id, app.ScenarioPageQuery(cursor="invalid")
        )
    assert denied.value.code is app.ScenarioErrorCode.ACCESS_DENIED


async def test_expired_idempotent_run_keeps_original_expiry_and_has_no_body(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    case.now = case.run.expires_at + timedelta(seconds=1)
    with (
        patch.object(case.service, "capture", side_effect=AssertionError("expired recapture")),
        patch.object(
            case.service, "read_retained_input", side_effect=AssertionError("expired decode")
        ),
    ):
        again = await case.service.create_run(case.principal, case.command)
        status = await case.service.get_run(
            case.principal, case.run.id, app.ScenarioComponentPageQuery()
        )
    assert again.id == status.id == case.run.id
    assert again.expires_at == status.expires_at == case.run.expires_at
    assert again.result is status.result is None
    assert again.result_availability == status.result_availability == "expired"


async def test_requested_account_mismatch_precedes_private_read_and_malformed_cursor(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    with (
        patch.object(case.service, "_run_rows", side_effect=AssertionError("private rows")) as rows,
        patch.object(
            case.service._cursors, "decode", side_effect=AssertionError("cursor before account")
        ) as decode,
        pytest.raises(app.ScenarioServiceError) as rejected,
    ):
        await case.service.get_run(
            case.principal,
            case.run.id,
            app.ScenarioComponentPageQuery(component_cursor="malformed"),
            expected_account_id=uuid4(),
        )
    assert rejected.value.code is app.ScenarioErrorCode.NOT_FOUND
    rows.assert_not_called()
    decode.assert_not_called()
