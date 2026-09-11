"""Complete local seeding grants alerts once and preserves trusted expiry/revocation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import alerts as app
from trading212_domain import alerts as d
from trading212_domain import build_synthetic_identity
from trading212_domain.values import CurrencyCode
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.models import AuditEventModel
from trading212_persistence.provider_observation_models import ProviderInvocationObservationModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LocalSyntheticAuthenticator
from trading212_worker.seed import SEED_TIME, seed_complete_synthetic

from tests.integration.test_alert_postgres import KEY
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def _grants(
    sessions: sessionmaker[Session], principal_id: UUID
) -> dict[str, tuple[datetime, datetime | None, datetime | None]]:
    with sessions() as session:
        return {
            row.scope: (row.granted_at, row.expires_at, row.revoked_at)
            for row in session.scalars(
                select(PrincipalScopeGrantModel).where(
                    PrincipalScopeGrantModel.principal_id == principal_id
                )
            )
        }


def _observations(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return (
            session.scalar(select(func.count()).select_from(ProviderInvocationObservationModel))
            or 0
        )


def _seed_audits(sessions: sessionmaker[Session], principal_id: UUID) -> int:
    with sessions() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.principal_id == principal_id,
                    AuditEventModel.action == "principal.scopes.seeded",
                )
            )
            or 0
        )


async def test_complete_seed_enables_actual_local_alerts_and_never_restores_revoked_grants(
    alert_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, sessions = alert_database
    identity = build_synthetic_identity()
    alert_scopes = {Scope.ALERTS_READ.value, Scope.ALERTS_WRITE.value}
    # This fixture seeds only materialized broker/source facts. It does not use
    # alert_case, seed_alert_browser_scenario, or manually provision alert access.
    assert not alert_scopes & _grants(sessions, identity.principal.id).keys()
    before_calls = _observations(sessions)
    url = engine.url.render_as_string(hide_password=False)
    await seed_complete_synthetic(url, app_environment="test")
    initial = _grants(sessions, identity.principal.id)
    assert {key: initial[key] for key in alert_scopes} == {
        key: (SEED_TIME, None, None) for key in alert_scopes
    }
    assert _observations(sessions) == before_calls + 16
    seed_audits = _seed_audits(sessions, identity.principal.id)

    now = [datetime.now(UTC)]
    authenticator = LocalSyntheticAuthenticator(
        SecuritySettings(environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True),
        clock=lambda: now[0],
    )
    principal = await authenticator.authenticate("")
    assert {Scope.ALERTS_READ, Scope.ALERTS_WRITE} <= principal.scopes
    service = PostgresAlertService(sessions, cursor_signing_key=KEY, clock=lambda: now[0])
    command = app.CreateAlertRuleCommand(
        account_id=identity.account.id,
        definition=d.AlertRuleDefinition(
            name="Complete seed local cash alert",
            predicate=d.AlertPredicate(
                family=d.AlertFamily.CASH_THRESHOLD,
                metric=d.AlertMetric.CASH_AMOUNT,
                comparison=d.AlertComparison.GT,
                threshold=Decimal("0"),
                currency=CurrencyCode("EUR"),
            ),
            schedule=d.AlertIntervalSchedule(anchor_at=now[0]),
        ),
    )
    created = await service.create_rule(
        principal, command, idempotency_key=uuid4().hex, correlation_id="complete-seed"
    )
    assert (
        await service.get_rule(principal, created.id, query=app.AlertRuleDetailQuery())
    ).id == created.id

    # A trusted administrator shortens existing grants only after the default
    # seed/principal has proved real creation and reading without manual grants.
    expiry = now[0] + timedelta(days=1)
    with sessions.begin() as session:
        session.execute(
            update(PrincipalScopeGrantModel)
            .where(
                PrincipalScopeGrantModel.principal_id == identity.principal.id,
                PrincipalScopeGrantModel.scope.in_(alert_scopes),
            )
            .values(expires_at=expiry)
        )
    bounded_grants = _grants(sessions, identity.principal.id)
    assert all(bounded_grants[key] == (SEED_TIME, expiry, None) for key in alert_scopes)
    await seed_complete_synthetic(url, app_environment="test")
    assert _grants(sessions, identity.principal.id) == bounded_grants
    assert _seed_audits(sessions, identity.principal.id) == seed_audits
    assert _observations(sessions) == before_calls + 32
    assert (
        await service.get_rule(principal, created.id, query=app.AlertRuleDetailQuery())
    ).id == created.id

    now[0] += timedelta(seconds=1)
    with sessions.begin() as session:
        session.execute(
            update(PrincipalScopeGrantModel)
            .where(
                PrincipalScopeGrantModel.principal_id == identity.principal.id,
                PrincipalScopeGrantModel.scope.in_(alert_scopes),
            )
            .values(revoked_at=now[0])
        )
    revoked = _grants(sessions, identity.principal.id)
    assert all(revoked[key] == (bounded_grants[key][0], expiry, now[0]) for key in alert_scopes)
    await seed_complete_synthetic(url, app_environment="test")
    assert _grants(sessions, identity.principal.id) == revoked
    assert _seed_audits(sessions, identity.principal.id) == seed_audits
    assert _observations(sessions) == before_calls + 48

    # Authentication still advertises the scopes; current durable revocation
    # independently rejects both read and create after the full reseed.
    principal = await authenticator.authenticate("")
    assert {Scope.ALERTS_READ, Scope.ALERTS_WRITE} <= principal.scopes
    with pytest.raises(app.AlertServiceError) as denied_read:
        await service.get_rule(principal, created.id, query=app.AlertRuleDetailQuery())
    assert denied_read.value.code is app.AlertServiceErrorCode.ACCESS_DENIED
    with pytest.raises(app.AlertServiceError) as denied_write:
        await service.create_rule(
            principal, command, idempotency_key=uuid4().hex, correlation_id="revoked-reseed"
        )
    assert denied_write.value.code is app.AlertServiceErrorCode.ACCESS_DENIED
