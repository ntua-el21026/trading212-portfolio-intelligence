"""Stable ranking and explicit revision/dedup decisions with no dropped evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID

from .errors import fail_validation
from .research import MAX_RESEARCH_PAGE, ResearchRecord, research_bound, research_unique
from .research_facts import ResearchPortfolioFacts
from .research_notes import ResearchReviewAcknowledgment
from .research_sources import ResearchEventRevision
from .serialization import canonical_json
from .values import Money, require_utc


def research_semantic_fact_digest(value: ResearchEventRevision) -> str:
    from .research_serialization import research_record_digest

    return sha256(
        b"t212pi.research.facts.v1\0"
        + canonical_json((value.entity_id, research_record_digest(value.facts))).encode()
    ).hexdigest()


def research_material_digest(value: ResearchEventRevision) -> str:
    """Fact/citation semantics only; retrieval, row IDs and request-cutoff drift are not facts."""
    citations = {
        canonical_json(
            (
                item.source.provider_id,
                item.source.license_version_id,
                item.provider_event_key,
                item.entity_id,
                item.facts_digest,
                item.published_at,
            )
        )
        for item in value.citations
    }
    return sha256(
        b"t212pi.research.material.v1\0"
        + canonical_json((research_semantic_fact_digest(value), tuple(sorted(citations)))).encode()
    ).hexdigest()


def research_revision_is_visible(value: ResearchEventRevision, cutoff: datetime) -> bool:
    if type(value) is not ResearchEventRevision or type(cutoff) is not datetime:
        fail_validation("Typed research visibility inputs are required.")
    cutoff = require_utc(cutoff)
    return all(
        item.source.first_known_at <= cutoff
        and (item.published_at is None or item.published_at <= cutoff)
        for item in value.citations
    )


def latest_research_revisions(
    values: tuple[ResearchEventRevision, ...], *, cutoff: datetime
) -> tuple[ResearchEventRevision, ...]:
    """Bounded candidate-page selection; database admission/indexing remains the service's job."""
    research_bound(type(values) is tuple and len(values) <= MAX_RESEARCH_PAGE, "events")
    if type(cutoff) is not datetime:
        fail_validation("A research source cutoff is required.")
    cutoff = require_utc(cutoff)
    selected: dict[UUID, ResearchEventRevision] = {}
    for value in values:
        if type(value) is not ResearchEventRevision:
            fail_validation("A retained research revision is required.")
        if not research_revision_is_visible(value, cutoff):
            continue
        previous = selected.get(value.event_id)
        if previous is not None and (
            previous.owner_id,
            previous.entity_id,
            previous.provider_id,
            previous.provider_event_key,
            previous.facts.kind,
        ) != (
            value.owner_id,
            value.entity_id,
            value.provider_id,
            value.provider_event_key,
            value.facts.kind,
        ):
            fail_validation("Research logical event identity differs.")
        if (
            previous is not None
            and previous.revision == value.revision
            and previous.content_digest != value.content_digest
        ):
            fail_validation("Research revision identity conflicts.")
        if previous is None or value.revision > previous.revision:
            selected[value.event_id] = value
    return tuple(selected[key] for key in sorted(selected))


def validate_research_successor(
    previous: ResearchEventRevision, current: ResearchEventRevision
) -> None:
    if (
        (
            previous.owner_id,
            previous.entity_id,
            previous.event_id,
            previous.provider_id,
            previous.provider_event_key,
            previous.facts.kind,
        )
        != (
            current.owner_id,
            current.entity_id,
            current.event_id,
            current.provider_id,
            current.provider_event_key,
            current.facts.kind,
        )
        or current.previous_revision_id != previous.revision_id
        or current.revision != previous.revision + 1
        or current.created_at < previous.created_at
        or current.revision_id == previous.revision_id
    ):
        fail_validation("Research successor identity or ordering differs.")
    if research_material_digest(previous) == research_material_digest(current):
        fail_validation("Retrieval-only drift must not append a material event revision.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchDedupDecision(ResearchRecord):
    action: Literal[
        "new_event", "exact_replay", "retrieval_only", "material_revision", "semantic_alias"
    ]
    existing_event_ids: tuple[UUID, ...]
    incoming: ResearchEventRevision

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        research_bound(len(self.existing_event_ids) <= MAX_RESEARCH_PAGE, "events")
        research_unique(self.existing_event_ids, "events")
        if (self.action == "new_event") != (not self.existing_event_ids):
            fail_validation("Research dedup identity is inconsistent.")
        object.__setattr__(self, "existing_event_ids", tuple(sorted(self.existing_event_ids)))


def deduplicate_research_event(
    incoming: ResearchEventRevision, existing: tuple[ResearchEventRevision, ...]
) -> ResearchDedupDecision:
    """Return retained witnesses, never merge/drop a provider alias or authorize its data."""
    research_bound(type(existing) is tuple and len(existing) <= MAX_RESEARCH_PAGE, "events")
    if type(incoming) is not ResearchEventRevision or any(
        type(item) is not ResearchEventRevision or item.owner_id != incoming.owner_id
        for item in existing
    ):
        fail_validation("Research dedup owner or type differs.")
    research_unique(tuple(item.event_id for item in existing), "event_heads")
    if any(
        item.event_id == incoming.event_id
        and (item.provider_id, item.provider_event_key)
        != (incoming.provider_id, incoming.provider_event_key)
        for item in existing
    ):
        fail_validation("Research logical event changed provider identity.")
    identity = tuple(
        item
        for item in existing
        if (item.provider_id, item.provider_event_key)
        == (incoming.provider_id, incoming.provider_event_key)
    )
    if len(identity) > 1:
        fail_validation("Research provider identity has conflicting logical events.")
    if identity:
        previous = identity[0]
        if (previous.entity_id, previous.facts.kind) != (incoming.entity_id, incoming.facts.kind):
            fail_validation("Research provider event changed economic identity.")
        action: Literal["exact_replay", "retrieval_only", "material_revision"] = "material_revision"
        if previous.content_digest == incoming.content_digest:
            action = "exact_replay"
        elif research_material_digest(previous) == research_material_digest(incoming):
            action = "retrieval_only"
        return ResearchDedupDecision(
            action=action, existing_event_ids=(previous.event_id,), incoming=incoming
        )
    aliases = tuple(
        item.event_id
        for item in existing
        if research_semantic_fact_digest(item) == research_semantic_fact_digest(incoming)
    )
    return ResearchDedupDecision(
        action="semantic_alias" if aliases else "new_event",
        existing_event_ids=aliases,
        incoming=incoming,
    )


def research_revision_reviewed(
    event: ResearchEventRevision, *, account_id: UUID, review: ResearchReviewAcknowledgment | None
) -> bool:
    if review is not None and (review.owner_id, review.account_id, review.event_id) != (
        event.owner_id,
        account_id,
        event.event_id,
    ):
        fail_validation("Research review scope differs.")
    if (
        review is not None
        and review.revision_id == event.revision_id
        and (
            review.revision_digest != event.content_digest or review.reviewed_at < event.created_at
        )
    ):
        fail_validation("Research review revision differs.")
    return (
        review is not None
        and review.revision_id == event.revision_id
        and review.revision_digest == event.content_digest
    )


def research_rank_key(
    event: ResearchEventRevision, effective_exposure: Money | None, *, reviewed: bool
) -> tuple[int, Decimal, int, int, timedelta, UUID, UUID]:
    """The identical scalar order is shared by complete records and bounded public previews."""
    if (
        type(event) is not ResearchEventRevision
        or type(reviewed) is not bool
        or (effective_exposure is not None and type(effective_exposure) is not Money)
    ):
        fail_validation("Typed research ranking scalars are required.")
    published = event.facts.published_at
    # copy_abs/copy_negate preserve every Q18 digit under a hostile Decimal context.
    return (
        int(effective_exposure is None),
        Decimal(0)
        if effective_exposure is None
        else effective_exposure.amount.copy_abs().copy_negate(),
        int(reviewed),
        int(published is None),
        timedelta(0) if published is None else datetime.max.replace(tzinfo=UTC) - published,
        event.entity_id,
        event.event_id,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchRankedItem(ResearchRecord):
    event: ResearchEventRevision
    portfolio: ResearchPortfolioFacts
    review: ResearchReviewAcknowledgment | None = None

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        if (self.event.owner_id, self.event.entity_id) != (
            self.portfolio.pin.owner_id,
            self.portfolio.entity_id,
        ):
            fail_validation("Research event and portfolio scope differ.")
        research_revision_reviewed(
            self.event, account_id=self.portfolio.pin.account_id, review=self.review
        )

    @property
    def reviewed(self) -> bool:
        return research_revision_reviewed(
            self.event, account_id=self.portfolio.pin.account_id, review=self.review
        )


def rank_research_items(values: tuple[ResearchRankedItem, ...]) -> tuple[ResearchRankedItem, ...]:
    research_bound(type(values) is tuple and len(values) <= MAX_RESEARCH_PAGE, "events")
    if any(type(value) is not ResearchRankedItem for value in values):
        fail_validation("Closed research ranking items are required.")
    research_unique(tuple(value.event.event_id for value in values), "events")
    if values and any(value.portfolio.pin != values[0].portfolio.pin for value in values):
        fail_validation("Research ranking requires one exact X-ray basis.")

    def key(item: ResearchRankedItem) -> tuple[int, Decimal, int, int, timedelta, UUID, UUID]:
        return research_rank_key(
            item.event, item.portfolio.effective_exposure, reviewed=item.reviewed
        )

    return tuple(sorted(values, key=key))
