"""Private capability authority required from the real provider entitlement layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from sqlalchemy import Boolean, false
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from trading212_application.research import ResearchErrorCode, ResearchServiceError
from trading212_domain.research import ResearchEventKind, ResearchRecord
from trading212_domain.sources import SourceUse

if TYPE_CHECKING:
    from .source_retention import SourcePurgeBudget


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCapabilityGrant(ResearchRecord):
    grant_id: UUID
    grant_digest: str
    owner_id: UUID
    provider_id: UUID
    entity_id: UUID
    capability: ResearchEventKind
    license_version_id: UUID
    effective_at: datetime
    expires_at: datetime
    uses: tuple[SourceUse, ...]

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        if (
            self.expires_at <= self.effective_at
            or len(self.uses) != len(set(self.uses))
            or not {SourceUse.STORE, SourceUse.DISPLAY} <= set(self.uses)
        ):
            raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCapabilityScope:
    """Only these fixed research metadata expressions are given to the authority.

    This is an internal entitlement predicate seam, not a source registry or raw
    query port. The implementation must use its actual normalized current/pinned
    approvals and an indexed exact scope; it must not select private payloads.
    """

    source_version_id: ColumnElement[UUID]
    owner_id: ColumnElement[UUID]
    provider_id: ColumnElement[UUID]
    entity_id: ColumnElement[UUID]
    capability: ColumnElement[str]
    license_version_id: ColumnElement[UUID]
    grant_id: ColumnElement[UUID]
    grant_digest: ColumnElement[str]
    retained_at: ColumnElement[datetime]
    original_retained_at: ColumnElement[datetime]
    effective_expires_at: ColumnElement[datetime]


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCapabilityRequest(ResearchRecord):
    source_version_id: UUID
    owner_id: UUID
    provider_id: UUID
    entity_id: UUID
    capability: ResearchEventKind
    license_version_id: UUID
    grant_id: UUID
    grant_digest: str
    retained_at: datetime
    original_retained_at: datetime
    effective_expires_at: datetime


class ResearchCapabilityAuthority(Protocol):
    def research_source_eligibility(
        self,
        scope: ResearchCapabilityScope,
        *,
        now: datetime,
    ) -> ColumnElement[bool]:
        """Pure fixed-scope SQL predicate, equivalent to current batch authority.

        It covers exact original grant ID/digest, owner/provider/entity/capability/
        licence, current and pinned STORE/DISPLAY uses, revocation and both clocks.
        The expression performs no I/O here and never admits synthetic fallback.
        This authoritative predicate is used for exact filtered count and rank;
        every returned source is independently batch-authorized before decoding
        and again at the final boundary. It is not a maintenance eligibility cache.
        """
        ...

    def authorize_research_capabilities(
        self,
        session: Session,
        *,
        requests: tuple[ResearchCapabilityRequest, ...],
        now: datetime,
    ) -> tuple[ResearchCapabilityGrant, ...]:
        """One bounded metadata statement; exact ordered response for every request.

        At most6,400 distinct source versions (100 items times64 citations). Return
        no partial successful batch, and never call a provider or an N+1 resolver.
        Fixed source IDs carry independent immutable scope and original clocks.
        """
        ...

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
        """Resolve/check actual normalized current and pinned grants, without provider I/O.

        A non-None grant_id is immutable provenance, never authority by itself.
        The returned id/digest pin the original grant; effective_at/expires_at and
        uses must conservatively intersect its still-current authorized rights.
        When budget is supplied, charge every actual normalized metadata read to it.
        Implementations must reject revoked/missing/expired grants and verify exact
        current owner/provider/entity/capability/license scope before returning.
        """
        ...


def require_research_capability(
    authority: ResearchCapabilityAuthority | None,
    session: Session,
    *,
    owner_id: UUID,
    provider_id: UUID,
    entity_id: UUID,
    capability: ResearchEventKind,
    license_version_id: UUID,
    now: datetime,
    grant_id: UUID | None = None,
    grant_digest: str | None = None,
    budget: SourcePurgeBudget | None = None,
) -> ResearchCapabilityGrant:
    if authority is None:
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    try:
        grant = authority.authorize_research_capability(
            session,
            owner_id=owner_id,
            provider_id=provider_id,
            entity_id=entity_id,
            capability=capability,
            license_version_id=license_version_id,
            grant_id=grant_id,
            now=now,
            budget=budget,
        )
    except ResearchServiceError:
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE) from None
    if (
        type(grant) is not ResearchCapabilityGrant
        or (
            grant.owner_id,
            grant.provider_id,
            grant.entity_id,
            grant.capability,
            grant.license_version_id,
        )
        != (owner_id, provider_id, entity_id, capability, license_version_id)
        or not grant.effective_at <= now < grant.expires_at
        or (grant_id is not None and grant.grant_id != grant_id)
        or (grant_digest is not None and grant.grant_digest != grant_digest)
    ):
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    return grant


def research_capability_eligibility(
    authority: ResearchCapabilityAuthority | None,
    scope: ResearchCapabilityScope,
    *,
    now: datetime,
) -> ColumnElement[bool]:
    if authority is None:
        return false()
    result = authority.research_source_eligibility(scope, now=now)
    if not isinstance(result, ColumnElement) or not isinstance(result.type, Boolean):
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    return result


def require_research_capabilities(
    authority: ResearchCapabilityAuthority | None,
    session: Session,
    *,
    requests: tuple[ResearchCapabilityRequest, ...],
    now: datetime,
) -> tuple[ResearchCapabilityGrant, ...]:
    if (
        type(requests) is not tuple
        or len(requests) > 6400
        or any(type(item) is not ResearchCapabilityRequest for item in requests)
        or len({item.source_version_id for item in requests}) != len(requests)
    ):
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    if not requests:
        return ()
    if authority is None:
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    try:
        grants = authority.authorize_research_capabilities(session, requests=requests, now=now)
    except ResearchServiceError:
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE) from None
    if type(grants) is not tuple or len(grants) != len(requests):
        raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    for request, grant in zip(requests, grants, strict=True):
        if (
            type(grant) is not ResearchCapabilityGrant
            or (
                grant.owner_id,
                grant.provider_id,
                grant.entity_id,
                grant.capability,
                grant.license_version_id,
                grant.grant_id,
                grant.grant_digest,
            )
            != (
                request.owner_id,
                request.provider_id,
                request.entity_id,
                request.capability,
                request.license_version_id,
                request.grant_id,
                request.grant_digest,
            )
            or not grant.effective_at <= now < grant.expires_at
            or grant.effective_at > request.retained_at
            or request.original_retained_at > request.retained_at
            or request.effective_expires_at > grant.expires_at
            or request.effective_expires_at <= now
        ):
            raise ResearchServiceError(ResearchErrorCode.SOURCE_UNAVAILABLE)
    return grants
