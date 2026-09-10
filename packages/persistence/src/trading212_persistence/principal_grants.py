"""Trusted entitlement provisioning; authenticating a token never grants scopes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Scope

from .models import AuditEventModel, PrincipalModel
from .report_models import PrincipalScopeGrantModel


def provision_principal_scopes(
    session: Session,
    *,
    principal_id: UUID,
    scopes: frozenset[Scope],
    now: datetime,
    expires_at: datetime | None = None,
) -> None:
    """Replace current grants from trusted provisioning, in the caller's transaction.

    No public authentication or report request calls this function. The principal
    lock also serializes authorization and grant revocation at publication/read
    boundaries. Repeating an unchanged provision does not create audit noise.
    """
    at = require_utc(now)
    expiry = require_utc(expires_at) if expires_at is not None else None
    if not isinstance(scopes, frozenset) or any(not isinstance(scope, Scope) for scope in scopes):
        raise ValueError("Known immutable scopes are required.")
    if expiry is not None and expiry <= at:
        raise ValueError("Entitlement expiry must follow its grant.")
    principal = session.scalar(
        select(PrincipalModel)
        .where(PrincipalModel.id == principal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if principal is None or principal.status != "active":
        raise AuthorizationError("access denied")
    existing = {
        row.scope: row
        for row in session.scalars(
            select(PrincipalScopeGrantModel)
            .where(PrincipalScopeGrantModel.principal_id == principal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    changed: list[str] = []
    for scope in sorted(Scope, key=lambda value: value.value):
        row = existing.get(scope.value)
        if scope in scopes:
            if row is None:
                session.add(
                    PrincipalScopeGrantModel(
                        principal_id=principal_id,
                        scope=scope.value,
                        granted_at=at,
                        expires_at=expiry,
                        revoked_at=None,
                    )
                )
                changed.append(scope.value)
            elif row.revoked_at is not None or row.expires_at != expiry:
                row.granted_at, row.expires_at, row.revoked_at = at, expiry, None
                changed.append(scope.value)
        elif row is not None and row.revoked_at is None:
            if at < row.granted_at:
                raise ValueError("Entitlement revocation cannot predate its grant.")
            row.revoked_at = at
            changed.append(scope.value)
    if changed:
        session.add(
            AuditEventModel(
                id=uuid4(),
                owner_id=principal.owner_id,
                principal_id=principal.id,
                action="principal.scopes.provisioned",
                resource_type="principal",
                resource_id=str(principal.id),
                outcome="succeeded",
                occurred_at=at,
                safe_metadata={"changed_scopes": changed},
            )
        )
