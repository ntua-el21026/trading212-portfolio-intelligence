"""Fixed batched current principal/member authority before any private aggregate bytes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, literal, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CTE
from trading212_application import aggregation as app
from trading212_domain.serialization import canonical_json
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

from .aggregation_models import AggregateOwnerErasureModel
from .models import BrokerAccountModel, BrokerConnectionModel, PrincipalModel
from .report_models import PrincipalScopeGrantModel
from .research_models import ResearchOwnerErasureModel


@dataclass(frozen=True, slots=True)
class AggregateAuthorization:
    principal: Principal
    principal_id: UUID
    owner_id: UUID
    account_ids: tuple[UUID, ...]
    scopes: frozenset[Scope]
    fingerprint: str

    def finish(self, session: Session, *, now: datetime) -> None:
        current = authorize_aggregate_members(
            session, self.principal, self.account_ids, now=now, scopes=self.scopes, lock_owner=False
        )
        if current.principal_id != self.principal_id or current.fingerprint != self.fingerprint:
            raise AuthorizationError("access denied")


def authorize_aggregate_members(
    session: Session,
    principal: Principal,
    accounts: tuple[UUID, ...],
    *,
    now: datetime,
    scopes: frozenset[Scope] = app.AGGREGATE_READ_SCOPES,
    lock_owner: bool = True,
) -> AggregateAuthorization:
    at = require_utc(now)
    if (
        type(accounts) is not tuple
        or len(accounts) > 800
        or len(set(accounts)) != len(accounts)
        or any(type(x) is not UUID for x in accounts)
    ):
        raise AuthorizationError("access denied")
    # 800 is only a page of100 selections times8 members. Every individual saved selection
    # remains1..8.
    allowed = app.AGGREGATE_WRITE_SCOPES | {Scope.ACTIVITY_READ}
    if not app.AGGREGATE_READ_SCOPES <= scopes <= allowed:
        raise AuthorizationError("access denied")
    for scope in scopes:
        Authorizer().require_scope(principal, scope, now=at)
    try:
        owner = UUID(principal.owner_id)
    except ValueError:
        raise AuthorizationError("access denied") from None
    previous: CTE | None = None
    if lock_owner:
        for index, namespace in enumerate(
            ("sources", "xray", "historical", "premium", "aggregate")
        ):
            lock = select(
                func.pg_advisory_xact_lock(func.hashtextextended(f"{namespace}:{owner}", 0)).label(
                    "held"
                )
            )
            if previous is not None:
                lock = lock.select_from(previous)
            previous = lock.cte(f"aggregate_owner_lock_{index}").prefix_with("MATERIALIZED")
    grant = PrincipalScopeGrantModel
    account_column = BrokerAccountModel.id if accounts else literal(None)
    query = (
        select(
            PrincipalModel.id,
            account_column.label("account"),
            grant.scope,
            grant.granted_at,
            grant.expires_at,
        )
        .select_from(PrincipalModel)
        .join(grant, grant.principal_id == PrincipalModel.id)
    )
    if accounts:
        query = (
            query.join(
                BrokerConnectionModel, BrokerConnectionModel.owner_id == PrincipalModel.owner_id
            )
            .join(BrokerAccountModel, BrokerAccountModel.connection_id == BrokerConnectionModel.id)
            .where(
                BrokerAccountModel.id.in_(accounts),
                BrokerAccountModel.status == "active",
                BrokerConnectionModel.status == "active",
            )
        )
    if previous is not None:
        query = query.join(previous, true())
    query = query.where(
        PrincipalModel.owner_id == owner,
        PrincipalModel.issuer == principal.issuer,
        PrincipalModel.subject == principal.subject,
        PrincipalModel.status == "active",
        grant.scope.in_(x.value for x in scopes),
        grant.granted_at <= at,
        grant.revoked_at.is_(None),
        grant.expires_at.is_(None) | (grant.expires_at > at),
        ~select(AggregateOwnerErasureModel.owner_id)
        .where(AggregateOwnerErasureModel.owner_id == owner)
        .exists(),
        ~select(ResearchOwnerErasureModel.owner_id)
        .where(ResearchOwnerErasureModel.owner_id == owner)
        .exists(),
    )
    if accounts:
        query = query.with_for_update(
            read=True, of=(PrincipalModel, grant, BrokerAccountModel, BrokerConnectionModel)
        )
    else:
        query = query.with_for_update(read=True, of=(PrincipalModel, grant))
    rows = session.execute(query).all()
    expected = {
        (account, scope.value)
        for account in (accounts if accounts else (None,))
        for scope in scopes
    }
    if (
        len(rows) != len(expected)
        or {(row[1], row[2]) for row in rows} != expected
        or not rows
        or len({row[0] for row in rows}) != 1
    ):
        raise AuthorizationError("access denied")
    identifier = rows[0][0]
    fingerprint = sha256(
        canonical_json(
            {
                "owner": owner,
                "principal": identifier,
                "accounts": accounts,
                "grants": sorted(
                    ((row[2], row[3], row[4]) for row in rows),
                    key=lambda x: (x[0], x[1], str(x[2])),
                ),
            }
        ).encode()
    ).hexdigest()
    return AggregateAuthorization(principal, identifier, owner, accounts, scopes, fingerprint)
