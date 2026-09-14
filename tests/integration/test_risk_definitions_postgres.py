"""Real current-grant, immutable-version and cursor semantics on the risk service."""

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import risk as app
from trading212_domain.risk import RiskDefinitionContent
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_models import PremiumAuditModel, PremiumCapacityModel
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    PrincipalScopeGrantModel,
)
from trading212_persistence.risk_definitions import RISK_WRITE_SCOPES, RiskDefinitionStore
from trading212_persistence.risk_models import RiskVersionModel
from trading212_security.principals import Principal, Scope

from tests.integration.test_migrations import database_engine as database_engine
from tests.integration.test_phase3_risk_schema import NOW
from tests.integration.test_phase3_risk_schema import scope as scope

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


@dataclass
class Case:
    sessions: sessionmaker[Session]
    service: RiskDefinitionStore
    principal: Principal
    account: UUID
    calendar: UUID

    def command(
        self, key: str = "risk-definition-one", name: str = "Risk"
    ) -> app.CreateRiskDefinition:
        return app.CreateRiskDefinition(
            account_id=self.account,
            idempotency_key=key,
            correlation_id="risk-test",
            content=RiskDefinitionContent(
                name=name,
                description="Synthetic case",
                calendar_id="risk-calendar",
                calendar_version="1",
                annual_risk_free=Decimal(".012345678901234567"),
            ),
        )


@pytest.fixture
def case(scope: tuple[Session, UUID, UUID, UUID, UUID], database_engine: Engine) -> Case:
    session, owner, account, principal_id, calendar = scope
    identity = session.get(PrincipalModel, principal_id)
    assert identity is not None
    identity.subject = f"opaque-risk-user:{owner}"
    capacity = session.get(PremiumCapacityModel, owner)
    assert capacity is not None
    capacity.definition_versions = 0
    for permission in RISK_WRITE_SCOPES:
        session.add(
            PrincipalScopeGrantModel(
                principal_id=principal_id,
                scope=permission.value,
                granted_at=NOW - timedelta(days=1),
                expires_at=None,
                revoked_at=None,
            )
        )
    principal = Principal(
        principal_id="opaque-transport-principal",
        owner_id=str(owner),
        issuer=identity.issuer,
        subject=identity.subject,
        scopes=RISK_WRITE_SCOPES,
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    session.commit()
    sessions = sessionmaker(database_engine, expire_on_commit=False)
    return Case(
        sessions,
        RiskDefinitionStore(
            sessions, cursor_signing_key=b"synthetic-cursor-key-256bits-only!", clock=lambda: NOW
        ),
        principal,
        account,
        calendar,
    )


async def test_definition_exact_round_trip_and_semantic_replay(case: Case) -> None:
    command = case.command()
    first = await case.service.create_definition(case.principal, command)
    again = await case.service.create_definition(
        case.principal, replace(command, correlation_id="another-trace")
    )
    assert first == again
    version = await case.service.get_version(case.principal, first.current_version_id)
    assert version.content == command.content
    assert version.content.annual_risk_free == Decimal(".012345678901234567")
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApplicationCommandIdentityModel)
                .where(ApplicationCommandIdentityModel.owner_id == UUID(case.principal.owner_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PremiumAuditModel)
                .where(PremiumAuditModel.owner_id == UUID(case.principal.owner_id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(PremiumCapacityModel.definition_versions).where(
                    PremiumCapacityModel.owner_id == UUID(case.principal.owner_id)
                )
            )
            == 1
        )


async def test_concurrent_same_command_has_one_version_and_identity(case: Case) -> None:
    rows = await asyncio.gather(
        *(case.service.create_definition(case.principal, case.command()) for _ in range(3))
    )
    assert len({row.id for row in rows}) == 1
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RiskVersionModel)
                .where(RiskVersionModel.owner_id == UUID(case.principal.owner_id))
            )
            == 1
        )


async def test_changed_semantics_conflicts_without_additional_version(case: Case) -> None:
    await case.service.create_definition(case.principal, case.command())
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_definition(case.principal, case.command(name="Changed"))
    assert failure.value.code is app.RiskErrorCode.CONFLICT


async def test_new_versions_preserve_predecessor_and_replay_before_revision_check(
    case: Case,
) -> None:
    first = await case.service.create_definition(case.principal, case.command())
    content = replace(case.command().content, name="Updated", confidence=Decimal(".99"))
    command = app.CreateRiskVersion(
        definition_id=first.id,
        expected_revision=1,
        content=content,
        idempotency_key="risk-version-two",
        correlation_id="version-test",
    )
    second = await case.service.create_version(case.principal, command)
    assert second.predecessor_id == first.current_version_id and second.version_number == 2
    assert await case.service.create_version(case.principal, command) == second
    assert (
        await case.service.get_definition(case.principal, first.id)
    ).current_version_id == second.id
    assert (
        await case.service.get_version(case.principal, first.current_version_id)
    ).content.name == "Risk"
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_version(
            case.principal, replace(command, idempotency_key="stale-version")
        )
    assert failure.value.code is app.RiskErrorCode.REVISION_MISMATCH


@pytest.mark.parametrize("operation", ["read", "replay", "page"])
async def test_current_grant_revocation_blocks_all_paths(case: Case, operation: str) -> None:
    first = await case.service.create_definition(case.principal, case.command())
    with case.sessions() as session, session.begin():
        grant = session.get(
            PrincipalScopeGrantModel, (UUID(await _identity_id(case)), Scope.ANALYTICS_READ.value)
        )
        assert grant is not None
        grant.revoked_at = NOW
    with pytest.raises(app.RiskServiceError) as failure:
        if operation == "read":
            await case.service.get_definition(case.principal, first.id)
        elif operation == "replay":
            await case.service.create_definition(case.principal, case.command())
        else:
            await case.service.list_definitions(case.principal, case.account, app.RiskPageQuery())
    assert failure.value.code is app.RiskErrorCode.ACCESS_DENIED


async def _identity_id(case: Case) -> str:
    with case.sessions() as session:
        identifier = session.scalar(
            select(PrincipalModel.id).where(
                PrincipalModel.owner_id == UUID(case.principal.owner_id)
            )
        )
        assert identifier is not None
        return str(identifier)


async def test_write_scope_does_not_imply_read_and_wrong_issuer_is_denied(case: Case) -> None:
    for principal in (
        replace(case.principal, scopes=frozenset((Scope.RISK_WRITE,))),
        replace(case.principal, issuer="https://different.invalid"),
    ):
        with pytest.raises(app.RiskServiceError) as failure:
            await case.service.create_definition(principal, case.command())
        assert failure.value.code is app.RiskErrorCode.ACCESS_DENIED


async def test_cursor_membership_survives_insert_and_binds_account(case: Case) -> None:
    originals = {
        (
            await case.service.create_definition(
                case.principal, case.command(key=f"definition-{i}")
            )
        ).id
        for i in range(3)
    }
    first = await case.service.list_definitions(
        case.principal, case.account, app.RiskPageQuery(limit=1)
    )
    await case.service.create_definition(case.principal, case.command(key="later-definition"))
    seen = {first.items[0].id}
    cursor = first.next_cursor
    while cursor:
        page = await case.service.list_definitions(
            case.principal, case.account, app.RiskPageQuery(limit=1, cursor=cursor)
        )
        assert page.total == 3
        seen.update(item.id for item in page.items)
        cursor = page.next_cursor
    assert seen == originals
    assert first.next_cursor is not None
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.list_definitions(
            case.principal, uuid4(), app.RiskPageQuery(cursor=first.next_cursor)
        )
    assert failure.value.code is app.RiskErrorCode.ACCESS_DENIED


async def test_versions_cursor_cannot_cross_definition(case: Case) -> None:
    first = await case.service.create_definition(case.principal, case.command())
    await case.service.create_version(
        case.principal,
        app.CreateRiskVersion(
            definition_id=first.id,
            expected_revision=1,
            content=case.command().content,
            idempotency_key="v2",
            correlation_id="versions",
        ),
    )
    other = await case.service.create_definition(case.principal, case.command(key="other"))
    page = await case.service.list_versions(case.principal, first.id, app.RiskPageQuery(limit=1))
    assert page.items[0].version_number == 2 and page.next_cursor is not None
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.list_versions(
            case.principal, other.id, app.RiskPageQuery(cursor=page.next_cursor)
        )
    assert failure.value.code is app.RiskErrorCode.CURSOR_INVALID


async def test_definition_capacity_and_foreign_calendar_are_checked(case: Case) -> None:
    with case.sessions() as session, session.begin():
        row = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert row is not None
        row.definition_versions = 512
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_definition(case.principal, case.command())
    assert failure.value.code is app.RiskErrorCode.RATE_LIMITED
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_definition(
            case.principal,
            replace(
                case.command(), content=replace(case.command().content, calendar_id=str(uuid4()))
            ),
        )
    assert failure.value.code is app.RiskErrorCode.SOURCE_UNAVAILABLE


async def test_version_quota_preserves_aggregate_revision(case: Case) -> None:
    first = await case.service.create_definition(case.principal, case.command())
    with case.sessions() as session, session.begin():
        row = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert row is not None
        row.definition_versions = 512
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_version(
            case.principal,
            app.CreateRiskVersion(
                definition_id=first.id,
                expected_revision=1,
                content=case.command().content,
                idempotency_key="over-quota-version",
                correlation_id="quota",
            ),
        )
    assert failure.value.code is app.RiskErrorCode.RATE_LIMITED
    assert await case.service.get_definition(case.principal, first.id) == first
