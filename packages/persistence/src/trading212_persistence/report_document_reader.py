"""Fenced renderer-thread reads, with a short transaction per bounded chunk."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    decode_report_chunk,
    decode_report_manifest,
    encode_report_row,
    encode_report_schema,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.reports import (
    ReportChunk,
    ReportDocumentHeader,
    ReportFailureCode,
    ReportManifest,
    ReportTableKey,
)
from trading212_security.principals import AuthorizationError

from .report_base import report_owner_lock
from .report_models import ReportInputChunkModel, ReportInputSnapshotModel

if TYPE_CHECKING:
    from .report_job_store import JobClaim, PostgresReportJobStore


class PostgresReportDocumentReader:
    def __init__(self, store: PostgresReportJobStore, claim: JobClaim) -> None:
        self._store = store
        self._claim = claim
        self._closed = False
        self._manifest: ReportManifest | None = self._load_manifest()

    def _load_manifest(self) -> ReportManifest:
        try:
            with self._store._sessions() as session, session.begin():
                report_owner_lock(session, self._claim.message.owner_id)
                job = self._store._live(session, self._claim)
                if job is None:
                    raise jobs.ReportJobInputError(ReportFailureCode.LEASE_EXPIRED)
                authorization = self._store._job_authorization(session, job)
                payload = session.scalar(
                    select(ReportInputSnapshotModel.canonical_manifest).where(
                        ReportInputSnapshotModel.id == job.input_id,
                        ReportInputSnapshotModel.owner_id == job.owner_id,
                    )
                )
                if payload is None or hashlib.sha256(payload).hexdigest() != job.input_digest:
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
                value = decode_report_manifest(payload)
                self._store._sources(session, authorization, job)
                if self._store._live(session, self._claim) is None:
                    raise jobs.ReportJobInputError(ReportFailureCode.LEASE_EXPIRED)
                return value
        except (AuthorizationError, app.ReportServiceError):
            raise jobs.ReportJobInputError(ReportFailureCode.ACCESS_DENIED) from None
        except DomainError:
            raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED) from None
        except SQLAlchemyError:
            raise jobs.ReportJobInputError(
                ReportFailureCode.STORAGE_UNAVAILABLE, retryable=True
            ) from None

    def _check(self) -> None:
        if self._closed:
            raise jobs.ReportJobInputError(ReportFailureCode.INPUT_UNAVAILABLE)
        try:
            with self._store._sessions() as session, session.begin():
                report_owner_lock(session, self._claim.message.owner_id)
                job = self._store._live(session, self._claim)
                if job is None:
                    raise jobs.ReportJobInputError(ReportFailureCode.LEASE_EXPIRED)
                self._store._job_authorization(session, job)
        except (AuthorizationError, app.ReportServiceError):
            raise jobs.ReportJobInputError(ReportFailureCode.ACCESS_DENIED) from None
        except SQLAlchemyError:
            raise jobs.ReportJobInputError(
                ReportFailureCode.STORAGE_UNAVAILABLE, retryable=True
            ) from None

    @property
    def manifest(self) -> ReportManifest:
        self._check()
        if self._manifest is None:
            raise jobs.ReportJobInputError(ReportFailureCode.INPUT_UNAVAILABLE)
        return self._manifest

    @property
    def header(self) -> ReportDocumentHeader:
        return self.manifest.document

    def _read_chunk(self, table: ReportTableKey, ordinal: int) -> ReportChunk | None:
        if self._closed:
            raise jobs.ReportJobInputError(ReportFailureCode.INPUT_UNAVAILABLE)
        try:
            with self._store._sessions() as session, session.begin():
                report_owner_lock(session, self._claim.message.owner_id)
                job = self._store._live(session, self._claim)
                if job is None:
                    raise jobs.ReportJobInputError(ReportFailureCode.LEASE_EXPIRED)
                authorization = self._store._job_authorization(session, job)
                row = session.scalar(
                    select(ReportInputChunkModel).where(
                        ReportInputChunkModel.owner_id == job.owner_id,
                        ReportInputChunkModel.input_id == job.input_id,
                        ReportInputChunkModel.table_key == table.value,
                        ReportInputChunkModel.ordinal == ordinal,
                    )
                )
                if row is None:
                    return None
                if row.purged_at is not None or not 0 < row.byte_length <= 1024 * 1024:
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_UNAVAILABLE)
                payload = session.scalar(
                    select(ReportInputChunkModel.payload).where(
                        ReportInputChunkModel.id == row.id,
                        ReportInputChunkModel.owner_id == job.owner_id,
                    )
                )
                if (
                    payload is None
                    or len(payload) != row.byte_length
                    or hashlib.sha256(payload).hexdigest() != row.content_digest
                ):
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
                value = decode_report_chunk(payload)
                if (
                    value.table is not table
                    or value.ordinal != ordinal
                    or len(value.rows) != row.row_count
                ):
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
                self._store._sources(session, authorization, job)
                return value
        except (AuthorizationError, app.ReportServiceError):
            raise jobs.ReportJobInputError(ReportFailureCode.ACCESS_DENIED) from None
        except DomainError:
            raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED) from None
        except SQLAlchemyError:
            raise jobs.ReportJobInputError(
                ReportFailureCode.STORAGE_UNAVAILABLE, retryable=True
            ) from None

    def iter_chunks(self, table: ReportTableKey) -> Iterator[ReportChunk]:
        manifest = self.manifest
        descriptor = next((item for item in manifest.document.tables if item.table is table), None)
        if descriptor is None:
            raise jobs.ReportJobInputError(ReportFailureCode.INVALID_INPUT)
        digest = hashlib.sha256()
        schema = encode_report_schema(table_schema(table))
        digest.update(len(schema).to_bytes(8, "big"))
        digest.update(schema)
        count = 0
        for ordinal in range(100_001):
            chunk = self._read_chunk(table, ordinal)
            if chunk is None:
                if count != descriptor.row_count or digest.hexdigest() != descriptor.content_digest:
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
                return
            count += len(chunk.rows)
            if count > descriptor.row_count or count > 100_000:
                raise jobs.ReportJobInputError(ReportFailureCode.LIMIT_EXCEEDED)
            for row in chunk.rows:
                encoded = encode_report_row(row)
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            yield chunk
        raise jobs.ReportJobInputError(ReportFailureCode.LIMIT_EXCEEDED)

    def close(self) -> None:
        self._closed = True
        self._manifest = None
