"""Current durable report authority, independent of an initiating token lifetime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

from .models import BrokerAccountModel, BrokerConnectionModel, PrincipalModel
from .report_models import PrincipalScopeGrantModel


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportAuthorization:
    principal_id: UUID
    owner_id: UUID
    account_id: UUID
    required_scopes: frozenset[Scope]
    expires_at: datetime
    issuer: str
    subject: str
    requesting_principal: Principal | None = None

    def check(self, session: Session, *, now: datetime) -> None:
        """Reload permissions before any licensed decode and final publication."""
        at = require_utc(now)
        if at >= self.expires_at:
            raise AuthorizationError("access denied")
        if self.requesting_principal is not None:
            for scope in self.required_scopes:
                Authorizer().require_scope(self.requesting_principal, scope, now=at)
        principal = session.scalar(
            select(PrincipalModel)
            .where(
                PrincipalModel.id == self.principal_id,
                PrincipalModel.owner_id == self.owner_id,
                PrincipalModel.issuer == self.issuer,
                PrincipalModel.subject == self.subject,
                PrincipalModel.status == "active",
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if principal is None:
            raise AuthorizationError("access denied")
        account = session.execute(
            select(BrokerAccountModel.id)
            .join(
                BrokerConnectionModel, BrokerAccountModel.connection_id == BrokerConnectionModel.id
            )
            .where(
                BrokerAccountModel.id == self.account_id,
                BrokerAccountModel.status == "active",
                BrokerConnectionModel.owner_id == self.owner_id,
                BrokerConnectionModel.status == "active",
            )
            .with_for_update(read=True, of=(BrokerAccountModel, BrokerConnectionModel))
        ).scalar_one_or_none()
        if account is None:
            raise AuthorizationError("access denied")
        granted = frozenset(
            session.scalars(
                select(PrincipalScopeGrantModel.scope)
                .where(
                    PrincipalScopeGrantModel.principal_id == self.principal_id,
                    PrincipalScopeGrantModel.scope.in_(
                        scope.value for scope in self.required_scopes
                    ),
                    PrincipalScopeGrantModel.granted_at <= at,
                    PrincipalScopeGrantModel.revoked_at.is_(None),
                    (
                        PrincipalScopeGrantModel.expires_at.is_(None)
                        | (PrincipalScopeGrantModel.expires_at > at)
                    ),
                )
                .with_for_update(read=True)
            )
        )
        if granted != frozenset(scope.value for scope in self.required_scopes):
            raise AuthorizationError("access denied")

    def as_principal(self, *, now: datetime) -> Principal:
        """Supply the exact authorized subset to existing canonical family adapters.

        This is an in-process fixed-purpose delegation, never a minted bearer token.
        Call check in the same transaction before using the returned identity.
        """
        return Principal(
            principal_id=str(self.principal_id),
            owner_id=str(self.owner_id),
            issuer=self.issuer,
            subject=self.subject,
            scopes=self.required_scopes,
            authenticated_at=require_utc(now),
            expires_at=self.expires_at,
        )


def authorize_report_request(
    session: Session,
    principal: Principal,
    *,
    account_id: UUID,
    required_scopes: frozenset[Scope],
    now: datetime,
) -> ReportAuthorization:
    """Resolve issuer/sub to the canonical principal; an opaque sub need not be a UUID."""
    _require_scopes(required_scopes)
    at = require_utc(now)
    for scope in required_scopes:
        Authorizer().require_scope(principal, scope, now=at)
    try:
        owner_id = UUID(principal.owner_id)
    except ValueError:
        raise AuthorizationError("access denied") from None
    identity = session.scalar(
        select(PrincipalModel)
        .where(
            PrincipalModel.owner_id == owner_id,
            PrincipalModel.issuer == principal.issuer,
            PrincipalModel.subject == principal.subject,
            PrincipalModel.status == "active",
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if identity is None:
        raise AuthorizationError("access denied")
    result = ReportAuthorization(
        principal_id=identity.id,
        owner_id=owner_id,
        account_id=account_id,
        required_scopes=required_scopes,
        expires_at=principal.expires_at,
        issuer=identity.issuer,
        subject=identity.subject,
        requesting_principal=principal,
    )
    result.check(session, now=at)
    return result


def authorize_report_job(
    session: Session,
    *,
    principal_id: UUID,
    owner_id: UUID,
    account_id: UUID,
    required_scopes: frozenset[Scope],
    expires_at: datetime,
    now: datetime,
) -> ReportAuthorization:
    """Revalidate the sealed job's initiating identity and bounded current grants."""
    _require_scopes(required_scopes)
    identity = session.scalar(
        select(PrincipalModel)
        .where(PrincipalModel.id == principal_id, PrincipalModel.owner_id == owner_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if identity is None:
        raise AuthorizationError("access denied")
    result = ReportAuthorization(
        principal_id=principal_id,
        owner_id=owner_id,
        account_id=account_id,
        required_scopes=required_scopes,
        expires_at=require_utc(expires_at),
        issuer=identity.issuer,
        subject=identity.subject,
    )
    result.check(session, now=now)
    return result


def _require_scopes(scopes: frozenset[Scope]) -> None:
    if (
        not isinstance(scopes, frozenset)
        or not scopes
        or any(not isinstance(scope, Scope) for scope in scopes)
    ):
        raise AuthorizationError("access denied")
