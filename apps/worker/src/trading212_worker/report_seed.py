"""Explicit local/test report entitlement seed; existing revocations are preserved."""

from __future__ import annotations

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

SYNTHETIC_REPORT_SCOPES = frozenset(
    {
        Scope.PORTFOLIO_READ,
        Scope.ACTIVITY_READ,
        Scope.TARGETS_READ,
        Scope.ANALYTICS_READ,
        Scope.REPORTS_READ,
        Scope.REPORTS_WRITE,
    }
)


def seed_synthetic_report_grants(
    sessions: sessionmaker[Session], *, app_environment: str, at: datetime
) -> None:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("Synthetic report grants are restricted to local/test environments.")
    identity = build_synthetic_identity()
    now = require_utc(at)
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
            raise RuntimeError("Synthetic report identity is unavailable.")
        added = []
        for scope in sorted(SYNTHETIC_REPORT_SCOPES, key=lambda item: item.value):
            inserted = session.scalar(
                insert(PrincipalScopeGrantModel)
                .values(principal_id=principal.id, scope=scope.value, granted_at=now)
                .on_conflict_do_nothing()
                .returning(PrincipalScopeGrantModel.scope)
            )
            if inserted is not None:
                added.append(inserted)
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
                    safe_metadata={"added_scopes": added, "fixture": "synthetic_reports_v1"},
                )
            )
