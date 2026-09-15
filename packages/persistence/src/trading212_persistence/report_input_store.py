"""Stream complete canonical inputs into one transaction-owned report capture."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain.enums import QualityState
from trading212_domain.report_manifest import (
    build_report_manifest,
    encode_report_chunk,
    encode_report_manifest,
    encode_report_row,
    encode_report_schema,
    report_document_digest,
    validate_report_references,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.reports import (
    MAX_REPORT_DATASET_ROWS,
    MAX_REPORT_DOCUMENT_BYTES,
    ExportSelection,
    ReportCaptureSummary,
    ReportChunk,
    ReportSelection,
    ReportSourceUse,
    ReportTableKey,
    report_profile_version,
    report_schema_version,
)
from trading212_domain.sources import SourceAvailability

from .models import PortfolioSnapshotModel
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_models import (
    ReportInputChunkModel,
    ReportInputLicenseModel,
    ReportInputPinModel,
    ReportInputSnapshotModel,
)


def _remember_reference(
    keys: set[str], key: str | None, *, limit: int = MAX_REPORT_DATASET_ROWS
) -> None:
    if key is None or key in keys:
        return
    if len(keys) >= limit:
        raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
    keys.add(key)


class _TableCapture:
    def __init__(self, key: ReportTableKey) -> None:
        self.digest = hashlib.sha256()
        schema = encode_report_schema(table_schema(key))
        self.schema_digest = hashlib.sha256(schema).hexdigest()
        self.digest.update(len(schema).to_bytes(8, "big"))
        self.digest.update(schema)
        self.chunks = 0
        self.rows = 0
        self.row_keys: set[str] = set()


class ReportInputSink:
    """The service seals exactly once, after the canonical adapter returns proof."""

    def __init__(
        self,
        session: Session,
        authorization: ReportAuthorization,
        *,
        selection: ReportSelection | ExportSelection,
        expires_at: datetime,
        clock: Callable[[], datetime],
    ) -> None:
        self._session = session
        self._authorization = authorization
        self._selection = selection
        self._clock = clock
        self._tables: dict[ReportTableKey, _TableCapture] = {}
        self._context_keys: set[str] = set()
        self._reason_keys: set[str] = set()
        self._bound_keys: set[str] = set()
        self._coverage_keys: set[str] = set()
        self._provenance_set_keys: set[str] = set()
        self._note_set_keys: set[str] = set()
        self._payload_bytes = 0
        self._chunk_count = 0
        self._finished = False
        snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.id == selection.snapshot_id,
                PortfolioSnapshotModel.broker_account_id == authorization.account_id,
            )
        )
        if snapshot is None:
            raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
        at = clock()
        self.row = ReportInputSnapshotModel(
            id=uuid4(),
            owner_id=authorization.owner_id,
            account_id=authorization.account_id,
            created_at=at,
            kind="report" if isinstance(selection, ReportSelection) else "export",
            contract_version=2 if report_schema_version(selection) == "2.0.0" else 1,
            snapshot_id=selection.snapshot_id,
            start_date=selection.start_date,
            end_date=selection.end_date,
            valuation_at=snapshot.valuation_at,
            source_cutoff_at=selection.source_cutoff_at,
            reporting_currency=selection.reporting_currency.value,
            input_digest="0" * 64,
            document_digest="0" * 64,
            canonical_byte_length=0,
            chunk_count=0,
            pin_count=1,
            source_count=0,
            canonical_manifest=b"",
            canonical_context=b"",
            sealed_at=None,
            expires_at=expires_at,
            purged_at=None,
        )
        session.add(self.row)
        session.flush()

    def append(self, chunk: ReportChunk) -> None:
        if self._finished:
            raise report_error(app.ReportServiceErrorCode.CONFLICT)
        payload = encode_report_chunk(chunk)
        if self._payload_bytes + len(payload) > MAX_REPORT_DOCUMENT_BYTES:
            raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
        table = self._tables.get(chunk.table)
        if table is None:
            table = _TableCapture(chunk.table)
            self._tables[chunk.table] = table
        if chunk.ordinal != table.chunks:
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        if table.rows + len(chunk.rows) > 100_000:
            raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
        for row in chunk.rows:
            if row.key in table.row_keys:
                raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
            table.row_keys.add(row.key)
            _remember_reference(self._context_keys, row.context_key, limit=256)
            for cell in row.cells:
                _remember_reference(self._context_keys, cell.context_key, limit=256)
                _remember_reference(self._reason_keys, cell.reason_key)
                _remember_reference(self._bound_keys, cell.bound_key)
                _remember_reference(self._coverage_keys, cell.coverage_key)
                _remember_reference(self._provenance_set_keys, cell.provenance_set_key)
                _remember_reference(self._note_set_keys, cell.note_set_key)
            encoded = encode_report_row(row)
            table.digest.update(len(encoded).to_bytes(8, "big"))
            table.digest.update(encoded)
        table.rows += len(chunk.rows)
        table.chunks += 1
        self._chunk_count += 1
        self._payload_bytes += len(payload)
        self._session.add(
            ReportInputChunkModel(
                id=uuid4(),
                owner_id=self.row.owner_id,
                input_id=self.row.id,
                created_at=self._clock(),
                table_key=chunk.table.value,
                ordinal=chunk.ordinal,
                row_count=len(chunk.rows),
                byte_length=len(payload),
                content_digest=chunk.digest,
                payload=payload,
                purged_at=None,
            )
        )
        # Flush each bounded chunk and release ORM payload ownership immediately.
        self._session.flush()

    def finish(self, summary: ReportCaptureSummary) -> None:
        from trading212_application.reports import encode_report_pinned_context

        from .report_sources import project_report_dependencies

        if (
            self._finished
            or summary.header.selection != self._selection
            or summary.header.owner_id != self.row.owner_id
        ):
            raise report_error(app.ReportServiceErrorCode.CONFLICT)
        if (
            summary.header.valuation_at != self.row.valuation_at
            or report_document_digest(summary.header) != summary.header.document_digest
        ):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        if summary.chunk_count != self._chunk_count:
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        validate_report_references(
            summary.proof,
            context_keys=self._context_keys,
            reason_keys=self._reason_keys,
            bound_keys=self._bound_keys,
            coverage_keys=self._coverage_keys,
            provenance_set_keys=self._provenance_set_keys,
            note_set_keys=self._note_set_keys,
        )
        if set(self._tables) - {d.table for d in summary.header.tables}:
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        for descriptor in summary.header.tables:
            table = self._tables.get(descriptor.table) or _TableCapture(descriptor.table)
            if (
                descriptor.row_count != table.rows
                or descriptor.content_digest != table.digest.hexdigest()
                or descriptor.schema_digest != table.schema_digest
            ):
                raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        manifest = build_report_manifest(summary)
        payload = encode_report_manifest(manifest)
        digest = hashlib.sha256(payload).hexdigest()
        pins = summary.immutable_bindings
        if not 1 <= len(pins) <= 256:
            raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
        quality_order = {
            state: index
            for index, state in enumerate(
                (
                    QualityState.FRESH,
                    QualityState.STALE,
                    QualityState.ESTIMATED,
                    QualityState.PARTIAL,
                    QualityState.UNRECONCILED,
                    QualityState.FAILED,
                )
            )
        }
        states = {descriptor.state for descriptor in summary.header.tables}
        availability = (
            SourceAvailability.FAILED
            if "failed" in states
            else SourceAvailability.UNAVAILABLE
            if states == {"unavailable"}
            else SourceAvailability.PARTIAL
            if states & {"partial", "unavailable"}
            else SourceAvailability.AVAILABLE
        )
        quality = max(
            (context.quality for context in summary.proof.contexts),
            key=quality_order.__getitem__,
            default=QualityState.FRESH,
        )
        warnings = summary.proof.notes
        context = app.ReportPinnedContext(
            profile_version=report_profile_version(self._selection),
            schema_version=report_schema_version(self._selection),
            snapshot_id=self.row.snapshot_id,
            valuation_at=self.row.valuation_at,
            source_cutoff_at=self.row.source_cutoff_at,
            reporting_currency=self._selection.reporting_currency,
            input_digest=digest,
            document_digest=summary.header.document_digest,
            pins=pins,
            quality=app.ReportQualitySummary(
                state=quality,
                availability=availability,
                evaluated_at=self.row.created_at,
                warnings=warnings[:64],
                warning_count=len(warnings),
                warning_omitted_count=max(0, len(warnings) - 64),
            ),
        )
        context_payload = encode_report_pinned_context(context)
        total = self._payload_bytes + len(payload)
        if total > MAX_REPORT_DOCUMENT_BYTES:
            raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
        if summary.canonical_byte_length != total:
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        dependencies = project_report_dependencies(
            self._session,
            self._authorization,
            input_id=self.row.id,
            proof=summary.proof,
            source_use=ReportSourceUse.REPORT
            if isinstance(self._selection, ReportSelection)
            else ReportSourceUse.EXPORT,
            now=self._clock(),
        )
        if len(dependencies) > 100_000:
            raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
        self._session.add_all(dependencies)
        for ordinal, pin in enumerate(pins):
            self._session.add(
                ReportInputPinModel(
                    id=uuid4(),
                    owner_id=self.row.owner_id,
                    input_id=self.row.id,
                    created_at=self._clock(),
                    ordinal=ordinal,
                    kind=f"{pin.family.value}:{pin.role.value}",
                    subject_id=pin.subject_id,
                    parent_id=pin.parent_id,
                    content_digest=pin.content_digest,
                )
            )
        for license in summary.proof.license_references:
            self._session.add(
                ReportInputLicenseModel(
                    id=uuid4(),
                    owner_id=self.row.owner_id,
                    input_id=self.row.id,
                    created_at=self._clock(),
                    provider_id=license.provider_id,
                    license_version_id=license.version_id,
                    content_digest=license.license_digest,
                )
            )
        from .report_premium_sources import bind_report_premium_dependency

        premium_expiry = bind_report_premium_dependency(
            self._session,
            self._authorization,
            self.row,
            self._selection,
            summary,
            now=self._clock(),
        )
        deadlines = [self.row.expires_at]
        if premium_expiry is not None:
            deadlines.append(premium_expiry)
        if summary.copy_expires_at is not None:
            deadlines.append(summary.copy_expires_at)
        deadlines.extend(dep.expires_at for dep in dependencies if dep.expires_at is not None)
        deadlines.extend(
            license.expires_at
            for license in summary.proof.license_references
            if license.expires_at is not None
        )
        self.row.expires_at = min(deadlines)
        if self.row.expires_at <= self._clock():
            raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
        self._authorization.check(self._session, now=self._clock())
        self.row.canonical_manifest = payload
        self.row.canonical_context = context_payload
        self.row.input_digest = digest
        self.row.document_digest = summary.header.document_digest
        self.row.canonical_byte_length = total
        self.row.chunk_count = self._chunk_count
        self.row.pin_count = len(pins)
        self.row.source_count = len(dependencies)
        # Flush the children while the database still sees an open input, then seal.
        self._session.flush()
        self.row.sealed_at = self._clock()
        self._session.flush()
        self._finished = True
