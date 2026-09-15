"""Fenced immutable projection chunks/results under original retained source authority.

Callers own the surrounding transaction, worker execution slot and terminal job/
capacity transition. No method commits, signs a cursor, resamples, rewrites source
proofs, or changes already sealed financial rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import Select, and_, or_, select, text
from sqlalchemy.orm import Session
from trading212_application.projection import ProjectionErrorCode as Code
from trading212_domain.enums import QualityState
from trading212_domain.projection import PROJECTION_MAX_BYTES, ProjectionVariant
from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import source_integer

from . import projection_models as m
from .premium_models import PremiumJobModel, PremiumRetentionModel, PremiumRunModel
from .projection_definition_store import ProjectionStorageError, projection_owner_lock
from .projection_input_store import (
    CapturedProjectionInputs,
    ProjectionInputStore,
    projection_run_header,
)
from .projection_result_parity import (
    PROJECTION_ROW_BATCH,
    reconcile_chunk_rows,
    reconcile_result_rows,
)
from .projection_result_rows import ProjectionChunkRows, ProjectionResultRows
from .projection_retained_codec import (
    ProjectionChunkBytes,
    ProjectionResultBytes,
    pack_projection_chunk,
    pack_projection_result,
    unpack_projection_chunk,
    unpack_projection_result,
)
from .report_authorization import ReportAuthorization

_VARIANTS: tuple[ProjectionVariant, ...] = ("baseline", "contribution_delta", "mean_log_delta")
_QUALITY_ORDER = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.UNRECONCILED: 3,
    QualityState.PARTIAL: 4,
    QualityState.FAILED: 5,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredProjectionChunk:
    id: UUID
    run_id: UUID
    content_digest: str
    created_at: datetime
    chunk: ProjectionChunk


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredProjectionResult:
    id: UUID
    run_id: UUID
    content_digest: str
    created_at: datetime
    calculation: ProjectionCalculation
    quality: QualityState


@dataclass(frozen=True, slots=True, kw_only=True)
class _Fence:
    job_id: UUID
    lease_token: UUID
    consumer_attempt: int

    def __post_init__(self) -> None:
        if type(self.job_id) is not UUID or type(self.lease_token) is not UUID:
            raise ProjectionStorageError(Code.VALIDATION_FAILED)
        source_integer(self.consumer_attempt, "consumer_attempt", 1, 4)


class ProjectionResultStore(ProjectionInputStore):
    def _load_root(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        *,
        fence: _Fence | None,
    ) -> tuple[ReportAuthorization, PremiumRunModel, datetime]:
        auth = self.authority(session, auth, write="run" if fence is not None else None)
        if type(root.id) is not UUID or type(captured) is not CapturedProjectionInputs:
            raise ProjectionStorageError(Code.VALIDATION_FAILED)
        projection_owner_lock(session, auth.owner_id)
        current = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == root.id,
                PremiumRunModel.owner_id == auth.owner_id,
                PremiumRunModel.account_id == auth.account_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        run = session.scalar(
            select(m.ProjectionRunModel)
            .where(
                m.ProjectionRunModel.id == root.id,
                m.ProjectionRunModel.owner_id == auth.owner_id,
                m.ProjectionRunModel.account_id == auth.account_id,
            )
            .execution_options(populate_existing=True)
        )
        if current is None or run is None:
            raise ProjectionStorageError(Code.NOT_FOUND)
        if (
            current.kind != "projection"
            or not run.sealed
            or run.created_at != current.created_at
            or root.owner_id != auth.owner_id
            or root.account_id != auth.account_id
            or captured.plan.selection.account_id != auth.account_id
            or current.input_digest != captured.input_digest
            or current.method_version != "1.0.0"
            or current.schema_version != "1.0.0"
            or current.numerical_profile != "premium_decimal96_q18_v1"
            or any(
                getattr(run, key) != value
                for key, value in projection_run_header(
                    captured.plan, len(captured.sources.sources)
                ).items()
            )
        ):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        self._not_expired(session, auth, current)
        if fence is not None:
            self._fence(session, auth, current, fence)
        # The input store checks metadata/current and original licenses before its
        # private input/proof reads; passing a typed capture never skips this check.
        retained = self.read_retained_input(session, auth, current.id)

        def proof(value: CapturedProjectionInputs) -> tuple[object, ...]:
            return tuple(
                (
                    source.header.kind,
                    source.header.role,
                    source.header.subject_id,
                    source.header.content_digest,
                    source.header.original_created_at,
                    source.header.license_version_ids,
                    source.quality,
                    source.canonical_proof,
                )
                for source in value.sources.sources
            )

        if (
            retained.plan != captured.plan
            or retained.stored != captured.stored
            or proof(retained) != proof(captured)
        ):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        deadline = self._source_boundary(session, auth, current, retained)
        self._result_bytes(session, current)
        return auth, current, deadline

    def _not_expired(
        self, session: Session, auth: ReportAuthorization, root: PremiumRunModel
    ) -> None:
        if (
            root.expires_at <= self._now()
            or root.created_at > self._now()
            or session.scalar(
                select(PremiumRetentionModel.id)
                .where(
                    PremiumRetentionModel.run_id == root.id,
                    PremiumRetentionModel.owner_id == auth.owner_id,
                    PremiumRetentionModel.account_id == auth.account_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise ProjectionStorageError(Code.RUN_EXPIRED)

    def _source_boundary(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
    ) -> datetime:
        headers, deadline = self.sources.authorize_sources(
            session,
            auth,
            captured.plan.assumption_version.content.calibration_pins,
            snapshot_id=captured.plan.selection.initial.snapshot_id,
            retained_at=root.created_at,
        )
        original = {
            (source.header.role, source.header.subject_id): source.header
            for source in captured.sources.sources
        }
        if len(headers) != len(original) or any(
            (expected := original.get((header.role, header.subject_id))) is None
            or header.kind != expected.kind
            or header.content_digest != expected.content_digest
            or header.original_created_at != expected.original_created_at
            or header.license_version_ids != expected.license_version_ids
            for header in headers
        ):
            raise ProjectionStorageError(Code.SOURCE_UNAVAILABLE)
        auth.check(session, now=self._now())
        self._not_expired(session, auth, root)
        if (
            root.expires_at > deadline
            or root.expires_at > captured.expires_at
            or deadline <= self._now()
        ):
            raise ProjectionStorageError(Code.RUN_EXPIRED)
        return deadline

    def _fence(
        self, session: Session, auth: ReportAuthorization, root: PremiumRunModel, fence: _Fence
    ) -> PremiumJobModel:
        job = session.scalar(
            select(PremiumJobModel)
            .where(
                PremiumJobModel.id == fence.job_id,
                PremiumJobModel.run_id == root.id,
                PremiumJobModel.owner_id == auth.owner_id,
                PremiumJobModel.account_id == auth.account_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        at = self._now()
        if (
            root.actor_principal_id != auth.principal_id
            or job is None
            or job.state != "running"
            or job.lease_token != fence.lease_token
            or job.consumer_attempts != fence.consumer_attempt
            or job.lease_expires_at is None
            or job.lease_expires_at <= at
            or job.deadline_at is None
            or job.deadline_at <= at
            or root.reserved_bytes != PROJECTION_MAX_BYTES
        ):
            raise ProjectionStorageError(Code.INVALID_STATE_TRANSITION)
        return job

    def _batch_boundary(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        deadline: datetime,
        fence: _Fence | None,
    ) -> None:
        # Source/parent owner locks stay held for this entire transaction. Time
        # checks still apply to every bounded private read/write batch.
        auth.check(session, now=self._now())
        if min(root.expires_at, deadline) <= self._now():
            raise ProjectionStorageError(Code.RUN_EXPIRED)
        if fence is not None:
            self._fence(session, auth, root, fence)

    def _result_bytes(self, session: Session, root: PremiumRunModel) -> int:
        size = session.scalar(text("SELECT projection_storage_bytes(:run)"), {"run": root.id})
        if (
            type(size) is not int
            or not 0 <= size <= PROJECTION_MAX_BYTES
            or size > root.reserved_bytes + root.retained_bytes
            or root.reserved_bytes + root.retained_bytes > PROJECTION_MAX_BYTES
        ):
            raise ProjectionStorageError(Code.INPUT_BOUND_EXCEEDED)
        return size

    def _chunk_query(
        self, auth: ReportAuthorization, root: PremiumRunModel
    ) -> Select[tuple[m.ProjectionChunkModel]]:
        return (
            select(m.ProjectionChunkModel)
            .where(
                m.ProjectionChunkModel.run_id == root.id,
                m.ProjectionChunkModel.owner_id == auth.owner_id,
                m.ProjectionChunkModel.account_id == auth.account_id,
            )
            .order_by(m.ProjectionChunkModel.variant, m.ProjectionChunkModel.first_path)
        )

    def _chunk(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        header: m.ProjectionChunkModel,
        *,
        boundary: Callable[[], None],
    ) -> StoredProjectionChunk:
        if (
            not header.sealed
            or header.variant not in captured.plan.inputs.variants
            or not 1 <= header.consumer_attempt <= 4
            or type(header.job_id) is not UUID
            or type(header.lease_token) is not UUID
            or header.input_digest != captured.plan.numerical_input_digest
            or header.run_id != root.id
            or header.owner_id != auth.owner_id
            or header.account_id != auth.account_id
            or header.created_at < root.created_at
            or header.created_at > self._now()
            or not 1 <= header.byte_length <= PROJECTION_MAX_BYTES
        ):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        boundary()
        payload = session.scalar(
            select(m.ProjectionChunkModel.canonical_chunk).where(
                m.ProjectionChunkModel.id == header.id,
                m.ProjectionChunkModel.run_id == root.id,
                m.ProjectionChunkModel.owner_id == auth.owner_id,
                m.ProjectionChunkModel.account_id == auth.account_id,
            )
        )
        if not payload:
            raise ProjectionStorageError(Code.RUN_EXPIRED)
        packed = ProjectionChunkBytes(
            canonical_chunk=payload,
            byte_length=header.byte_length,
            content_digest=header.content_digest,
            input_digest=header.input_digest,
            variant=header.variant,
            first_path=header.first_path,
            path_count=header.path_count,
        )
        chunk = unpack_projection_chunk(packed, expected_inputs=captured.plan.inputs)
        reconcile_chunk_rows(
            session,
            ProjectionChunkRows(run_id=root.id, chunk_id=header.id, value=chunk),
            owner=auth.owner_id,
            account=auth.account_id,
            created_at=header.created_at,
            publish=False,
            boundary=boundary,
        )
        return StoredProjectionChunk(
            id=header.id,
            run_id=root.id,
            content_digest=header.content_digest,
            created_at=header.created_at,
            chunk=chunk,
        )

    def publish_chunk(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        chunk: ProjectionChunk,
        *,
        job_id: UUID,
        lease_token: UUID,
        consumer_attempt: int,
    ) -> StoredProjectionChunk:
        fence = _Fence(job_id=job_id, lease_token=lease_token, consumer_attempt=consumer_attempt)
        auth, root, deadline = self._load_root(session, auth, root, captured, fence=fence)
        packed = pack_projection_chunk(chunk, expected_inputs=captured.plan.inputs)

        def boundary() -> None:
            return self._batch_boundary(session, auth, root, deadline, fence)

        # Owner/root locks serialize overlapping publications, including a changed
        # chunk size on a resumed delivery. Exact old sealed ranges are reusable.
        overlap = tuple(
            session.scalars(
                select(m.ProjectionChunkModel)
                .where(
                    m.ProjectionChunkModel.run_id == root.id,
                    m.ProjectionChunkModel.owner_id == auth.owner_id,
                    m.ProjectionChunkModel.account_id == auth.account_id,
                    m.ProjectionChunkModel.variant == packed.variant,
                    m.ProjectionChunkModel.first_path < packed.first_path + packed.path_count,
                    m.ProjectionChunkModel.first_path + m.ProjectionChunkModel.path_count
                    > packed.first_path,
                )
                .limit(33)
            )
        )
        if overlap:
            if len(overlap) != 1:
                raise ProjectionStorageError(Code.CONFLICT)
            prior = overlap[0]
            if (
                prior.first_path != packed.first_path
                or prior.path_count != packed.path_count
                or prior.content_digest != packed.content_digest
                or prior.job_id != job_id
                or prior.consumer_attempt > consumer_attempt
            ):
                raise ProjectionStorageError(Code.CONFLICT)
            retained = self._chunk(session, auth, root, captured, prior, boundary=boundary)
            if retained.chunk != chunk:
                raise ProjectionStorageError(Code.CONFLICT)
        else:
            if (
                session.scalar(
                    select(m.ProjectionResultModel.id).where(
                        m.ProjectionResultModel.run_id == root.id
                    )
                )
                is not None
            ):
                raise ProjectionStorageError(Code.INVALID_STATE_TRANSITION)
            at = self._now()
            row = m.ProjectionChunkModel(
                id=uuid5(root.id, f"projection_chunks:{chunk.variant}:{packed.first_path}"),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                created_at=at,
                run_id=root.id,
                job_id=job_id,
                lease_token=lease_token,
                consumer_attempt=consumer_attempt,
                variant=packed.variant,
                first_path=packed.first_path,
                path_count=packed.path_count,
                input_digest=packed.input_digest,
                content_digest=packed.content_digest,
                byte_length=packed.byte_length,
                canonical_chunk=packed.canonical_chunk,
                sealed=False,
            )
            boundary()
            session.add(row)
            session.flush()
            reconcile_chunk_rows(
                session,
                ProjectionChunkRows(run_id=root.id, chunk_id=row.id, value=chunk),
                owner=auth.owner_id,
                account=auth.account_id,
                created_at=at,
                publish=True,
                boundary=boundary,
            )
            self._source_boundary(session, auth, root, captured)
            boundary()
            row.sealed = True
            session.flush()
            retained = StoredProjectionChunk(
                id=row.id,
                run_id=root.id,
                content_digest=row.content_digest,
                created_at=at,
                chunk=chunk,
            )
        self._result_bytes(session, root)
        self._source_boundary(session, auth, root, captured)
        boundary()
        return retained

    def read_chunks(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        *,
        after: tuple[ProjectionVariant, int] | None = None,
        limit: int = 32,
    ) -> tuple[StoredProjectionChunk, ...]:
        source_integer(limit, "chunk_limit", 1, 32)
        if after is not None:
            if type(after) is not tuple or len(after) != 2 or after[0] not in _VARIANTS:
                raise ProjectionStorageError(Code.VALIDATION_FAILED)
            source_integer(after[1], "after_first_path", 0, 4095)
        auth, root, deadline = self._load_root(session, auth, root, captured, fence=None)
        job = self._job(session, auth, root)
        if job.state not in ("queued", "running", "succeeded"):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        query = self._chunk_query(auth, root)
        if after is not None:
            query = query.where(
                or_(
                    m.ProjectionChunkModel.variant > after[0],
                    and_(
                        m.ProjectionChunkModel.variant == after[0],
                        m.ProjectionChunkModel.first_path > after[1],
                    ),
                )
            )
        headers = tuple(session.scalars(query.limit(limit)))

        def boundary() -> None:
            return self._batch_boundary(session, auth, root, deadline, None)

        values: list[StoredProjectionChunk] = []
        consumed = 0
        previous: tuple[str, int] | None = None
        for header in headers:
            if header.job_id != job.id or header.consumer_attempt > job.consumer_attempts:
                raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
            if (
                previous is not None
                and header.variant == previous[0]
                and header.first_path < previous[1]
            ):
                raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
            if consumed + header.byte_length > PROJECTION_MAX_BYTES:
                if not values:
                    raise ProjectionStorageError(Code.INPUT_BOUND_EXCEEDED)
                break
            value = self._chunk(session, auth, root, captured, header, boundary=boundary)
            # Include the returned typed metadata as well as all decoded chunk
            # fields in the aggregate byte bound. Never return an empty prefix.
            size = len(canonical_json(value).encode("utf-8"))
            if consumed + size > PROJECTION_MAX_BYTES:
                if not values:
                    raise ProjectionStorageError(Code.INPUT_BOUND_EXCEEDED)
                break
            values.append(value)
            consumed += size
            previous = (header.variant, header.first_path + header.path_count)
        self._source_boundary(session, auth, root, captured)
        boundary()
        return tuple(values)

    def _job(
        self, session: Session, auth: ReportAuthorization, root: PremiumRunModel
    ) -> PremiumJobModel:
        job = session.scalar(
            select(PremiumJobModel)
            .where(
                PremiumJobModel.run_id == root.id,
                PremiumJobModel.owner_id == auth.owner_id,
                PremiumJobModel.account_id == auth.account_id,
            )
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        return job

    def _complete_chunks(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        value: ProjectionCalculation,
        *,
        job_id: UUID,
        attempt: int,
        created_at: datetime,
        boundary: Callable[[], None],
    ) -> None:
        expected = {variant.variant: variant for variant in value.variants}
        positions = {variant: 0 for variant in captured.plan.inputs.variants}
        consumed = 0
        count = 0
        # Only one metadata batch and one decoded chunk are resident at a time.
        stream = session.scalars(
            self._chunk_query(auth, root).execution_options(yield_per=PROJECTION_ROW_BATCH)
        )
        try:
            for header in stream:
                count += 1
                consumed += header.byte_length
                if count > 3 * 4096 or consumed > PROJECTION_MAX_BYTES:
                    raise ProjectionStorageError(Code.INPUT_BOUND_EXCEEDED)
                variant = cast(ProjectionVariant, header.variant)
                if (
                    variant not in expected
                    or header.first_path != positions.get(variant)
                    or header.job_id != job_id
                    or header.consumer_attempt > attempt
                    or header.created_at > created_at
                ):
                    raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
                saved = self._chunk(session, auth, root, captured, header, boundary=boundary)
                end = header.first_path + header.path_count
                if saved.chunk.paths != expected[variant].paths[header.first_path : end]:
                    raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
                positions[variant] = end
        finally:
            stream.close()
        if any(position != captured.plan.inputs.paths for position in positions.values()):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)

    def _quality(self, captured: CapturedProjectionInputs) -> QualityState:
        return max(
            (QualityState.ESTIMATED, *(source.quality for source in captured.sources.sources)),
            key=_QUALITY_ORDER.__getitem__,
        )

    def _read_result_record(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        row: m.ProjectionResultModel,
        *,
        boundary: Callable[[], None],
    ) -> StoredProjectionResult:
        if (
            not row.sealed
            or not 1 <= row.consumer_attempt <= 4
            or type(row.job_id) is not UUID
            or type(row.lease_token) is not UUID
            or row.run_id != root.id
            or row.owner_id != auth.owner_id
            or row.account_id != auth.account_id
            or row.input_digest != captured.plan.numerical_input_digest
            or row.sampler != "sha256_counter_polar_v1"
            or row.quality != self._quality(captured).value
            or row.created_at < root.created_at
            or row.created_at > self._now()
            or not 1 <= row.byte_length <= PROJECTION_MAX_BYTES
        ):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        boundary()
        payload = session.scalar(
            select(m.ProjectionResultModel.canonical_result).where(
                m.ProjectionResultModel.id == row.id,
                m.ProjectionResultModel.run_id == root.id,
                m.ProjectionResultModel.owner_id == auth.owner_id,
                m.ProjectionResultModel.account_id == auth.account_id,
            )
        )
        if not payload:
            raise ProjectionStorageError(Code.RUN_EXPIRED)
        packed = ProjectionResultBytes(
            canonical_result=payload,
            byte_length=row.byte_length,
            content_digest=row.content_digest,
            input_digest=row.input_digest,
        )
        value = unpack_projection_result(packed, expected_inputs=captured.plan.inputs)
        self._complete_chunks(
            session,
            auth,
            root,
            captured,
            value,
            job_id=row.job_id,
            attempt=row.consumer_attempt,
            created_at=row.created_at,
            boundary=boundary,
        )
        reconcile_result_rows(
            session,
            ProjectionResultRows(result_id=row.id, value=value),
            owner=auth.owner_id,
            account=auth.account_id,
            root=root.id,
            created_at=row.created_at,
            publish=False,
            boundary=boundary,
        )
        return StoredProjectionResult(
            id=row.id,
            run_id=root.id,
            content_digest=row.content_digest,
            created_at=row.created_at,
            calculation=value,
            quality=QualityState(row.quality),
        )

    def publish_result(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
        calculation: ProjectionCalculation,
        *,
        job_id: UUID,
        lease_token: UUID,
        consumer_attempt: int,
    ) -> StoredProjectionResult:
        fence = _Fence(job_id=job_id, lease_token=lease_token, consumer_attempt=consumer_attempt)
        auth, root, deadline = self._load_root(session, auth, root, captured, fence=fence)
        if (
            type(calculation) is not ProjectionCalculation
            or calculation.inputs != captured.plan.inputs
        ):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
        packed = pack_projection_result(calculation)
        if packed.input_digest != captured.plan.numerical_input_digest:
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)

        def boundary() -> None:
            return self._batch_boundary(session, auth, root, deadline, fence)

        prior = session.scalar(
            select(m.ProjectionResultModel).where(
                m.ProjectionResultModel.run_id == root.id,
                m.ProjectionResultModel.owner_id == auth.owner_id,
                m.ProjectionResultModel.account_id == auth.account_id,
            )
        )
        if prior is not None:
            if (
                prior.content_digest != packed.content_digest
                or prior.job_id != job_id
                or prior.consumer_attempt > consumer_attempt
            ):
                raise ProjectionStorageError(Code.CONFLICT)
            saved = self._read_result_record(
                session, auth, root, captured, prior, boundary=boundary
            )
            if saved.calculation != calculation:
                raise ProjectionStorageError(Code.CONFLICT)
        else:
            at = self._now()
            self._complete_chunks(
                session,
                auth,
                root,
                captured,
                calculation,
                job_id=job_id,
                attempt=consumer_attempt,
                created_at=at,
                boundary=boundary,
            )
            row = m.ProjectionResultModel(
                id=uuid5(root.id, "projection_results:v1"),
                run_id=root.id,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                created_at=at,
                job_id=job_id,
                lease_token=lease_token,
                consumer_attempt=consumer_attempt,
                input_digest=packed.input_digest,
                content_digest=packed.content_digest,
                byte_length=packed.byte_length,
                canonical_result=packed.canonical_result,
                quality=self._quality(captured).value,
                sampler=calculation.sampler,
                sealed=False,
            )
            boundary()
            session.add(row)
            session.flush()
            reconcile_result_rows(
                session,
                ProjectionResultRows(result_id=row.id, value=calculation),
                owner=auth.owner_id,
                account=auth.account_id,
                root=root.id,
                created_at=at,
                publish=True,
                boundary=boundary,
            )
            self._source_boundary(session, auth, root, captured)
            boundary()
            row.sealed = True
            session.flush()
            saved = StoredProjectionResult(
                id=row.id,
                run_id=root.id,
                content_digest=row.content_digest,
                created_at=at,
                calculation=calculation,
                quality=self._quality(captured),
            )
        self._result_bytes(session, root)
        self._source_boundary(session, auth, root, captured)
        boundary()
        return saved

    def read_result(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        captured: CapturedProjectionInputs,
    ) -> StoredProjectionResult:
        auth, root, deadline = self._load_root(session, auth, root, captured, fence=None)
        job = self._job(session, auth, root)
        row = session.scalar(
            select(m.ProjectionResultModel).where(
                m.ProjectionResultModel.run_id == root.id,
                m.ProjectionResultModel.owner_id == auth.owner_id,
                m.ProjectionResultModel.account_id == auth.account_id,
            )
        )
        if (
            job.state != "succeeded"
            or row is None
            or row.job_id != job.id
            or row.consumer_attempt > job.consumer_attempts
        ):
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)

        def boundary() -> None:
            return self._batch_boundary(session, auth, root, deadline, None)

        saved = self._read_result_record(session, auth, root, captured, row, boundary=boundary)
        self._result_bytes(session, root)
        self._source_boundary(session, auth, root, captured)
        boundary()
        return saved
