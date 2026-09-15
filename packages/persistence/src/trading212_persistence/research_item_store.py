"""Stable item identities over one exact retained X-ray result; no financial copies."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.research import MAX_RESEARCH_RESPONSE_BYTES
from trading212_domain.research_facts import ResearchXrayPin, copy_research_portfolio_facts
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceUse
from trading212_domain.xray_result import XrayCalculation

from .report_authorization import ReportAuthorization
from .research_capacity import admit_research
from .research_models import (
    ResearchEventRevisionModel,
    ResearchItemModel,
    ResearchNoteModel,
    ResearchNoteRevisionModel,
)
from .research_note_store import ResearchNoteStore
from .research_source_store import research_error
from .source_models import FxSnapshotModel
from .xray_catalog_models import (
    ClassificationSnapshotModel,
    ConstituentSnapshotModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
    FundSourceMappingModel,
)
from .xray_run_models import (
    XrayInputDependencyModel,
    XrayInputSnapshotModel,
    XrayRetentionEventModel,
    XrayRunModel,
)
from .xray_run_store import XrayRunStore


class ResearchItemStore(ResearchNoteStore):
    _research_xray: XrayRunStore

    def xray_metadata(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[UUID, str, str, UUID, datetime | None]:
        self.research_authority(session, auth)
        row = session.execute(
            select(
                XrayRunModel.input_id,
                XrayRunModel.content_digest,
                XrayInputSnapshotModel.input_digest,
                XrayInputSnapshotModel.snapshot_id,
                XrayRunModel.sealed_at,
                XrayInputSnapshotModel.sealed_at,
            )
            .join(XrayInputSnapshotModel, XrayInputSnapshotModel.id == XrayRunModel.input_id)
            .where(
                XrayRunModel.owner_id == auth.owner_id,
                XrayRunModel.id == run_id,
                XrayInputSnapshotModel.owner_id == auth.owner_id,
                XrayInputSnapshotModel.account_id == auth.account_id,
            )
            .with_for_update(read=True, of=(XrayRunModel, XrayInputSnapshotModel))
        ).one_or_none()
        if row is None or row[4] is None or row[5] is None:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        input_id, result_digest, input_digest, snapshot_id = row[:4]
        if (
            session.scalar(
                select(XrayRetentionEventModel.id)
                .where(
                    XrayRetentionEventModel.owner_id == auth.owner_id,
                    XrayRetentionEventModel.input_id == input_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise research_error()
        deadlines = []
        models: tuple[
            tuple[
                type[
                    FxSnapshotModel
                    | ConstituentSnapshotModel
                    | ClassificationSnapshotModel
                    | EntityEvidenceVersionModel
                    | FundDefinitionModel
                    | FundSourceMappingModel
                ],
                str,
            ],
            ...,
        ] = (
            (FxSnapshotModel, "fx_snapshot_id"),
            (ConstituentSnapshotModel, "constituent_snapshot_id"),
            (ClassificationSnapshotModel, "classification_snapshot_id"),
            (EntityEvidenceVersionModel, "entity_evidence_version_id"),
            (FundDefinitionModel, "fund_definition_id"),
            (FundSourceMappingModel, "fund_mapping_id"),
        )
        for model, column in models:
            rows = session.execute(
                select(
                    model.id,
                    model.provider_id,
                    model.license_version_id,
                    model.created_at,
                    model.expires_at,
                )
                .join(
                    XrayInputDependencyModel, getattr(XrayInputDependencyModel, column) == model.id
                )
                .where(
                    XrayInputDependencyModel.owner_id == auth.owner_id,
                    XrayInputDependencyModel.input_id == input_id,
                    model.owner_id == auth.owner_id,
                )
                .distinct()
                .limit(100001)
            ).all()
            if len(rows) > 100000:
                raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
            for _identifier, provider_id, license_id, created_at, expires_at in rows:
                pinned = self._permit(session, auth.owner_id, license_id, SourceUse.DISPLAY)
                self._permit(session, auth.owner_id, license_id, SourceUse.STORE)
                current = self._current_license(session, auth.owner_id, provider_id)
                if (
                    current is None
                    or current.retention_days is None
                    or pinned.retention_days is None
                ):
                    raise research_error()
                deadline = min(
                    expires_at,
                    created_at + timedelta(days=min(pinned.retention_days, current.retention_days)),
                )
                if expires_at > deadline or self._now() >= deadline:
                    raise research_error()
                deadlines.append(deadline)
        return (
            input_id,
            result_digest,
            input_digest,
            snapshot_id,
            min(deadlines) if deadlines else None,
        )

    def retained_xray(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None]:
        metadata = self.xray_metadata(session, auth, run_id)
        principal = auth.as_principal(now=self._now())
        handle = self._research_xray._authorize_xray_run(
            session, principal, auth.account_id, run_id
        )
        value = self._research_xray._load_xray_result(session, principal, auth.account_id, handle)
        pin = ResearchXrayPin(
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            run_id=run_id,
            snapshot_id=value.snapshot_id,
            input_digest=value.input_digest,
            result_digest=value.content_digest,
            reporting_currency=value.reporting_currency,
            valuation_at=value.valuation_at.value,
            source_cutoff_at=value.source_cutoff_at.value,
            quality_evaluated_at=value.quality_evaluated_at.value,
            policy_id=value.policy.id,
            policy_version=value.policy.version,
        )
        if (
            handle.input_id,
            value.content_digest,
            value.input_digest,
            value.snapshot_id,
        ) != metadata[:4]:
            raise research_error()
        final = self.xray_metadata(session, auth, run_id)
        if final[:4] != metadata[:4]:
            raise research_error()
        return pin, value, handle.input_id, final[4]

    def _selection_digest(
        self,
        auth: ReportAuthorization,
        revision: ResearchEventRevisionModel,
        pin: ResearchXrayPin,
        cutoff: datetime,
    ) -> str:
        return sha256(
            b"t212pi.research.item.v1\0"
            + canonical_json(
                (auth.owner_id, auth.account_id, revision.id, revision.content_digest, pin, cutoff)
            ).encode()
        ).hexdigest()

    def _item_identity(
        self,
        session: Session,
        auth: ReportAuthorization,
        revision: ResearchEventRevisionModel,
        pin: ResearchXrayPin,
        input_id: UUID,
        cutoff: datetime,
        deadline: datetime | None,
    ) -> ResearchItemModel:
        identity = self._selection_digest(auth, revision, pin, cutoff)
        row = session.scalar(
            select(ResearchItemModel).where(
                ResearchItemModel.owner_id == auth.owner_id,
                ResearchItemModel.account_id == auth.account_id,
                ResearchItemModel.selection_digest == identity,
            )
        )
        expires = (
            min(revision.expires_at, deadline) if deadline is not None else revision.expires_at
        )
        if row is None:
            if expires <= self._now():
                raise research_error()
            admit_research(session, auth, "item")
            row = ResearchItemModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=revision.id,
                revision_digest=revision.content_digest,
                entity_id=revision.entity_id,
                xray_run_id=pin.run_id,
                xray_input_id=input_id,
                snapshot_id=pin.snapshot_id,
                xray_input_digest=pin.input_digest,
                xray_result_digest=pin.result_digest,
                xray_pin_digest=research_record_digest(pin),
                source_cutoff_at=cutoff,
                selection_digest=identity,
                expires_at=expires,
                created_at=self._now(),
            )
            session.add(row)
            session.flush()
        if row.expires_at > expires or row.expires_at <= self._now():
            raise research_error()
        return row

    def item_view(
        self,
        session: Session,
        auth: ReportAuthorization,
        row: ResearchItemModel,
        pin: ResearchXrayPin,
        xray: XrayCalculation,
        input_id: UUID,
        deadline: datetime | None,
    ) -> app.ResearchItemView:
        self.research_authority(session, auth)
        revision = self.event_header(session, auth, row.revision_id)
        expires = (
            min(revision.expires_at, deadline) if deadline is not None else revision.expires_at
        )
        if (
            (
                row.owner_id,
                row.account_id,
                row.revision_digest,
                row.entity_id,
                row.xray_run_id,
                row.xray_input_id,
                row.snapshot_id,
                row.xray_input_digest,
                row.xray_result_digest,
                row.xray_pin_digest,
            )
            != (
                auth.owner_id,
                auth.account_id,
                revision.content_digest,
                revision.entity_id,
                pin.run_id,
                input_id,
                pin.snapshot_id,
                pin.input_digest,
                pin.result_digest,
                research_record_digest(pin),
            )
            or row.selection_digest
            != self._selection_digest(auth, revision, pin, row.source_cutoff_at)
            or row.expires_at > expires
            or row.expires_at <= self._now()
        ):
            raise research_error()
        source = self.read_event(session, auth, row.revision_id)
        preview = app.preview_research_portfolio(
            copy_research_portfolio_facts(pin, xray, row.entity_id)
        )
        # Bound proof previews by whole warning records and disclose every omitted record.
        # All financial scalars and the canonical facts digest stay unchanged.
        while len(canonical_json(preview).encode()) > MAX_RESEARCH_RESPONSE_BYTES // 2:
            if not preview.warnings:
                raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
            preview = replace(
                preview,
                warnings=preview.warnings[:-1],
                warnings_omitted=preview.warnings_omitted + 1,
            )
        headers = tuple(
            session.execute(
                select(ResearchNoteRevisionModel.id)
                .join(
                    ResearchNoteModel,
                    (ResearchNoteModel.id == ResearchNoteRevisionModel.note_id)
                    & (ResearchNoteModel.revision == ResearchNoteRevisionModel.revision),
                )
                .where(
                    ResearchNoteModel.owner_id == auth.owner_id,
                    ResearchNoteModel.account_id == auth.account_id,
                    ResearchNoteModel.entity_id == row.entity_id,
                )
                .order_by(ResearchNoteModel.created_at.desc(), ResearchNoteModel.id.desc())
                .limit(513)
            ).scalars()
        )
        if len(headers) > 512:
            raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
        review = self.current_review(session, auth, row.revision_id)
        result = app.ResearchItemView(
            item_id=row.id,
            source_cutoff_at=row.source_cutoff_at,
            source=source,
            portfolio=preview,
            owner_revisions_omitted=len(headers),
            review=review,
        )
        used = len(canonical_json(result).encode())
        notes = []
        for identifier in headers[:64]:
            note = self.read_note_revision(session, auth, identifier)
            cost = len(canonical_json(note).encode()) + 1
            if used + cost + 4096 > MAX_RESEARCH_RESPONSE_BYTES:
                break
            notes.append(note)
            used += cost
        result = replace(
            result, owner_revisions=tuple(notes), owner_revisions_omitted=len(headers) - len(notes)
        )
        self.event_header(session, auth, row.revision_id)
        self.xray_metadata(session, auth, pin.run_id)
        if row.expires_at <= self._now():
            raise research_error()
        return result

    def _get_item(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> app.ResearchItemView:
        row = session.scalar(
            select(ResearchItemModel).where(
                ResearchItemModel.owner_id == auth.owner_id,
                ResearchItemModel.account_id == auth.account_id,
                ResearchItemModel.id == identifier,
            )
        )
        if row is None:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        self.event_header(session, auth, row.revision_id)
        if row.expires_at <= self._now():
            raise research_error()
        pin, value, input_id, deadline = self.retained_xray(session, auth, row.xray_run_id)
        return self.item_view(session, auth, row, pin, value, input_id, deadline)
