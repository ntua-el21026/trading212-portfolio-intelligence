"""Account event revisions and complete immutable publication witnesses."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.research_ranking import (
    research_material_digest,
    research_semantic_fact_digest,
)
from trading212_domain.research_serialization import (
    research_event_from_json,
    research_record_bytes,
    research_record_digest,
)
from trading212_domain.research_sources import ResearchCitation, ResearchEventRevision

from .report_authorization import ReportAuthorization
from .research_capacity import admit_research
from .research_models import (
    ResearchAccountStateModel,
    ResearchAliasModel,
    ResearchAliasPromotionModel,
    ResearchCitationModel,
    ResearchEventCitationModel,
    ResearchEventModel,
    ResearchEventPayloadModel,
    ResearchEventRevisionModel,
    ResearchWitnessCitationModel,
    ResearchWitnessModel,
)
from .research_source_store import ResearchSourceStore, research_error, research_owner_lock


class ResearchEventStore(ResearchSourceStore):
    def research_epoch(
        self, session: Session, auth: ReportAuthorization, *, bump: bool = False
    ) -> int:
        row = session.scalar(
            select(ResearchAccountStateModel)
            .where(
                ResearchAccountStateModel.owner_id == auth.owner_id,
                ResearchAccountStateModel.account_id == auth.account_id,
            )
            .with_for_update()
        )
        if row is None:
            row = ResearchAccountStateModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision=1,
                created_at=self._now(),
                updated_at=self._now(),
            )
            session.add(row)
        elif bump:
            row.revision += 1
            row.updated_at = self._now()
        session.flush()
        return row.revision

    def event_header(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> ResearchEventRevisionModel:
        self.research_authority(session, auth)
        row = session.scalar(
            select(ResearchEventRevisionModel)
            .where(
                ResearchEventRevisionModel.owner_id == auth.owner_id,
                ResearchEventRevisionModel.account_id == auth.account_id,
                ResearchEventRevisionModel.id == identifier,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        if not row.sealed or row.expires_at <= self._now():
            raise research_error()
        members = tuple(
            session.scalars(
                select(ResearchEventCitationModel)
                .where(
                    ResearchEventCitationModel.owner_id == auth.owner_id,
                    ResearchEventCitationModel.account_id == auth.account_id,
                    ResearchEventCitationModel.revision_id == row.id,
                )
                .order_by(ResearchEventCitationModel.ordinal)
                .limit(65)
            )
        )
        if len(members) != row.citation_count or tuple(m.ordinal for m in members) != tuple(
            range(row.citation_count)
        ):
            raise research_error()
        deadlines = []
        for member in members:
            cite = session.scalar(
                select(ResearchCitationModel).where(
                    ResearchCitationModel.owner_id == auth.owner_id,
                    ResearchCitationModel.id == member.citation_id,
                )
            )
            if cite is None:
                raise research_error()
            allowed = self.authorize_source(session, auth, cite.source_version_id)
            deadlines.append(allowed.header.effective_expires_at)
        if not deadlines or row.expires_at != min(deadlines) or self._now() >= row.expires_at:
            raise research_error()
        return row

    def read_event(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> ResearchEventRevision:
        row = self.event_header(session, auth, identifier)
        head = session.scalar(
            select(ResearchEventModel).where(
                ResearchEventModel.owner_id == auth.owner_id,
                ResearchEventModel.account_id == auth.account_id,
                ResearchEventModel.id == row.event_id,
            )
        )
        payload = session.scalar(
            select(ResearchEventPayloadModel).where(
                ResearchEventPayloadModel.owner_id == auth.owner_id,
                ResearchEventPayloadModel.account_id == auth.account_id,
                ResearchEventPayloadModel.revision_id == row.id,
            )
        )
        if head is None or payload is None:
            raise research_error()
        value = research_event_from_json(
            payload.canonical_event, expected_digest=row.content_digest
        )
        members = tuple(
            session.scalars(
                select(ResearchEventCitationModel)
                .where(ResearchEventCitationModel.revision_id == row.id)
                .order_by(ResearchEventCitationModel.ordinal)
                .limit(65)
            )
        )
        citations: list[ResearchCitation] = []
        for member in members:
            citation, facts = self.read_citation(session, auth, member.citation_id)
            if facts != value.facts:
                raise research_error()
            citations.append(citation)
        if (
            tuple(citations) != value.citations
            or (
                value.event_id,
                value.revision_id,
                value.revision,
                value.previous_revision_id,
                value.owner_id,
                value.entity_id,
                value.provider_id,
                value.provider_event_key,
                value.created_at,
                value.facts.kind,
                value.facts.published_at,
                research_record_digest(value.facts),
                research_semantic_fact_digest(value),
                research_material_digest(value),
            )
            != (
                row.event_id,
                row.id,
                row.revision,
                row.previous_revision_id,
                row.owner_id,
                row.entity_id,
                head.provider_id,
                head.provider_event_key,
                row.created_at,
                head.kind,
                row.published_at,
                row.facts_digest,
                row.semantic_digest,
                row.material_digest,
            )
            or row.visible_at != max(c.source.first_known_at for c in citations)
        ):
            raise research_error()
        self.event_header(session, auth, identifier)
        return value

    def _append_event(
        self, session: Session, auth: ReportAuthorization, value: ResearchEventRevision
    ) -> ResearchEventRevisionModel:
        deadlines = [
            self.authorize_source(session, auth, c.source.version_id).header.effective_expires_at
            for c in value.citations
        ]
        admit_research(session, auth, "event", payload_bytes=len(research_record_bytes(value)))
        row = ResearchEventRevisionModel(
            id=value.revision_id,
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            event_id=value.event_id,
            revision=value.revision,
            previous_revision_id=value.previous_revision_id,
            entity_id=value.entity_id,
            content_digest=value.content_digest,
            facts_digest=research_record_digest(value.facts),
            semantic_digest=research_semantic_fact_digest(value),
            material_digest=research_material_digest(value),
            published_at=value.facts.published_at,
            visible_at=max(c.source.first_known_at for c in value.citations),
            expires_at=min(deadlines),
            citation_count=len(value.citations),
            sealed=False,
            created_at=value.created_at,
        )
        session.add(row)
        session.flush()
        session.add(
            ResearchEventPayloadModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=row.id,
                canonical_event=research_record_bytes(value),
                created_at=self._now(),
            )
        )
        session.add_all(
            ResearchEventCitationModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=row.id,
                citation_id=c.citation_id,
                ordinal=i,
                created_at=self._now(),
            )
            for i, c in enumerate(value.citations)
        )
        session.flush()
        row.sealed = True
        session.flush()
        return row

    def publish_event(
        self, session: Session, auth: ReportAuthorization, incoming: ResearchEventRevision
    ) -> ResearchEventRevision:
        """Private typed publisher. Original incoming identities are receipts, not account IDs."""
        research_owner_lock(session, auth.owner_id)
        self.research_authority(session, auth, write=True)
        if (
            type(incoming) is not ResearchEventRevision
            or incoming.owner_id != auth.owner_id
            or incoming.created_at > self._now()
        ):
            raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
        prior = session.scalar(
            select(ResearchWitnessModel).where(
                ResearchWitnessModel.owner_id == auth.owner_id,
                ResearchWitnessModel.account_id == auth.account_id,
                ResearchWitnessModel.incoming_digest == incoming.content_digest,
            )
        )
        if prior is not None:
            if not prior.sealed or self.read_witness(session, auth, prior.id) != incoming:
                raise research_error(app.ResearchErrorCode.CONFLICT)
            return self.read_event(session, auth, prior.revision_id)
        for citation in incoming.citations:
            self.publish_citation(session, auth, citation, incoming.facts)
        alias = session.scalar(
            select(ResearchAliasModel).where(
                ResearchAliasModel.owner_id == auth.owner_id,
                ResearchAliasModel.account_id == auth.account_id,
                ResearchAliasModel.provider_id == incoming.provider_id,
                ResearchAliasModel.provider_event_key == incoming.provider_event_key,
            )
        )
        head: ResearchEventModel | None = None
        previous: ResearchEventRevisionModel | None = None
        action = "new_event"
        promotion_alias: ResearchAliasModel | None = None
        if alias is not None:
            promotion = session.scalar(
                select(ResearchAliasPromotionModel).where(
                    ResearchAliasPromotionModel.owner_id == auth.owner_id,
                    ResearchAliasPromotionModel.account_id == auth.account_id,
                    ResearchAliasPromotionModel.alias_id == alias.id,
                )
            )
            target = alias.event_id if promotion is None else promotion.event_id
            head = session.scalar(select(ResearchEventModel).where(ResearchEventModel.id == target))
            if head is not None and (head.provider_id, head.provider_event_key) != (
                incoming.provider_id,
                incoming.provider_event_key,
            ):
                current = session.scalar(
                    select(ResearchEventRevisionModel).where(
                        ResearchEventRevisionModel.event_id == head.id,
                        ResearchEventRevisionModel.revision == head.revision,
                    )
                )
                if current is None or not current.sealed:
                    raise research_error()
                if current.facts_digest != research_record_digest(incoming.facts):
                    promotion_alias = alias
                    head = None
                    action = "new_event"
        else:
            # One indexed exact semantic candidate set, never a truncated global scan.
            candidates = tuple(
                session.scalars(
                    select(ResearchEventModel)
                    .join(
                        ResearchEventRevisionModel,
                        (ResearchEventRevisionModel.event_id == ResearchEventModel.id)
                        & (ResearchEventRevisionModel.revision == ResearchEventModel.revision),
                    )
                    .where(
                        ResearchEventModel.owner_id == auth.owner_id,
                        ResearchEventModel.account_id == auth.account_id,
                        ResearchEventRevisionModel.semantic_digest
                        == research_semantic_fact_digest(incoming),
                    )
                    .order_by(ResearchEventModel.id)
                    .limit(101)
                )
            )
            if len(candidates) > 100:
                raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
            if len(candidates) > 1:
                # A correction may converge with an existing event. Preserve those identities;
                # an ambiguous new alias requires a provider identity, never an invented merge.
                raise research_error(app.ResearchErrorCode.CONFLICT)
            if candidates:
                head = candidates[0]
                action = "semantic_alias"
        if head is not None:
            if (head.owner_id, head.account_id, head.entity_id, head.kind) != (
                auth.owner_id,
                auth.account_id,
                incoming.entity_id,
                incoming.facts.kind,
            ):
                raise research_error(app.ResearchErrorCode.CONFLICT)
            previous = session.scalar(
                select(ResearchEventRevisionModel).where(
                    ResearchEventRevisionModel.event_id == head.id,
                    ResearchEventRevisionModel.revision == head.revision,
                )
            )
            if previous is None or not previous.sealed:
                raise research_error()
            if previous.facts_digest == research_record_digest(incoming.facts):
                old = self.read_event(session, auth, previous.id)

                def semantic_citation(c: ResearchCitation) -> tuple[object, ...]:
                    return (
                        c.source.provider_id,
                        c.source.license_version_id,
                        c.provider_event_key,
                        c.entity_id,
                        c.facts_digest,
                        c.published_at,
                    )

                known = {semantic_citation(c) for c in old.citations}
                added = []
                for citation in incoming.citations:
                    key = semantic_citation(citation)
                    if key not in known:
                        added.append(citation)
                        known.add(key)
                if not added:
                    selected = old
                    action = "retrieval_only"
                else:
                    selected = replace(
                        old,
                        citations=(*old.citations, *added),
                        revision_id=uuid4(),
                        revision=old.revision + 1,
                        previous_revision_id=old.revision_id,
                        created_at=self._now(),
                    )
                    if action != "semantic_alias":
                        action = "material_revision"
            else:
                # An alias cannot manufacture the primary provider's corrected citation.
                if (head.provider_id, head.provider_event_key) != (
                    incoming.provider_id,
                    incoming.provider_event_key,
                ):
                    raise research_error(app.ResearchErrorCode.CONFLICT)
                # Corrections retain their owned event identity and exact previous revision pin.
                selected = replace(
                    incoming,
                    event_id=head.id,
                    revision_id=uuid4(),
                    revision=previous.revision + 1,
                    previous_revision_id=previous.id,
                    provider_id=head.provider_id,
                    provider_event_key=head.provider_event_key,
                    created_at=self._now(),
                )
                action = "material_revision"
            if selected.revision_id != previous.id:
                self._append_event(session, auth, selected)
                head.revision = selected.revision
                head.head_digest = selected.content_digest
                head.updated_at = self._now()
        else:
            selected = replace(
                incoming,
                event_id=uuid4(),
                revision_id=uuid4(),
                revision=1,
                previous_revision_id=None,
                created_at=self._now(),
            )
            head = ResearchEventModel(
                id=selected.event_id,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                entity_id=selected.entity_id,
                provider_id=selected.provider_id,
                provider_event_key=selected.provider_event_key,
                kind=selected.facts.kind,
                revision=1,
                head_digest=selected.content_digest,
                created_at=self._now(),
                updated_at=self._now(),
            )
            session.add(head)
            session.flush()
            self._append_event(session, auth, selected)
        if alias is None:
            session.add(
                ResearchAliasModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    event_id=selected.event_id,
                    provider_id=incoming.provider_id,
                    provider_event_key=incoming.provider_event_key,
                    created_at=self._now(),
                )
            )
        admit_research(session, auth, "receipt")
        witness = ResearchWitnessModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            event_id=selected.event_id,
            revision_id=selected.revision_id,
            incoming_revision_id=incoming.revision_id,
            incoming_event_id=incoming.event_id,
            incoming_revision=incoming.revision,
            incoming_previous_revision_id=incoming.previous_revision_id,
            incoming_created_at=incoming.created_at,
            incoming_provider_id=incoming.provider_id,
            incoming_provider_event_key=incoming.provider_event_key,
            incoming_facts_digest=research_record_digest(incoming.facts),
            incoming_digest=incoming.content_digest,
            action=action,
            citation_count=len(incoming.citations),
            actor_id=auth.principal_id,
            sealed=False,
            created_at=self._now(),
        )
        session.add(witness)
        session.flush()
        session.add_all(
            ResearchWitnessCitationModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                witness_id=witness.id,
                citation_id=c.citation_id,
                ordinal=i,
                created_at=self._now(),
            )
            for i, c in enumerate(incoming.citations)
        )
        session.flush()
        witness.sealed = True
        session.flush()
        if promotion_alias is not None:
            session.add(
                ResearchAliasPromotionModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    alias_id=promotion_alias.id,
                    event_id=selected.event_id,
                    witness_id=witness.id,
                    created_at=self._now(),
                )
            )
            session.flush()
        self.research_epoch(session, auth, bump=True)
        if self.read_witness(session, auth, witness.id) != incoming:
            raise research_error()
        return self.read_event(session, auth, selected.revision_id)

    def read_witness(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> ResearchEventRevision:
        self.research_authority(session, auth)
        witness = session.scalar(
            select(ResearchWitnessModel).where(
                ResearchWitnessModel.owner_id == auth.owner_id,
                ResearchWitnessModel.account_id == auth.account_id,
                ResearchWitnessModel.id == identifier,
            )
        )
        if witness is None or not witness.sealed:
            raise research_error()
        members = tuple(
            session.scalars(
                select(ResearchWitnessCitationModel)
                .where(ResearchWitnessCitationModel.witness_id == witness.id)
                .order_by(ResearchWitnessCitationModel.ordinal)
                .limit(65)
            )
        )
        if len(members) != witness.citation_count or tuple(m.ordinal for m in members) != tuple(
            range(witness.citation_count)
        ):
            raise research_error()
        records = tuple(self.read_citation(session, auth, m.citation_id) for m in members)
        if not records or any(facts != records[0][1] for _, facts in records):
            raise research_error()
        event = session.scalar(
            select(ResearchEventModel).where(
                ResearchEventModel.owner_id == auth.owner_id,
                ResearchEventModel.account_id == auth.account_id,
                ResearchEventModel.id == witness.event_id,
            )
        )
        if event is None:
            raise research_error()
        value = ResearchEventRevision(
            event_id=witness.incoming_event_id,
            revision_id=witness.incoming_revision_id,
            revision=witness.incoming_revision,
            previous_revision_id=witness.incoming_previous_revision_id,
            owner_id=auth.owner_id,
            entity_id=event.entity_id,
            provider_id=witness.incoming_provider_id,
            provider_event_key=witness.incoming_provider_event_key,
            facts=records[0][1],
            citations=tuple(c for c, _ in records),
            created_at=witness.incoming_created_at,
        )
        if (
            value.content_digest != witness.incoming_digest
            or research_record_digest(value.facts) != witness.incoming_facts_digest
        ):
            raise research_error()
        for citation in value.citations:
            self.authorize_source(session, auth, citation.source.version_id)
        self.research_authority(session, auth)
        return value
