"""Explicit local/test entitlements for synthetic producer scenarios."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from trading212_domain import build_synthetic_identity
from trading212_domain.values import require_utc
from trading212_persistence.models import AuditEventModel, PrincipalModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope


def seed_synthetic_grants(
    sessions: sessionmaker[Session],
    *,
    app_environment: str,
    at: datetime,
    scopes: frozenset[Scope],
) -> None:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("Synthetic entitlements are restricted to local/test environments.")
    if not isinstance(scopes, frozenset) or any(not isinstance(scope, Scope) for scope in scopes):
        raise ValueError("Explicit typed synthetic entitlements are required.")
    identity, now = build_synthetic_identity(), require_utc(at)
    with sessions.begin() as session:
        principal = session.scalar(
            select(PrincipalModel)
            .where(
                PrincipalModel.id == identity.principal.id,
                PrincipalModel.owner_id == identity.owner.id,
                PrincipalModel.issuer == "local.synthetic",
                PrincipalModel.subject == "synthetic-owner",
                PrincipalModel.status == "active",
            )
            .with_for_update()
        )
        if principal is None:
            raise RuntimeError("The explicit synthetic principal is unavailable.")
        added = []
        for scope in sorted(scopes, key=lambda item: item.value):
            granted = session.scalar(
                insert(PrincipalScopeGrantModel)
                .values(principal_id=principal.id, scope=scope.value, granted_at=now)
                .on_conflict_do_nothing()
                .returning(PrincipalScopeGrantModel.scope)
            )
            if granted is not None:
                added.append(granted)
        # Re-seeding never restores a revoked grant or changes its effective time.
        if added:
            session.add(
                AuditEventModel(
                    id=uuid4(),
                    owner_id=principal.owner_id,
                    principal_id=principal.id,
                    action="principal.scopes.seeded",
                    resource_type="principal",
                    resource_id=str(principal.id),
                    outcome="succeeded",
                    occurred_at=now,
                    safe_metadata={"added_scopes": added, "fixture": "synthetic_producers_v1"},
                )
            )
