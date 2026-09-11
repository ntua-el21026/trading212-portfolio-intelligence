"""Actual provider attempts persist content-free outcomes under current durable grants."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import source_providers as p
from trading212_application.provider_observations import (
    ObservedMarketPriceHistoryProvider,
    ProviderInvocation,
)
from trading212_domain import build_synthetic_identity
from trading212_persistence.provider_observation_models import ProviderInvocationObservationModel
from trading212_persistence.provider_observation_store import PostgresProviderOutcomeObserver
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_reference_data.replay import ReplayMarketPriceHistoryProvider
from trading212_reference_data.synthetic import PROVIDER_ID, PROVIDER_KEY
from trading212_security.principals import AuthorizationError, Principal, Scope
from trading212_worker.synthetic_grants import seed_synthetic_grants

from tests.integration.test_alert_postgres import alert_database as alert_database
from tests.unit.test_reference_replay import context, price_request

pytestmark = pytest.mark.integration


def _principal(at: datetime) -> Principal:
    identity = build_synthetic_identity()
    return Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=frozenset({Scope.ANALYTICS_READ, Scope.TARGETS_WRITE}),
        authenticated_at=at - timedelta(seconds=1),
        expires_at=at + timedelta(hours=1),
    )


async def test_actual_replay_attempts_have_independent_safe_immutable_observations(
    alert_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = alert_database
    at = datetime.now(UTC)
    observer = PostgresProviderOutcomeObserver(
        sessions=sessions,
        principal=_principal(at),
        provider_id=UUID(PROVIDER_ID),
        clock=lambda: at,
    )
    ctx = context()
    provider = ObservedMarketPriceHistoryProvider(ReplayMarketPriceHistoryProvider(ctx), observer)
    for _ in range(2):
        assert isinstance(await provider.get_price_history(price_request(ctx)), p.PriceHistoryPage)
    with sessions() as session:
        rows = tuple(
            session.scalars(
                select(ProviderInvocationObservationModel)
                .where(
                    ProviderInvocationObservationModel.started_at == at,
                )
                .order_by(ProviderInvocationObservationModel.observed_sequence)
            )
        )
        assert len(rows) == 2 and rows[0].id != rows[1].id
        assert all(row.outcome == "succeeded" and row.failure_code is None for row in rows)
        row = rows[0]
        invocation = ProviderInvocation(
            id=row.id,
            owner_id=row.owner_id,
            provider_id=row.provider_id,
            provider_key=PROVIDER_KEY,
            adapter_version=row.adapter_version,
            capability=p.SourceCapability(row.capability),
            started_at=row.started_at,
        )
        assert not {"response", "payload", "credential", "account_id"} & set(
            row.__table__.columns.keys()
        )
    await observer.complete(invocation, failure=None)
    with pytest.raises(ValueError, match="identity conflicts"):
        await observer.complete(invocation, failure=p.SourceProviderError.TIMEOUT)
    with pytest.raises(AuthorizationError):
        await observer.complete(replace(invocation, owner_id=UUID(int=991)), failure=None)
    with sessions() as session:
        assert (
            len(
                tuple(
                    session.scalars(
                        select(ProviderInvocationObservationModel.id).where(
                            ProviderInvocationObservationModel.started_at == at,
                        )
                    )
                )
            )
            == 2
        )


async def test_revoked_grant_denies_before_provider_call_and_reseed_does_not_restore_it(
    alert_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = alert_database
    at = datetime.now(UTC)
    principal = _principal(at)
    called = False

    class Provider(ReplayMarketPriceHistoryProvider):
        async def get_price_history(
            self, request: p.PriceHistoryRequest
        ) -> p.PriceHistoryPage | p.SourceFailure:
            nonlocal called
            called = True
            return await super().get_price_history(request)

    with sessions.begin() as session:
        grant = session.get(
            PrincipalScopeGrantModel, (UUID(principal.principal_id), Scope.TARGETS_WRITE.value)
        )
        assert grant is not None
        grant.revoked_at = at
    try:
        seed_synthetic_grants(
            sessions,
            app_environment="test",
            at=at,
            scopes=principal.scopes,
        )
        observer = PostgresProviderOutcomeObserver(
            sessions=sessions,
            principal=principal,
            provider_id=UUID(PROVIDER_ID),
            clock=lambda: at,
        )
        ctx = context()
        with pytest.raises(AuthorizationError):
            await ObservedMarketPriceHistoryProvider(Provider(ctx), observer).get_price_history(
                price_request(ctx)
            )
        assert not called
        with sessions() as session:
            assert (
                session.scalar(
                    select(ProviderInvocationObservationModel.id).where(
                        ProviderInvocationObservationModel.started_at == at,
                    )
                )
                is None
            )
    finally:
        # This fixture owns the whole disposable database; restore its shared grant.
        with sessions.begin() as session:
            grant = session.get(
                PrincipalScopeGrantModel, (UUID(principal.principal_id), Scope.TARGETS_WRITE.value)
            )
            assert grant is not None
            grant.revoked_at = None
