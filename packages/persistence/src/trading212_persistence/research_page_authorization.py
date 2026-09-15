"""One fixed joined page authority statement, with ordered transaction owner locks."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CTE, ScalarSelect
from trading212_application import research as app
from trading212_security.principals import AuthorizationError, Authorizer, Principal

from .models import BrokerAccountModel, BrokerConnectionModel, PrincipalModel
from .premium_models import PremiumOwned
from .report_authorization import ReportAuthorization
from .report_models import PrincipalScopeGrantModel
from .research_models import ResearchAccountStateModel, ResearchOwnerErasureModel
from .research_source_store import research_error


@dataclass(frozen=True, slots=True)
class ResearchPageAuthority:
    auth: ReportAuthorization
    epoch: int


def authorize_research_page(
    session: Session,
    principal: Principal,
    account_id: UUID | None,
    *,
    now: datetime,
    resource: tuple[type[PremiumOwned], UUID] | None = None,
) -> ResearchPageAuthority:
    for scope in app.RESEARCH_READ_SCOPES:
        Authorizer().require_scope(principal, scope, now=now)
    try:
        owner = UUID(principal.owner_id)
    except ValueError:
        raise AuthorizationError("access denied") from None
    # Volatile materialized CTEs form a dependency chain, preserving the existing
    # sources -> xray -> historical -> premium -> research order in one statement.
    previous: CTE | None = None
    for ordinal, namespace in enumerate(("sources", "xray", "historical", "premium", "research")):
        lock = select(
            func.pg_advisory_xact_lock(func.hashtextextended(f"{namespace}:{owner}", 0)).label(
                "held"
            )
        )
        if previous is not None:
            lock = lock.select_from(previous)
        previous = lock.cte(f"research_page_lock_{ordinal}").prefix_with("MATERIALIZED")
    if previous is None:
        raise RuntimeError("Research page lock inventory is empty.")
    target = account_id
    target_account: UUID | ScalarSelect[UUID]
    if resource is not None:
        model, identifier = resource
        target_account = (
            select(model.account_id)
            .where(model.owner_id == owner, model.id == identifier)
            .scalar_subquery()
        )
    elif type(target) is UUID:
        target_account = target
    else:
        raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
    epoch = (
        select(ResearchAccountStateModel.revision)
        .where(
            ResearchAccountStateModel.owner_id == owner,
            ResearchAccountStateModel.account_id == BrokerAccountModel.id,
        )
        .correlate(BrokerAccountModel)
        .scalar_subquery()
    )
    grant = PrincipalScopeGrantModel
    statement = (
        select(PrincipalModel.id, BrokerAccountModel.id, grant.scope, func.coalesce(epoch, 0))
        .select_from(
            PrincipalModel,
        )
        .join(BrokerConnectionModel, BrokerConnectionModel.owner_id == PrincipalModel.owner_id)
        .join(
            BrokerAccountModel,
            BrokerAccountModel.connection_id == BrokerConnectionModel.id,
        )
        .join(grant, grant.principal_id == PrincipalModel.id)
        .join(previous, true())
        .where(
            PrincipalModel.owner_id == owner,
            PrincipalModel.issuer == principal.issuer,
            PrincipalModel.subject == principal.subject,
            PrincipalModel.status == "active",
            BrokerConnectionModel.status == "active",
            BrokerAccountModel.status == "active",
            BrokerAccountModel.id == target_account,
            grant.scope.in_(scope.value for scope in app.RESEARCH_READ_SCOPES),
            grant.granted_at <= now,
            grant.revoked_at.is_(None),
            grant.expires_at.is_(None) | (grant.expires_at > now),
            ~select(ResearchOwnerErasureModel.owner_id)
            .where(ResearchOwnerErasureModel.owner_id == owner)
            .exists(),
        )
        .with_for_update(
            read=True, of=(PrincipalModel, BrokerAccountModel, BrokerConnectionModel, grant)
        )
    )
    rows = session.execute(statement).all()
    required = frozenset(scope.value for scope in app.RESEARCH_READ_SCOPES)
    if len(rows) != len(required) or frozenset(row[2] for row in rows) != required:
        if resource is not None and not rows:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        raise AuthorizationError("access denied")
    identifier, account, _, revision = rows[0]
    if any((row[0], row[1], row[3]) != (identifier, account, revision) for row in rows):
        raise AuthorizationError("access denied")
    return ResearchPageAuthority(
        ReportAuthorization(
            principal_id=identifier,
            owner_id=owner,
            account_id=account,
            required_scopes=app.RESEARCH_READ_SCOPES,
            expires_at=principal.expires_at,
            issuer=principal.issuer,
            subject=principal.subject,
            requesting_principal=principal,
        ),
        revision,
    )
