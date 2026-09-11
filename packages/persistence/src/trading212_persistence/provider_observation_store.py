"""Durable content-free provider outcomes around, never during, adapter I/O."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.provider_observations import (
    ProviderInvocation,
    ProviderObservationUnavailable,
)
from trading212_application.source_providers import SourceCapability, SourceProviderError
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

from .models import PrincipalModel
from .provider_observation_models import ProviderInvocationObservationModel
from .report_models import PrincipalScopeGrantModel
from .source_models import MarketDataProviderModel


class PostgresProviderOutcomeObserver:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        principal: Principal,
        provider_id: UUID,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(provider_id, UUID):
            raise ValueError("A canonical configured provider identity is required.")
        self._sessions, self._principal, self._provider_id = sessions, principal, provider_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _execute[T](self, operation: Callable[[], T]) -> T:
        try:
            return await asyncio.to_thread(operation)
        except SQLAlchemyError:
            pass
        raise ProviderObservationUnavailable("Provider observation storage is unavailable.")

    def _authorize(
        self, session: Session, capability: SourceCapability, at: datetime
    ) -> MarketDataProviderModel:
        required = frozenset({Scope.ANALYTICS_READ, Scope.TARGETS_WRITE})
        for scope in required:
            Authorizer().require_scope(self._principal, scope, now=at)
        owner = UUID(self._principal.owner_id)
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{owner}"},
        )
        identity = session.scalar(
            select(PrincipalModel)
            .where(
                PrincipalModel.owner_id == owner,
                PrincipalModel.issuer == self._principal.issuer,
                PrincipalModel.subject == self._principal.subject,
                PrincipalModel.status == "active",
            )
            .with_for_update(read=True)
        )
        if identity is None:
            raise AuthorizationError("access denied")
        grants = set(
            session.scalars(
                select(PrincipalScopeGrantModel.scope)
                .where(
                    PrincipalScopeGrantModel.principal_id == identity.id,
                    PrincipalScopeGrantModel.scope.in_(scope.value for scope in required),
                    PrincipalScopeGrantModel.granted_at <= at,
                    PrincipalScopeGrantModel.revoked_at.is_(None),
                    PrincipalScopeGrantModel.expires_at.is_(None)
                    | (PrincipalScopeGrantModel.expires_at > at),
                )
                .with_for_update(read=True)
            )
        )
        provider = session.scalar(
            select(MarketDataProviderModel)
            .where(
                MarketDataProviderModel.owner_id == owner,
                MarketDataProviderModel.id == self._provider_id,
            )
            .with_for_update(read=True)
        )
        if (
            grants != {scope.value for scope in required}
            or provider is None
            or provider.configuration_state == "disabled"
            or capability.value not in provider.capabilities
        ):
            raise AuthorizationError("access denied")
        return provider

    async def begin(self, capability: SourceCapability) -> ProviderInvocation:
        if not isinstance(capability, SourceCapability):
            raise ValueError("A fixed provider capability is required.")

        def operation() -> ProviderInvocation:
            with self._sessions() as session, session.begin():
                now = require_utc(self._clock())
                provider = self._authorize(session, capability, now)
                return ProviderInvocation(
                    id=uuid4(),
                    owner_id=provider.owner_id,
                    provider_id=provider.id,
                    provider_key=provider.key,
                    adapter_version=provider.adapter_version,
                    capability=capability,
                    started_at=now,
                )

        return await self._execute(operation)

    async def complete(
        self, invocation: ProviderInvocation, *, failure: SourceProviderError | None
    ) -> None:
        if not isinstance(invocation, ProviderInvocation) or (
            failure is not None and not isinstance(failure, SourceProviderError)
        ):
            raise ValueError("An actual typed provider observation is required.")
        completed = require_utc(self._clock())
        if invocation.started_at > completed:
            raise ValueError("Provider completion cannot predate invocation.")

        def operation() -> None:
            with self._sessions() as session, session.begin():
                known = require_utc(self._clock())
                provider = self._authorize(session, invocation.capability, known)
                if (
                    provider.owner_id != invocation.owner_id
                    or provider.id != invocation.provider_id
                    or provider.key != invocation.provider_key
                    or provider.adapter_version != invocation.adapter_version
                    or known < completed
                ):
                    raise AuthorizationError("access denied")
                existing = session.get(ProviderInvocationObservationModel, invocation.id)
                code = failure.value if failure is not None else None
                if existing is not None:
                    if (
                        existing.owner_id != invocation.owner_id
                        or existing.provider_id != invocation.provider_id
                        or existing.capability != invocation.capability.value
                        or existing.started_at != invocation.started_at
                        or existing.adapter_version != invocation.adapter_version
                        or existing.failure_code != code
                    ):
                        raise ValueError("Provider observation identity conflicts.")
                    return
                outcome = "succeeded" if failure is None else "failed"
                if failure in {
                    SourceProviderError.NOT_CONFIGURED,
                    SourceProviderError.UNSUPPORTED,
                    SourceProviderError.LICENSE_DENIED,
                }:
                    outcome = "unavailable"
                session.add(
                    ProviderInvocationObservationModel(
                        id=invocation.id,
                        owner_id=invocation.owner_id,
                        provider_id=invocation.provider_id,
                        capability=invocation.capability.value,
                        adapter_version=invocation.adapter_version,
                        started_at=invocation.started_at,
                        completed_at=completed,
                        first_known_at=known,
                        outcome=outcome,
                        failure_code=code,
                    )
                )

        await self._execute(operation)
