"""Immutable owner notes and exact account-owner review acknowledgments."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.research_notes import (
    ResearchNoteContent,
    ResearchNoteRevision,
    ResearchReviewAcknowledgment,
)
from trading212_domain.research_serialization import (
    research_record_bytes,
    research_record_digest,
)

from .report_authorization import ReportAuthorization
from .report_models import ApplicationCommandIdentityModel
from .research_capacity import admit_research
from .research_event_store import ResearchEventStore
from .research_models import (
    ResearchCommandModel,
    ResearchNoteCitationModel,
    ResearchNoteModel,
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
    ResearchReviewModel,
)
from .research_note_record import research_note_record
from .research_source_store import research_error
from .xray_catalog_models import EconomicEntityModel

ResearchCommandName = Literal[
    "research.note.create.v1", "research.note.version.create.v1", "research.event.review.v1"
]


class ResearchNoteStore(ResearchEventStore):
    def _prior_research_command(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: ResearchCommandName,
        key: str,
        digest: str,
    ) -> ResearchCommandModel | None:
        identity = session.scalar(
            select(ApplicationCommandIdentityModel).where(
                ApplicationCommandIdentityModel.owner_id == auth.owner_id,
                ApplicationCommandIdentityModel.command == command,
                ApplicationCommandIdentityModel.idempotency_key == key,
            )
        )
        if identity is None:
            return None
        if identity.account_id != auth.account_id or identity.command_digest != digest:
            raise research_error(app.ResearchErrorCode.CONFLICT)
        row = session.scalar(
            select(ResearchCommandModel).where(
                ResearchCommandModel.owner_id == auth.owner_id,
                ResearchCommandModel.account_id == auth.account_id,
                ResearchCommandModel.command_id == identity.id,
            )
        )
        if row is None or identity.premium_resource_id not in (row.note_revision_id, row.review_id):
            raise research_error()
        return row

    def _record_research_command(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: ResearchCommandName,
        key: str,
        digest: str,
        correlation: str,
        *,
        note_revision_id: UUID | None = None,
        review_id: UUID | None = None,
    ) -> None:
        identity = ApplicationCommandIdentityModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            command=command,
            idempotency_key=key,
            command_digest=digest,
            premium_resource_id=note_revision_id or review_id,
            premium_actor_id=auth.principal_id,
            premium_correlation_id=correlation,
            report_job_id=None,
            export_job_id=None,
            created_at=self._now(),
        )
        session.add(identity)
        session.flush()
        session.add(
            ResearchCommandModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                command_id=identity.id,
                note_revision_id=note_revision_id,
                review_id=review_id,
                created_at=self._now(),
            )
        )
        session.flush()

    def read_note_revision(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> ResearchNoteRevision:
        self.research_authority(session, auth)
        row = session.scalar(
            select(ResearchNoteRevisionModel).where(
                ResearchNoteRevisionModel.owner_id == auth.owner_id,
                ResearchNoteRevisionModel.account_id == auth.account_id,
                ResearchNoteRevisionModel.id == identifier,
            )
        )
        if row is None or not row.sealed:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        payload = session.scalar(
            select(ResearchNotePayloadModel).where(
                ResearchNotePayloadModel.owner_id == auth.owner_id,
                ResearchNotePayloadModel.account_id == auth.account_id,
                ResearchNotePayloadModel.revision_id == identifier,
            )
        )
        if payload is None:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        citations = tuple(
            session.scalars(
                select(ResearchNoteCitationModel)
                .where(ResearchNoteCitationModel.revision_id == row.id)
                .order_by(ResearchNoteCitationModel.ordinal)
                .limit(65)
            )
        )
        value = research_note_record(row, payload, citations)
        # Notes contain authored text and opaque citation pins only, so a provider expiry
        # does not erase the owner's writing or require re-reading the expired source.
        self.research_authority(session, auth)
        return value

    def _append_note(
        self,
        session: Session,
        auth: ReportAuthorization,
        *,
        note_id: UUID,
        entity_id: UUID,
        content: ResearchNoteContent,
        previous: ResearchNoteRevisionModel | None,
    ) -> ResearchNoteRevision:
        self.research_authority(session, auth, write=True)
        if (
            session.scalar(
                select(EconomicEntityModel.id).where(
                    EconomicEntityModel.owner_id == auth.owner_id,
                    EconomicEntityModel.id == entity_id,
                )
            )
            is None
        ):
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        for pin in content.citations:
            self.read_citation(session, auth, pin.citation_id, expected=pin)
        value = ResearchNoteRevision(
            note_id=note_id,
            revision_id=uuid4(),
            revision=1 if previous is None else previous.revision + 1,
            previous_revision_id=None if previous is None else previous.id,
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            entity_id=entity_id,
            actor_id=auth.principal_id,
            created_at=self._now(),
            content=content,
        )
        cost = len(research_record_bytes(value)) + sum(
            len(v.encode())
            for v in (
                content.title,
                content.note,
                content.thesis,
                content.risks,
                content.catalysts,
                content.break_conditions,
            )
        )
        admit_research(session, auth, "note", payload_bytes=cost)
        head: ResearchNoteModel | None
        if previous is None:
            head = ResearchNoteModel(
                id=note_id,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                entity_id=entity_id,
                revision=1,
                head_digest=value.content_digest,
                created_at=value.created_at,
                updated_at=value.created_at,
            )
            session.add(head)
            session.flush()
        else:
            head = session.scalar(
                select(ResearchNoteModel)
                .where(
                    ResearchNoteModel.owner_id == auth.owner_id,
                    ResearchNoteModel.account_id == auth.account_id,
                    ResearchNoteModel.id == note_id,
                )
                .with_for_update()
            )
            if (
                head is None
                or head.revision != previous.revision
                or head.head_digest != previous.content_digest
            ):
                raise research_error(app.ResearchErrorCode.REVISION_MISMATCH)
        row = ResearchNoteRevisionModel(
            id=value.revision_id,
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            note_id=note_id,
            revision=value.revision,
            previous_revision_id=value.previous_revision_id,
            entity_id=entity_id,
            actor_id=auth.principal_id,
            content_digest=value.content_digest,
            citation_count=len(content.citations),
            sealed=False,
            created_at=value.created_at,
        )
        session.add(row)
        session.flush()
        session.add(
            ResearchNotePayloadModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=row.id,
                canonical_note=research_record_bytes(value),
                title=content.title,
                note=content.note,
                thesis=content.thesis,
                risks=content.risks,
                catalysts=content.catalysts,
                break_conditions=content.break_conditions,
                created_at=value.created_at,
            )
        )
        session.add_all(
            ResearchNoteCitationModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=row.id,
                citation_id=pin.citation_id,
                source_version_id=pin.source_version_id,
                source_version_digest=pin.source_version_digest,
                citation_digest=pin.citation_digest,
                ordinal=i,
                created_at=value.created_at,
            )
            for i, pin in enumerate(content.citations)
        )
        session.flush()
        row.sealed = True
        session.flush()
        if previous is not None:
            head.revision = value.revision
            head.head_digest = value.content_digest
            head.updated_at = value.created_at
            session.flush()
        for pin in content.citations:
            citation = self.read_citation(session, auth, pin.citation_id, expected=pin)[0]
            self.authorize_source(session, auth, citation.source.version_id)
        self.research_epoch(session, auth, bump=True)
        return self.read_note_revision(session, auth, value.revision_id)

    def _create_note(
        self, session: Session, auth: ReportAuthorization, command: app.CreateResearchNote
    ) -> ResearchNoteRevision:
        digest = app.research_command_digest(command, auth.account_id)
        name: ResearchCommandName = "research.note.create.v1"
        prior = self._prior_research_command(session, auth, name, command.idempotency_key, digest)
        if prior is not None:
            if prior.note_revision_id is None:
                raise research_error()
            return self.read_note_revision(session, auth, prior.note_revision_id)
        value = self._append_note(
            session,
            auth,
            note_id=uuid4(),
            entity_id=command.entity_id,
            content=command.content,
            previous=None,
        )
        self._record_research_command(
            session,
            auth,
            name,
            command.idempotency_key,
            digest,
            command.correlation_id,
            note_revision_id=value.revision_id,
        )
        return value

    def _create_note_version(
        self, session: Session, auth: ReportAuthorization, command: app.CreateResearchNoteVersion
    ) -> ResearchNoteRevision:
        digest = app.research_command_digest(command, auth.account_id)
        name: ResearchCommandName = "research.note.version.create.v1"
        prior = self._prior_research_command(session, auth, name, command.idempotency_key, digest)
        if prior is not None:
            if prior.note_revision_id is None:
                raise research_error()
            return self.read_note_revision(session, auth, prior.note_revision_id)
        head = session.scalar(
            select(ResearchNoteModel).where(
                ResearchNoteModel.owner_id == auth.owner_id,
                ResearchNoteModel.account_id == auth.account_id,
                ResearchNoteModel.id == command.note_id,
            )
        )
        if head is None:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        if head.revision != command.expected_revision:
            raise research_error(app.ResearchErrorCode.REVISION_MISMATCH)
        previous = session.scalar(
            select(ResearchNoteRevisionModel).where(
                ResearchNoteRevisionModel.note_id == head.id,
                ResearchNoteRevisionModel.revision == head.revision,
            )
        )
        if previous is None or not previous.sealed:
            raise research_error()
        value = self._append_note(
            session,
            auth,
            note_id=head.id,
            entity_id=head.entity_id,
            content=command.content,
            previous=previous,
        )
        self._record_research_command(
            session,
            auth,
            name,
            command.idempotency_key,
            digest,
            command.correlation_id,
            note_revision_id=value.revision_id,
        )
        return value

    def _review_view(self, row: ResearchReviewModel) -> ResearchReviewAcknowledgment:
        value = ResearchReviewAcknowledgment(
            acknowledgment_id=row.id,
            owner_id=row.owner_id,
            account_id=row.account_id,
            event_id=row.event_id,
            revision_id=row.revision_id,
            revision_digest=row.revision_digest,
            actor_id=row.actor_id,
            reviewed_at=row.reviewed_at,
        )
        if research_record_digest(value) != row.content_digest:
            raise research_error()
        return value

    def current_review(
        self, session: Session, auth: ReportAuthorization, revision_id: UUID
    ) -> ResearchReviewAcknowledgment | None:
        self.research_authority(session, auth)
        row = session.scalar(
            select(ResearchReviewModel)
            .where(
                ResearchReviewModel.owner_id == auth.owner_id,
                ResearchReviewModel.account_id == auth.account_id,
                ResearchReviewModel.revision_id == revision_id,
            )
            .order_by(ResearchReviewModel.reviewed_at.desc(), ResearchReviewModel.id.desc())
            .limit(1)
        )
        return None if row is None else self._review_view(row)

    def _review_event(
        self, session: Session, auth: ReportAuthorization, command: app.ReviewResearchEvent
    ) -> ResearchReviewAcknowledgment:
        value = self.read_event(session, auth, command.revision_id)
        if value.event_id != command.event_id or value.content_digest != command.revision_digest:
            raise research_error(app.ResearchErrorCode.CONFLICT)
        digest = app.research_command_digest(command, auth.account_id)
        name: ResearchCommandName = "research.event.review.v1"
        prior = self._prior_research_command(session, auth, name, command.idempotency_key, digest)
        if prior is not None:
            row = session.scalar(
                select(ResearchReviewModel).where(
                    ResearchReviewModel.owner_id == auth.owner_id,
                    ResearchReviewModel.account_id == auth.account_id,
                    ResearchReviewModel.id == prior.review_id,
                )
            )
            if row is None:
                raise research_error()
            return self._review_view(row)
        row = session.scalar(
            select(ResearchReviewModel).where(
                ResearchReviewModel.owner_id == auth.owner_id,
                ResearchReviewModel.account_id == auth.account_id,
                ResearchReviewModel.event_id == value.event_id,
                ResearchReviewModel.revision_id == value.revision_id,
                ResearchReviewModel.actor_id == auth.principal_id,
            )
        )
        if row is None:
            ack = ResearchReviewAcknowledgment(
                acknowledgment_id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                event_id=value.event_id,
                revision_id=value.revision_id,
                revision_digest=value.content_digest,
                actor_id=auth.principal_id,
                reviewed_at=self._now(),
            )
            row = ResearchReviewModel(
                id=ack.acknowledgment_id,
                owner_id=ack.owner_id,
                account_id=ack.account_id,
                event_id=ack.event_id,
                revision_id=ack.revision_id,
                revision_digest=ack.revision_digest,
                actor_id=ack.actor_id,
                reviewed_at=ack.reviewed_at,
                content_digest=research_record_digest(ack),
                created_at=ack.reviewed_at,
            )
            session.add(row)
            session.flush()
            self.research_epoch(session, auth, bump=True)
        self._record_research_command(
            session,
            auth,
            name,
            command.idempotency_key,
            digest,
            command.correlation_id,
            review_id=row.id,
        )
        self.event_header(session, auth, value.revision_id)
        return self._review_view(row)
