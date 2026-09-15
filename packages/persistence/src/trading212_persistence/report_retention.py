"""Bounded report-copy expiry with atomic artifact/grant clearing."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .report_audit import audit_report_job, audit_report_purge
from .report_base import report_owner_lock
from .report_models import (
    ArtifactDownloadGrantModel,
    ExportArtifactModel,
    ExportDispatchOutboxModel,
    ExportJobModel,
    ExportManifestModel,
    ReportArtifactModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
    ReportRetentionWorkModel,
)
from .source_retention import PayloadCopyCost, SourcePurgeBudget
from .source_retention_sql import logical_payload_size


def _clear_payloads(
    session: Session,
    table: Table,
    predicate: ColumnElement[bool],
    *,
    columns: tuple[str, ...],
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    remaining = predicate & or_(*(table.c[column].is_not(None) for column in columns))
    while budget.metadata_limit:
        rows = session.execute(
            select(table.c.id, logical_payload_size(table, columns).label("size"))
            .where(remaining)
            .order_by(table.c.id)
            .limit(budget.metadata_limit)
            .with_for_update(skip_locked=True)
        ).all()
        if not budget.inspect(rows=len(rows)):
            return False
        if not rows:
            if not budget.metadata_limit:
                return False
            pending = session.scalar(select(table.c.id).where(remaining).limit(1))
            if pending is not None:
                budget.inspect(rows=1)
            return pending is None
        ids = budget.reserve_clear_batch(
            tuple(PayloadCopyCost(row_id=row.id, payload_bytes=row.size) for row in rows)
        )
        if not ids:
            return False
        session.execute(
            update(table)
            .where(remaining, table.c.id.in_(ids))
            .values(**dict.fromkeys(columns), purged_at=at)
        )
        if len(ids) != len(rows):
            return False
    return False


def _artifact(
    session: Session,
    owner: UUID,
    identifier: UUID,
    *,
    export: bool,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    if budget.artifacts <= 0 or budget.metadata_limit < 2:
        return False
    model = ExportArtifactModel if export else ReportArtifactModel
    table = cast(Table, model.__table__)
    metadata = session.execute(
        select(model.id, model.byte_length)
        .where(model.owner_id == owner, model.id == identifier, model.purged_at.is_(None))
        .with_for_update(skip_locked=True)
    ).first()
    if metadata is None:
        return False
    if not budget.inspect(rows=1):
        return False
    grant = ArtifactDownloadGrantModel
    parent = grant.export_artifact_id if export else grant.report_artifact_id
    grants_table = cast(Table, grant.__table__)
    columns = (
        "token_digest",
        "report_artifact_id",
        "export_artifact_id",
        "issued_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
    )
    inactive = (
        (grant.owner_id == owner)
        & (parent == identifier)
        & ((grant.expires_at <= at) | grant.revoked_at.is_not(None))
    )
    # Invalid tokens can be cleared independently in bounded batches; only the
    # at-most-ten still valid grants must commit together with artifact bytes.
    while budget.metadata_limit:
        expired = session.execute(
            select(grant.id, logical_payload_size(grants_table, columns).label("size"))
            .where(inactive)
            .order_by(grant.id)
            .limit(budget.metadata_limit)
            .with_for_update()
        ).all()
        if not budget.inspect(rows=len(expired)):
            return False
        if not expired:
            break
        identifiers = budget.reserve_clear_batch(
            tuple(PayloadCopyCost(row_id=row.id, payload_bytes=row.size) for row in expired)
        )
        if identifiers:
            session.execute(delete(grant).where(inactive, grant.id.in_(identifiers)))
        if len(identifiers) != len(expired):
            return False
    if budget.metadata_limit < 12:
        return False
    grants = session.execute(
        select(grant.id, logical_payload_size(grants_table, columns).label("size"))
        .where(grant.owner_id == owner, parent == identifier)
        .order_by(grant.id)
        .limit(11)
        .with_for_update()
    ).all()
    if not budget.inspect(rows=len(grants)):
        return False
    # The extra bounded row detects a broken active-token capacity invariant.
    if len(grants) > 10:
        return False
    costs = tuple(PayloadCopyCost(row_id=row.id, payload_bytes=row.size) for row in grants)
    costs += (PayloadCopyCost(row_id=identifier, payload_bytes=metadata.byte_length),)
    if len(costs) > min(budget.rows_inspected, budget.rows_removed) or sum(
        cost.payload_bytes for cost in costs
    ) > min(budget.bytes_inspected, budget.bytes_removed):
        return False
    ids = budget.reserve_clear_batch(costs)
    if len(ids) != len(costs):
        raise RuntimeError("Report artifact clearing lost its reserved budget.")
    if grants:
        session.execute(
            delete(grant).where(
                grant.owner_id == owner, grant.id.in_(tuple(row.id for row in grants))
            )
        )
    session.execute(
        update(table)
        .where(table.c.owner_id == owner, table.c.id == identifier, table.c.purged_at.is_(None))
        .values(contents=None, purged_at=at)
    )
    budget.artifacts -= 1
    return True


def purge_report_input(
    session: Session,
    *,
    owner: UUID,
    input_id: UUID,
    reason: Literal["ttl", "source", "owner"],
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    if budget.metadata_limit < 2:
        return False
    row = session.execute(
        select(
            ReportInputSnapshotModel.id,
            ReportInputSnapshotModel.kind,
            ReportInputSnapshotModel.account_id,
            ReportInputSnapshotModel.purged_at,
        )
        .where(ReportInputSnapshotModel.id == input_id, ReportInputSnapshotModel.owner_id == owner)
        .with_for_update()
    ).first()
    if row is None:
        return True
    if not budget.inspect(rows=1):
        return False
    family = cast(Literal["report", "export"], row.kind)
    if not budget.enter_capture(family, input_id):
        return False
    work = session.scalar(
        select(ReportRetentionWorkModel)
        .where(
            ReportRetentionWorkModel.owner_id == owner,
            ReportRetentionWorkModel.input_id == input_id,
        )
        .with_for_update()
    )
    if work is not None and not budget.inspect(rows=1):
        return False
    if work is None:
        work = ReportRetentionWorkModel(
            id=uuid4(),
            owner_id=owner,
            input_id=input_id,
            created_at=at,
            started_at=at,
            reason=reason,
            completed_at=None,
        )
        session.add(work)
        session.flush()
    if work.completed_at is not None:
        return True
    for job_model, outbox_model, artifact_model, manifest_model in (
        (ReportJobModel, ReportDispatchOutboxModel, ReportArtifactModel, ReportManifestModel),
        (ExportJobModel, ExportDispatchOutboxModel, ExportArtifactModel, ExportManifestModel),
    ):
        if not budget.metadata_limit:
            return False
        jobs = tuple(
            session.scalars(
                select(job_model)
                .where(job_model.owner_id == owner, job_model.input_id == input_id)
                .order_by(job_model.id)
                .limit(min(100, budget.metadata_limit))
                .with_for_update()
            )
        )
        if not budget.inspect(rows=len(jobs)):
            return False
        for job in jobs:
            if not budget.enter_run(family, job.id):
                return False
            if job.state not in {"expired", "cancelled"}:
                job.state = "expired"
                audit_report_job(
                    session,
                    cast(ReportJobModel | ExportJobModel, job),
                    event="expired",
                    at=at,
                )
                job.lease_id = None
                job.lease_expires_at = None
                job.consumer_id = None
                session.execute(
                    update(outbox_model)
                    .where(outbox_model.owner_id == owner, outbox_model.job_id == job.id)
                    .values(
                        state="dead_letter",
                        claim_token=None,
                        claim_expires_at=None,
                        dispatcher_id=None,
                    )
                )
                session.flush()
            while budget.metadata_limit:
                artifact = session.scalar(
                    select(artifact_model.id)
                    .where(
                        artifact_model.owner_id == owner,
                        artifact_model.job_id == job.id,
                        artifact_model.purged_at.is_(None),
                    )
                    .order_by(artifact_model.id)
                    .limit(1)
                )
                if artifact is None:
                    break
                if not budget.inspect(rows=1) or not _artifact(
                    session,
                    owner,
                    artifact,
                    export=artifact_model is ExportArtifactModel,
                    at=at,
                    budget=budget,
                ):
                    return False
            if not budget.metadata_limit:
                return False
            table = cast(Table, manifest_model.__table__)
            if not _clear_payloads(
                session,
                table,
                (table.c.owner_id == owner) & (table.c.job_id == job.id),
                columns=("payload",),
                at=at,
                budget=budget,
            ):
                return False
    chunks = cast(Table, ReportInputChunkModel.__table__)
    if not _clear_payloads(
        session,
        chunks,
        (chunks.c.owner_id == owner) & (chunks.c.input_id == input_id),
        columns=("payload",),
        at=at,
        budget=budget,
    ):
        return False
    inputs = cast(Table, ReportInputSnapshotModel.__table__)
    if not _clear_payloads(
        session,
        inputs,
        (inputs.c.owner_id == owner) & (inputs.c.id == input_id),
        columns=("canonical_manifest", "canonical_context"),
        at=at,
        budget=budget,
    ):
        return False
    work.completed_at = at
    audit_report_purge(
        session,
        owner_id=owner,
        account_id=row.account_id,
        input_id=input_id,
        family=family,
        reason=cast(Literal["ttl", "source", "owner"], work.reason),
        at=at,
    )
    session.flush()
    return True


def purge_report_source_copies(
    session: Session,
    *,
    owner: UUID,
    kind: str,
    source_id: UUID,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    dependency = ReportInputDependencyModel
    capture = ReportInputSnapshotModel
    while budget.metadata_limit >= 2:
        candidate = session.scalar(
            select(capture.id)
            .join(dependency, dependency.input_id == capture.id)
            .where(
                capture.owner_id == owner,
                dependency.owner_id == owner,
                dependency.kind == kind,
                dependency.source_id == source_id,
                capture.purged_at.is_(None),
            )
            .order_by(capture.id)
            .limit(1)
        )
        if candidate is None:
            return True
        if not budget.inspect(rows=2) or not purge_report_input(
            session, owner=owner, input_id=candidate, reason="source", at=at, budget=budget
        ):
            return False
    return False


def purge_report_premium_copies(
    session: Session,
    owner: UUID,
    run_id: UUID,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    """Drain retained run copies before the caller clears any premium payload.

    The caller holds the existing source/family owner locks and has inserted the
    premium retention marker. That marker denies reads immediately, even when
    this shared invocation budget cannot yet finish the report artifacts.
    """
    capture = ReportInputSnapshotModel
    dependency = ReportInputPremiumDependencyModel
    while budget.metadata_limit >= 2:
        identifier = session.scalar(
            select(capture.id)
            .join(
                dependency,
                (dependency.input_id == capture.id) & (dependency.owner_id == capture.owner_id),
            )
            .where(
                capture.owner_id == owner,
                dependency.run_id == run_id,
                capture.purged_at.is_(None),
            )
            .order_by(capture.id)
            .limit(1)
        )
        if identifier is None:
            return True
        if not budget.inspect(rows=2) or not purge_report_input(
            session, owner=owner, input_id=identifier, reason="source", at=at, budget=budget
        ):
            return False
    return False


def expire_report_payloads(
    session: Session, *, at: datetime, limit: int = 100, budget: SourcePurgeBudget | None = None
) -> int:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Report expiry is bounded to one hundred artifacts.")
    budget = budget or SourcePurgeBudget(artifacts=limit)
    completed = 0
    while budget.metadata_limit >= 2 and completed < 100:
        row = session.execute(
            select(
                ReportInputSnapshotModel.id,
                ReportInputSnapshotModel.owner_id,
                ReportInputSnapshotModel.expires_at,
            )
            .where(
                or_(
                    ReportInputSnapshotModel.expires_at <= at,
                    (ReportInputSnapshotModel.contract_version == 2)
                    & or_(
                        func.report_premium_restricted(
                            ReportInputSnapshotModel.owner_id, ReportInputSnapshotModel.id, at
                        ),
                        select(ReportRetentionWorkModel.id)
                        .where(
                            ReportRetentionWorkModel.owner_id == ReportInputSnapshotModel.owner_id,
                            ReportRetentionWorkModel.input_id == ReportInputSnapshotModel.id,
                            ReportRetentionWorkModel.completed_at.is_(None),
                        )
                        .exists(),
                    ),
                ),
                ReportInputSnapshotModel.purged_at.is_(None),
            )
            .order_by(ReportInputSnapshotModel.expires_at, ReportInputSnapshotModel.id)
            .limit(1)
        ).first()
        if row is None:
            break
        if not budget.inspect(rows=1) or not report_owner_lock(session, row.owner_id, wait=False):
            break
        if not purge_report_input(
            session,
            owner=row.owner_id,
            input_id=row.id,
            reason="ttl" if row.expires_at <= at else "source",
            at=at,
            budget=budget,
        ):
            break
        completed += 1
    return completed
