"""Metadata-only authorized candidate/count/rank selection for one bounded page."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import ARRAY, Numeric, Text, Uuid, case, column, func, literal, select, true, tuple_
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE
from trading212_application import research as app
from trading212_domain.research import ResearchEventKind, ResearchReviewState
from trading212_domain.xray import XrayDimension
from trading212_domain.xray_result import XrayCalculation

from .report_authorization import ReportAuthorization
from .research_models import (
    ResearchCitationModel,
    ResearchEventCitationModel,
    ResearchEventModel,
    ResearchEventPayloadModel,
    ResearchEventRevisionModel,
    ResearchRetentionModel,
    ResearchReviewModel,
    ResearchSourceOriginModel,
    ResearchSourceVersionModel,
)
from .research_permissions import (
    ResearchCapabilityAuthority,
    ResearchCapabilityRequest,
    ResearchCapabilityScope,
    research_capability_eligibility,
)
from .research_source_store import research_error
from .source_models import MarketDataProviderModel, ProviderLicenseVersionModel


@dataclass(frozen=True, slots=True)
class ResearchSourceMetadata:
    source: ResearchSourceVersionModel
    origin: ResearchSourceOriginModel
    pinned: ProviderLicenseVersionModel
    request: ResearchCapabilityRequest


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    revision: ResearchEventRevisionModel
    event: ResearchEventModel
    review: ResearchReviewModel | None
    members: tuple[tuple[ResearchEventCitationModel, ResearchCitationModel], ...]
    key: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchCandidatePage:
    candidates: tuple[ResearchCandidate, ...]
    sources: tuple[ResearchSourceMetadata, ...]
    total: int
    unknown: int
    remaining: int
    fingerprint: str

    def signature(self) -> tuple[object, ...]:
        return (
            self.total,
            self.unknown,
            self.remaining,
            self.fingerprint,
            tuple(
                (
                    item.revision.id,
                    item.revision.content_digest,
                    item.key,
                    None if item.review is None else (item.review.id, item.review.content_digest),
                    tuple(
                        (m.id, c.id, c.content_digest, c.source_version_id) for m, c in item.members
                    ),
                )
                for item in self.candidates
            ),
            tuple(item.request for item in self.sources),
        )


def _licensed_sources(
    auth: ReportAuthorization,
    authority: ResearchCapabilityAuthority | None,
    *,
    now: datetime,
) -> CTE:
    source, origin = ResearchSourceVersionModel, ResearchSourceOriginModel
    provider, license = MarketDataProviderModel, ProviderLicenseVersionModel
    pinned = aliased(license, name="research_eligibility_pinned")
    current = aliased(license, name="research_eligibility_current")
    current_id = (
        select(license.id)
        .where(
            license.owner_id == source.owner_id,
            license.provider_id == source.provider_id,
            license.effective_at <= now,
        )
        .order_by(license.effective_at.desc(), license.version_number.desc(), license.id.desc())
        .limit(1)
        .correlate(source)
        .scalar_subquery()
    )
    scope = ResearchCapabilityScope(
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
    deadline = func.least(
        source.expires_at,
        origin.expires_at,
        origin.original_retained_at
        + func.make_interval(
            0, 0, 0, func.least(30, pinned.retention_days, current.retention_days)
        ),
    )
    return (
        select(source.id.label("source_id"))
        .join(
            origin,
            (origin.id == source.origin_id) & (origin.owner_id == source.owner_id),
        )
        .join(
            provider, (provider.id == source.provider_id) & (provider.owner_id == source.owner_id)
        )
        .join(
            pinned,
            (pinned.id == source.license_version_id)
            & (pinned.owner_id == source.owner_id)
            & (pinned.provider_id == source.provider_id),
        )
        .join(current, current.id == current_id)
        .where(
            source.owner_id == auth.owner_id,
            source.sealed.is_(True),
            source.effective_expires_at > now,
            source.effective_expires_at <= deadline,
            origin.entity_id == source.entity_id,
            origin.capability == source.capability,
            origin.facts_digest == source.facts_digest,
            origin.original_retained_at <= source.retained_at,
            provider.configuration_state == "configured",
            pinned.effective_at <= now,
            pinned.retention_days.is_not(None),
            current.retention_days.is_not(None),
            pinned.store_permission == "allowed",
            pinned.display_permission == "allowed",
            current.store_permission == "allowed",
            current.display_permission == "allowed",
            ~select(ResearchRetentionModel.id)
            .where(
                ResearchRetentionModel.owner_id == auth.owner_id,
                ResearchRetentionModel.source_version_id == source.id,
            )
            .exists(),
            research_capability_eligibility(authority, scope, now=now),
        )
        .cte("research_page_licensed_sources")
    )


def research_candidate_page(
    session: Session,
    auth: ReportAuthorization,
    query: app.ResearchSummaryQuery,
    xray: XrayCalculation,
    *,
    authority: ResearchCapabilityAuthority | None,
    now: datetime,
    after: tuple[str, ...] | None,
) -> ResearchCandidatePage:
    revision, event, review = ResearchEventRevisionModel, ResearchEventModel, ResearchReviewModel
    member, citation = ResearchEventCitationModel, ResearchCitationModel
    source, origin = ResearchSourceVersionModel, ResearchSourceOriginModel
    license = ProviderLicenseVersionModel
    # Exact canonical company amounts are only ranking inputs. No source prose is
    # parsed into finance, and known lower bounds keep their unchanged provenance.
    entities: list[UUID] = []
    amounts: list[Decimal | None] = []
    for bucket in xray.exposure_buckets:
        if bucket.dimension is not XrayDimension.COMPANY or bucket.bucket_key is None:
            continue
        try:
            entity_id = UUID(bucket.bucket_key)
        except ValueError:
            continue
        entities.append(entity_id)
        amounts.append(None if bucket.effective.value is None else bucket.effective.value.amount)
    exposures = (
        func.unnest(literal(entities, ARRAY(Uuid())), literal(amounts, ARRAY(Numeric())))
        .table_valued(
            column("entity_id", Uuid()),
            column("amount", Numeric()),
        )
        .render_derived(name="research_page_exposures")
    )
    licensed = _licensed_sources(auth, authority, now=now)
    latest = (
        select(revision.id)
        .where(
            revision.owner_id == auth.owner_id,
            revision.account_id == auth.account_id,
            revision.sealed.is_(True),
            revision.visible_at <= query.source_cutoff_at,
            revision.published_at.is_(None) | (revision.published_at <= query.source_cutoff_at),
        )
        .distinct(revision.event_id)
        .order_by(revision.event_id, revision.revision.desc())
        .cte("research_latest_visible")
    )
    review_id = (
        select(review.id)
        .where(
            review.owner_id == auth.owner_id,
            review.account_id == auth.account_id,
            review.revision_id == revision.id,
        )
        .order_by(review.reviewed_at.desc(), review.id.desc())
        .limit(1)
        .correlate(revision)
        .scalar_subquery()
    )
    member_count = (
        select(func.count())
        .select_from(member)
        .where(
            member.owner_id == auth.owner_id,
            member.account_id == auth.account_id,
            member.revision_id == revision.id,
        )
        .correlate(revision)
        .scalar_subquery()
    )
    denied = (
        select(member.id)
        .outerjoin(licensed, licensed.c.source_id == member.source_version_id)
        .where(
            member.owner_id == auth.owner_id,
            member.account_id == auth.account_id,
            member.revision_id == revision.id,
            licensed.c.source_id.is_(None) | member.copy_pending.is_(False),
        )
        .correlate(revision)
        .exists()
    )
    ranks = (
        case((exposures.c.amount.is_(None), 1), else_=0),
        -func.abs(func.coalesce(exposures.c.amount, 0)),
        case((review.id.is_(None), 0), else_=1),
        case((revision.published_at.is_(None), 1), else_=0),
        -func.coalesce(func.extract("epoch", revision.published_at), 0),
        revision.entity_id,
        revision.event_id,
    )
    eligible = (
        select(
            revision.id,
            revision.content_digest,
            review.id.label("review_id"),
            *(value.label(f"rank{i}") for i, value in enumerate(ranks)),
        )
        .join(
            latest,
            latest.c.id == revision.id,
        )
        .join(
            event,
            (event.id == revision.event_id)
            & (event.owner_id == auth.owner_id)
            & (event.account_id == auth.account_id),
        )
        .outerjoin(
            review,
            review.id == review_id,
        )
        .outerjoin(exposures, exposures.c.entity_id == revision.entity_id)
        .where(
            revision.expires_at > now,
            member_count == revision.citation_count,
            ~denied,
            select(ResearchEventPayloadModel.id)
            .where(ResearchEventPayloadModel.revision_id == revision.id)
            .exists(),
        )
    )
    if query.entity_id is not None:
        eligible = eligible.where(revision.entity_id == query.entity_id)
    if query.event_kind is not None:
        eligible = eligible.where(event.kind == query.event_kind.value)
    if query.review_state is not ResearchReviewState.ALL:
        eligible = eligible.where(
            review.id.is_not(None)
            if query.review_state is ResearchReviewState.REVIEWED
            else review.id.is_(None)
        )
    all_rows = eligible.cte("research_eligible_page_rows").prefix_with("MATERIALIZED")
    rank_columns = tuple(all_rows.c[f"rank{i}"] for i in range(7))
    remaining = select(all_rows)
    if after is not None:
        try:
            if len(after) != 7 or any(after[i] not in ("0", "1") for i in (0, 2, 3)):
                raise ValueError("invalid research rank")
            boundary = (
                int(after[0]),
                Decimal(after[1]),
                int(after[2]),
                int(after[3]),
                Decimal(after[4]),
                UUID(after[5]),
                UUID(after[6]),
            )
            if not boundary[1].is_finite() or not boundary[4].is_finite():
                raise ValueError("invalid research rank")
        except (ValueError, ArithmeticError):
            raise research_error(app.ResearchErrorCode.CURSOR_INVALID) from None
        remaining = remaining.where(
            tuple_(*rank_columns) > tuple_(*(literal(value) for value in boundary))
        )
    rest = remaining.cte("research_remaining_page_rows")
    membership_digest = (
        select(
            func.encode(
                func.sha256(
                    func.convert_to(
                        func.coalesce(
                            func.string_agg(
                                all_rows.c.id.cast(Text())
                                + literal(":")
                                + all_rows.c.content_digest,
                                aggregate_order_by(literal("|"), all_rows.c.id),
                            ),
                            "",
                        ),
                        "UTF8",
                    )
                ),
                "hex",
            )
        )
        .select_from(all_rows)
        .scalar_subquery()
    )
    stats = select(
        select(func.count()).select_from(all_rows).scalar_subquery().label("total"),
        select(func.count())
        .select_from(all_rows)
        .where(all_rows.c.rank0 == 1)
        .scalar_subquery()
        .label("unknown"),
        select(func.count()).select_from(rest).scalar_subquery().label("remaining"),
        membership_digest.label("fingerprint"),
    ).cte("research_page_statistics")
    chosen = (
        select(rest)
        .order_by(*(rest.c[f"rank{i}"] for i in range(7)))
        .limit(query.limit)
        .cte("research_chosen_page")
    )
    pinned = aliased(license, name="research_page_pinned")
    statement = (
        select(
            stats.c.total,
            stats.c.unknown,
            stats.c.remaining,
            *(chosen.c[f"rank{i}"] for i in range(7)),
            revision,
            event,
            review,
            member,
            citation,
            source,
            origin,
            pinned,
            stats.c.fingerprint,
        )
        .select_from(stats)
        .outerjoin(chosen, true())
        .outerjoin(revision, revision.id == chosen.c.id)
        .outerjoin(
            event,
            event.id == revision.event_id,
        )
        .outerjoin(review, review.id == chosen.c.review_id)
        .outerjoin(
            member,
            (member.revision_id == revision.id)
            & (member.owner_id == auth.owner_id)
            & (member.account_id == auth.account_id),
        )
        .outerjoin(
            citation, (citation.id == member.citation_id) & (citation.owner_id == auth.owner_id)
        )
        .outerjoin(
            source,
            (source.id == member.source_version_id) & (source.owner_id == auth.owner_id),
        )
        .outerjoin(origin, (origin.id == source.origin_id) & (origin.owner_id == auth.owner_id))
        .outerjoin(
            pinned,
            (pinned.id == source.license_version_id) & (pinned.owner_id == auth.owner_id),
        )
        .order_by(*(chosen.c[f"rank{i}"] for i in range(7)), member.ordinal)
        .execution_options(populate_existing=True)
    )
    rows = session.execute(statement).all()
    if not rows or len(rows) > max(1, query.limit * 64):
        raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
    total, unknown, remaining_count = rows[0][:3]
    fingerprint = rows[0][18]
    candidates: list[ResearchCandidate] = []
    sources: dict[UUID, ResearchSourceMetadata] = {}
    for row in rows:
        (
            header,
            head,
            acknowledgment,
            membership,
            citation_row,
            source_row,
            origin_row,
            pinned_row,
        ) = row[10:18]
        if header is None:
            if len(rows) != 1 or remaining_count:
                raise research_error()
            continue
        if any(
            value is None
            for value in (head, membership, citation_row, source_row, origin_row, pinned_row)
        ):
            raise research_error()
        key = tuple(str(value) for value in row[3:10])
        if candidates and candidates[-1].revision.id == header.id:
            prior = candidates.pop()
            members = (*prior.members, (membership, citation_row))
        else:
            members = ((membership, citation_row),)
        candidates.append(ResearchCandidate(header, head, acknowledgment, members, key))
        request = ResearchCapabilityRequest(
            source_version_id=source_row.id,
            owner_id=source_row.owner_id,
            provider_id=source_row.provider_id,
            entity_id=source_row.entity_id,
            capability=ResearchEventKind(source_row.capability),
            license_version_id=source_row.license_version_id,
            grant_id=source_row.capability_grant_id,
            grant_digest=source_row.capability_grant_digest,
            retained_at=source_row.retained_at,
            original_retained_at=origin_row.original_retained_at,
            effective_expires_at=source_row.effective_expires_at,
        )
        sources[source_row.id] = ResearchSourceMetadata(source_row, origin_row, pinned_row, request)
    for candidate in candidates:
        if (
            len(candidate.members) != candidate.revision.citation_count
            or tuple(m.ordinal for m, _ in candidate.members)
            != tuple(range(candidate.revision.citation_count))
            or any(c.source_version_id != m.source_version_id for m, c in candidate.members)
            or candidate.revision.expires_at
            != min(
                sources[m.source_version_id].source.effective_expires_at
                for m, _ in candidate.members
            )
        ):
            raise research_error()
    return ResearchCandidatePage(
        tuple(candidates),
        tuple(sources[key] for key in sorted(sources, key=str)),
        total,
        unknown,
        remaining_count,
        fingerprint,
    )
