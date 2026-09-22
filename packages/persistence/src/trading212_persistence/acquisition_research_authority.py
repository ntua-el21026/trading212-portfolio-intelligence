"""The real normalized entitlement authority shared by acquisition and research."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from trading212_application.research import ResearchErrorCode, ResearchServiceError
from trading212_domain.research import ResearchEventKind
from trading212_domain.sources import SourceUse

from .acquisition_models import (
    ProviderCapabilityGrantModel as Grant,
)
from .acquisition_models import (
    ProviderCapabilityScopeModel as Scope,
)
from .research_models import ResearchSourceOriginModel, ResearchSourceVersionModel
from .research_permissions import (
    ResearchCapabilityGrant,
    ResearchCapabilityRequest,
    ResearchCapabilityScope,
)
from .source_models import MarketDataProviderModel, ProviderLicenseVersionModel
from .source_retention import SourcePurgeBudget


def _denied() -> ResearchServiceError:
    return ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)


def _as_scope(
    source: type[ResearchSourceVersionModel], origin: type[ResearchSourceOriginModel]
) -> ResearchCapabilityScope:
    return ResearchCapabilityScope(
        source_version_id=cast(ColumnElement[UUID], source.id),
        owner_id=cast(ColumnElement[UUID], source.owner_id),
        provider_id=cast(ColumnElement[UUID], source.provider_id),
        entity_id=cast(ColumnElement[UUID], source.entity_id),
        capability=cast(ColumnElement[str], source.capability),
        license_version_id=cast(ColumnElement[UUID], source.license_version_id),
        grant_id=cast(ColumnElement[UUID], source.capability_grant_id),
        grant_digest=cast(ColumnElement[str], source.capability_grant_digest),
        retained_at=cast(ColumnElement[datetime], source.retained_at),
        original_retained_at=cast(ColumnElement[datetime], origin.original_retained_at),
        effective_expires_at=cast(ColumnElement[datetime], source.effective_expires_at),
    )


def _research_capability(scope: ResearchCapabilityScope) -> ColumnElement[str]:
    # These two names are a closed mapping; unknown capability never matches a grant.
    from sqlalchemy import case

    return case(
        (scope.capability == "news", "news_sentiment"),
        (scope.capability == "company_overview", "company_overview"),
        else_="invalid",
    )


class PostgresResearchCapabilityAuthority:
    """Metadata-only authority. Its SQL predicate is not a cached eligibility decision."""

    def research_source_eligibility(
        self, scope: ResearchCapabilityScope, *, now: datetime
    ) -> ColumnElement[bool]:
        pinned = aliased(Grant)
        current = aliased(Grant)
        original_license = aliased(ProviderLicenseVersionModel)
        current_license = aliased(ProviderLicenseVersionModel)
        latest_grant = (
            select(Grant.id)
            .where(
                Grant.owner_id == pinned.owner_id,
                Grant.scope_id == pinned.scope_id,
                Grant.effective_at <= now,
            )
            .order_by(Grant.effective_at.desc(), Grant.version_number.desc(), Grant.id.desc())
            .limit(1)
            .correlate(pinned)
            .scalar_subquery()
        )
        latest_license = (
            select(ProviderLicenseVersionModel.id)
            .where(
                ProviderLicenseVersionModel.owner_id == scope.owner_id,
                ProviderLicenseVersionModel.provider_id == scope.provider_id,
                ProviderLicenseVersionModel.effective_at <= now,
            )
            .order_by(
                ProviderLicenseVersionModel.effective_at.desc(),
                ProviderLicenseVersionModel.version_number.desc(),
                ProviderLicenseVersionModel.id.desc(),
            )
            .limit(1)
            .correlate_except(ProviderLicenseVersionModel)
            .scalar_subquery()
        )
        deadline = func.least(
            pinned.expires_at,
            current.expires_at,
            scope.original_retained_at
            + func.make_interval(
                0,
                0,
                0,
                func.least(30, original_license.retention_days, current_license.retention_days),
            ),
        )
        return (
            select(pinned.id)
            .select_from(pinned)
            .join(Scope, and_(Scope.owner_id == pinned.owner_id, Scope.id == pinned.scope_id))
            .join(current, current.id == latest_grant)
            .join(
                original_license,
                and_(
                    original_license.owner_id == pinned.owner_id,
                    original_license.id == pinned.license_version_id,
                ),
            )
            .join(current_license, current_license.id == latest_license)
            .join(
                MarketDataProviderModel,
                and_(
                    MarketDataProviderModel.owner_id == pinned.owner_id,
                    MarketDataProviderModel.id == pinned.provider_id,
                ),
            )
            .where(
                pinned.owner_id == scope.owner_id,
                pinned.provider_id == scope.provider_id,
                pinned.id == scope.grant_id,
                pinned.content_digest == scope.grant_digest,
                pinned.license_version_id == scope.license_version_id,
                Scope.subject_kind == "entity",
                Scope.subject_id == scope.entity_id,
                Scope.capability == _research_capability(scope),
                MarketDataProviderModel.key == "alpha_vantage",
                MarketDataProviderModel.configuration_state == "configured",
                pinned.store_allowed,
                pinned.display_allowed,
                current.store_allowed,
                current.display_allowed,
                pinned.effective_at <= scope.retained_at,
                pinned.effective_at <= now,
                pinned.expires_at > now,
                current.expires_at > now,
                current.license_version_id == current_license.id,
                original_license.store_permission == "allowed",
                original_license.display_permission == "allowed",
                current_license.store_permission == "allowed",
                current_license.display_permission == "allowed",
                original_license.effective_at <= scope.retained_at,
                original_license.effective_at <= now,
                original_license.retention_days.is_not(None),
                current_license.retention_days.is_not(None),
                scope.original_retained_at <= scope.retained_at,
                scope.effective_expires_at > now,
                scope.effective_expires_at <= deadline,
            )
            .correlate_except(
                pinned, Scope, current, original_license, current_license, MarketDataProviderModel
            )
            .exists()
        )

    def authorize_research_capabilities(
        self, session: Session, *, requests: tuple[ResearchCapabilityRequest, ...], now: datetime
    ) -> tuple[ResearchCapabilityGrant, ...]:
        if (
            type(requests) is not tuple
            or len(requests) > 6400
            or any(type(x) is not ResearchCapabilityRequest for x in requests)
            or len({x.source_version_id for x in requests}) != len(requests)
        ):
            raise _denied()
        if not requests:
            return ()
        source, origin = ResearchSourceVersionModel, ResearchSourceOriginModel
        pinned = aliased(Grant)
        current = aliased(Grant)
        latest = (
            select(Grant.id)
            .where(
                Grant.owner_id == pinned.owner_id,
                Grant.scope_id == pinned.scope_id,
                Grant.effective_at <= now,
            )
            .order_by(Grant.effective_at.desc(), Grant.version_number.desc(), Grant.id.desc())
            .limit(1)
            .correlate(pinned)
            .scalar_subquery()
        )
        # Select only actual normalized source headers, never caller-proposed grant rows.
        rows = session.execute(
            select(source, origin, pinned, current)
            .select_from(source)
            .join(origin, and_(origin.owner_id == source.owner_id, origin.id == source.origin_id))
            .join(
                pinned,
                and_(pinned.owner_id == source.owner_id, pinned.id == source.capability_grant_id),
            )
            .join(current, current.id == latest)
            .where(
                source.id.in_(x.source_version_id for x in requests),
                source.sealed,
                self.research_source_eligibility(_as_scope(source, origin), now=now),
            )
            .execution_options(populate_existing=True)
        ).all()
        if len(rows) != len(requests):
            raise _denied()
        by_id = {row[0].id: row for row in rows}
        output = []
        for request in requests:
            row = by_id.get(request.source_version_id)
            if row is None:
                raise _denied()
            header, original, grant, current_grant = row
            actual = ResearchCapabilityRequest(
                source_version_id=header.id,
                owner_id=header.owner_id,
                provider_id=header.provider_id,
                entity_id=header.entity_id,
                capability=ResearchEventKind(header.capability),
                license_version_id=header.license_version_id,
                grant_id=header.capability_grant_id,
                grant_digest=header.capability_grant_digest,
                retained_at=header.retained_at,
                original_retained_at=original.original_retained_at,
                effective_expires_at=header.effective_expires_at,
            )
            if actual != request:
                raise _denied()
            output.append(self._view(grant, current_grant, request.entity_id, request.capability))
        return tuple(output)

    @staticmethod
    def _view(
        pinned: Grant, current: Grant, entity_id: UUID, capability: ResearchEventKind
    ) -> ResearchCapabilityGrant:
        from .acquisition_authority import grant_digest

        if (
            grant_digest(pinned) != pinned.content_digest
            or grant_digest(current) != current.content_digest
        ):
            raise _denied()
        uses = tuple(
            use
            for use in SourceUse
            if getattr(pinned, f"{use.value}_allowed") and getattr(current, f"{use.value}_allowed")
        )
        return ResearchCapabilityGrant(
            grant_id=pinned.id,
            grant_digest=pinned.content_digest,
            owner_id=pinned.owner_id,
            provider_id=pinned.provider_id,
            entity_id=entity_id,
            capability=capability,
            license_version_id=pinned.license_version_id,
            effective_at=pinned.effective_at,
            expires_at=min(pinned.expires_at, current.expires_at),
            uses=uses,
        )

    def authorize_research_capability(
        self,
        session: Session,
        *,
        owner_id: UUID,
        provider_id: UUID,
        entity_id: UUID,
        capability: ResearchEventKind,
        license_version_id: UUID,
        grant_id: UUID | None,
        now: datetime,
        budget: SourcePurgeBudget | None = None,
    ) -> ResearchCapabilityGrant:
        # Original/current grants and licences, provider/scope and indexed probes.
        if budget is not None and not budget.inspect(rows=9):
            raise _denied()
        name = {
            ResearchEventKind.NEWS: "news_sentiment",
            ResearchEventKind.COMPANY_OVERVIEW: "company_overview",
        }.get(capability)
        if name is None:
            raise _denied()
        pinned = aliased(Grant)
        current = aliased(Grant)
        license = aliased(ProviderLicenseVersionModel)
        original_license = aliased(ProviderLicenseVersionModel)
        latest = (
            select(Grant.id)
            .where(
                Grant.owner_id == owner_id, Grant.scope_id == Scope.id, Grant.effective_at <= now
            )
            .order_by(Grant.effective_at.desc(), Grant.version_number.desc(), Grant.id.desc())
            .limit(1)
            .correlate(Scope)
            .scalar_subquery()
        )
        current_license = (
            select(ProviderLicenseVersionModel.id)
            .where(
                ProviderLicenseVersionModel.owner_id == owner_id,
                ProviderLicenseVersionModel.provider_id == provider_id,
                ProviderLicenseVersionModel.effective_at <= now,
            )
            .order_by(
                ProviderLicenseVersionModel.effective_at.desc(),
                ProviderLicenseVersionModel.version_number.desc(),
                ProviderLicenseVersionModel.id.desc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(pinned, current)
            .select_from(Scope)
            .join(current, current.id == latest)
            .join(
                pinned,
                and_(
                    pinned.scope_id == Scope.id,
                    pinned.id == (current.id if grant_id is None else grant_id),
                ),
            )
            .join(license, license.id == current_license)
            .join(original_license, original_license.id == pinned.license_version_id)
            .join(MarketDataProviderModel, MarketDataProviderModel.id == Scope.provider_id)
            .where(
                Scope.owner_id == owner_id,
                Scope.provider_id == provider_id,
                Scope.subject_kind == "entity",
                Scope.subject_id == entity_id,
                Scope.capability == name,
                pinned.license_version_id == license_version_id,
                pinned.effective_at <= now,
                pinned.expires_at > now,
                current.expires_at > now,
                pinned.store_allowed,
                pinned.display_allowed,
                current.store_allowed,
                current.display_allowed,
                current.license_version_id == license.id,
                license.store_permission == "allowed",
                license.display_permission == "allowed",
                original_license.owner_id == owner_id,
                original_license.provider_id == provider_id,
                original_license.effective_at <= now,
                original_license.store_permission == "allowed",
                original_license.display_permission == "allowed",
                MarketDataProviderModel.key == "alpha_vantage",
                MarketDataProviderModel.configuration_state == "configured",
            )
            .execution_options(populate_existing=True)
        )
        row = session.execute(statement).one_or_none()
        if row is None:
            raise _denied()
        return self._view(row[0], row[1], entity_id, capability)
