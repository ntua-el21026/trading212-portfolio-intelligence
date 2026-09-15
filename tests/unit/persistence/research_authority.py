"""Synthetic capability authority for the private research port, never production wiring."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, false
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from trading212_application import research as app
from trading212_domain.research import ResearchEventKind
from trading212_persistence.research_permissions import (
    ResearchCapabilityGrant,
    ResearchCapabilityRequest,
    ResearchCapabilityScope,
)
from trading212_persistence.source_retention import SourcePurgeBudget


@dataclass
class SyntheticResearchAuthority:
    grant: ResearchCapabilityGrant
    revoked: bool = False

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
        # No database/provider/model I/O: this fixture implements only the private seam.
        value = self.grant
        if self.revoked or (owner_id, provider_id, entity_id, capability, license_version_id) != (
            value.owner_id,
            value.provider_id,
            value.entity_id,
            value.capability,
            value.license_version_id,
        ):
            raise app.ResearchServiceError(app.ResearchErrorCode.SOURCE_UNAVAILABLE)
        if grant_id is not None and grant_id != value.grant_id:
            raise app.ResearchServiceError(app.ResearchErrorCode.SOURCE_UNAVAILABLE)
        return value

    def research_source_eligibility(
        self,
        scope: ResearchCapabilityScope,
        *,
        now: datetime,
    ) -> ColumnElement[bool]:
        # Deliberately synthetic fixture, not a concrete provider entitlement store.
        value = self.grant
        if self.revoked or not value.effective_at <= now < value.expires_at:
            return false()
        return and_(
            scope.owner_id == value.owner_id,
            scope.provider_id == value.provider_id,
            scope.entity_id == value.entity_id,
            scope.capability == value.capability.value,
            scope.license_version_id == value.license_version_id,
            scope.grant_id == value.grant_id,
            scope.grant_digest == value.grant_digest,
            scope.retained_at >= value.effective_at,
            scope.original_retained_at <= scope.retained_at,
            scope.effective_expires_at <= value.expires_at,
            scope.effective_expires_at > now,
        )

    def authorize_research_capabilities(
        self,
        session: Session,
        *,
        requests: tuple[ResearchCapabilityRequest, ...],
        now: datetime,
    ) -> tuple[ResearchCapabilityGrant, ...]:
        return tuple(
            self.authorize_research_capability(
                session,
                owner_id=request.owner_id,
                provider_id=request.provider_id,
                entity_id=request.entity_id,
                capability=request.capability,
                license_version_id=request.license_version_id,
                grant_id=request.grant_id,
                now=now,
            )
            for request in requests
        )
