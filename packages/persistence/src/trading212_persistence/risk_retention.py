"""Resumable physical risk expiry under the existing shared source purge budget.

Only fixed ORM participants are used. License lineage contains identities, not
licensed values; cleanup neither decodes a result nor fetches an external source.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, and_, literal, or_, select, text
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from .risk_models import (
    RiskComponentModel,
    RiskIntervalModel,
    RiskMatrixCellModel,
    RiskMetricModel,
    RiskResultModel,
    RiskRunAssetModel,
    RiskSeriesModel,
)
from .source_models import ProviderLicenseVersionModel
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

# Child references are removed before series; the canonical blob is cleared last.
RISK_PAYLOADS = (
    (
        RiskIntervalModel,
        ("series_id", "ordinal", "start_at", "end_at", "simple_return", "quality", "reason"),
    ),
    (RiskMatrixCellModel, ("kind", "row_series_id", "column_series_id", "value", "reason")),
    (RiskMetricModel, ("key", "ordinal", "at", "value", "reason")),
    (
        RiskComponentModel,
        (
            "instrument_id",
            "weight",
            "weight_reason",
            "marginal",
            "marginal_reason",
            "component",
            "component_reason",
        ),
    ),
    (RiskSeriesModel, ("series_key", "kind", "instrument_id", "interval_count")),
)


def _charge(budget: SourcePurgeBudget, rows: int) -> None:
    if not budget.inspect(rows=rows):
        raise RuntimeError("Risk retention exceeded its metadata allowance.")


def _complete() -> ColumnElement[bool]:
    return (
        select(PremiumRetentionModel.id)
        .where(
            PremiumRetentionModel.owner_id == PremiumRunModel.owner_id,
            PremiumRetentionModel.run_id == PremiumRunModel.id,
            PremiumRetentionModel.completed_at.is_not(None),
        )
        .exists()
    )


def _eligible(at: datetime) -> ColumnElement[bool]:
    lineage = PremiumRunLicenseModel
    current = aliased(ProviderLicenseVersionModel)
    latest = aliased(ProviderLicenseVersionModel)
    latest_id = (
        select(latest.id)
        .where(
            latest.owner_id == lineage.owner_id,
            latest.provider_id == lineage.provider_id,
            latest.effective_at <= at,
        )
        .order_by(latest.effective_at.desc(), latest.version_number.desc(), latest.id.desc())
        .limit(1)
        .correlate(lineage)
        .scalar_subquery()
    )
    permitted = (
        select(current.id)
        .where(
            current.id == latest_id,
            current.owner_id == lineage.owner_id,
            current.store_permission == "allowed",
            current.display_permission == "allowed",
            current.retention_days.is_not(None),
            PremiumRunModel.created_at + current.retention_days * literal(timedelta(days=1)) > at,
        )
        .correlate(lineage, PremiumRunModel)
        .exists()
    )
    restricted = (
        select(lineage.id)
        .where(
            lineage.owner_id == PremiumRunModel.owner_id,
            lineage.run_id == PremiumRunModel.id,
            ~permitted,
        )
        .exists()
    )
    pending = (
        select(PremiumRetentionModel.id)
        .where(
            PremiumRetentionModel.owner_id == PremiumRunModel.owner_id,
            PremiumRetentionModel.run_id == PremiumRunModel.id,
            PremiumRetentionModel.completed_at.is_(None),
        )
        .exists()
    )
    return and_(
        PremiumRunModel.kind == "risk",
        ~_complete(),
        or_(
            PremiumRunModel.expires_at <= at,
            pending,
            restricted,
        ),
    )


def _lock_owner(session: Session, owner: UUID) -> bool:
    # No execution-slot lock: a worker holds that lock before these owner locks.
    return all(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )
        is True
        for namespace in ("sources", "xray", "historical", "premium")
    )


def _purge_run(
    session: Session, root: PremiumRunModel, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    if not budget.enter_run("risk", root.id) or budget.metadata_limit < 7:
        return False
    marker = session.scalar(
        select(PremiumRetentionModel).where(
            PremiumRetentionModel.owner_id == root.owner_id,
            PremiumRetentionModel.run_id == root.id,
        )
    )
    if marker is not None:
        _charge(budget, 1)
        if marker.completed_at is not None:
            return True
    else:
        marker = PremiumRetentionModel(
            id=uuid4(),
            owner_id=root.owner_id,
            account_id=root.account_id,
            run_id=root.id,
            reason="run_expired" if root.expires_at <= at else "source_restricted",
            created_at=at,
        )
        session.add(marker)
        session.flush()
    job = session.scalar(
        select(PremiumJobModel)
        .where(
            PremiumJobModel.owner_id == root.owner_id,
            PremiumJobModel.run_id == root.id,
        )
        .with_for_update()
    )
    capacity = session.scalar(
        select(PremiumCapacityModel)
        .where(
            PremiumCapacityModel.owner_id == root.owner_id,
        )
        .with_for_update()
    )
    if job is None or capacity is None:
        raise RuntimeError("Risk retention authority is incomplete.")
    _charge(budget, 2)
    if job.state in ("queued", "running"):
        # Fence publication immediately. Byte reservations remain charged until
        # every payload row is physically gone, even across cleanup invocations.
        _charge(budget, 1)
        premium_attempt(
            session,
            job,
            kind="consumer",
            event="expired",
            number=job.consumer_attempts,
            token=job.lease_token,
            at=at,
            failure="source_restricted",
        )
        job.state = "expired"
        job.failure_code = "source_restricted"
        job.completed_at = at
        job.lease_token = job.lease_expires_at = job.heartbeat_at = job.deadline_at = (
            job.consumer_id
        ) = None
        capacity.active_jobs -= 1
        capacity.updated_at = at
        outbox = session.scalar(
            select(PremiumOutboxModel)
            .where(
                PremiumOutboxModel.owner_id == root.owner_id,
                PremiumOutboxModel.job_id == job.id,
            )
            .with_for_update()
        )
        if outbox is None:
            raise RuntimeError("Risk retention dispatch identity is missing.")
        _charge(budget, 1)
        outbox.state = "dead_letter"
        outbox.failure_code = "source_restricted"
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        session.flush()
    result_id = session.scalar(
        select(RiskResultModel.id).where(
            RiskResultModel.owner_id == root.owner_id,
            RiskResultModel.run_id == root.id,
        )
    )
    if result_id is not None:
        _charge(budget, 1)
        for model, columns in RISK_PAYLOADS:
            table = cast(Table, model.__table__)
            if not purge_payload_rows(
                session,
                table,
                (table.c.owner_id == root.owner_id) & (table.c.result_id == result_id),
                payload_columns=columns,
                delete_rows=True,
                budget=budget,
            ).complete:
                return False
    assets = cast(Table, RiskRunAssetModel.__table__)
    if not purge_payload_rows(
        session,
        assets,
        (assets.c.owner_id == root.owner_id) & (assets.c.run_id == root.id),
        payload_columns=("ordinal", "instrument_id", "source_series_id"),
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    if result_id is not None:
        result = cast(Table, RiskResultModel.__table__)
        if not purge_payload_rows(
            session,
            result,
            (result.c.owner_id == root.owner_id) & (result.c.id == result_id),
            payload_columns=("canonical_result",),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
    capacity.reserved_bytes -= root.reserved_bytes
    capacity.retained_bytes -= root.retained_bytes
    capacity.updated_at = at
    root.reserved_bytes = root.retained_bytes = 0
    marker.completed_at = at
    session.flush()
    return True


def expire_risk_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget, owner: UUID | None = None
) -> bool:
    """True only if no eligible risk run remains in the requested scope.

    Sources call this before dropping their copies. Independent dispatch also
    calls it for current license revocation/tightening and ordinary run expiry.
    Busy owners are skipped with nonblocking locks; incomplete work stays indexed.
    """
    busy: set[UUID] = set()
    after: UUID | None = None
    while budget.metadata_limit >= 2:
        query = select(PremiumRunModel.id, PremiumRunModel.owner_id).where(_eligible(at))
        if owner is not None:
            query = query.where(PremiumRunModel.owner_id == owner)
        if busy:
            query = query.where(PremiumRunModel.owner_id.not_in(busy))
        if after is not None:
            query = query.where(PremiumRunModel.id > after)
        candidate = session.execute(query.order_by(PremiumRunModel.id).limit(1)).first()
        if candidate is None:
            return not busy
        _charge(budget, 1)
        after = candidate.id
        if not _lock_owner(session, candidate.owner_id):
            busy.add(candidate.owner_id)
            continue
        root = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == candidate.id,
                PremiumRunModel.owner_id == candidate.owner_id,
                _eligible(at),
            )
            .with_for_update(skip_locked=True)
        )
        if root is None:
            busy.add(candidate.owner_id)
            continue
        _charge(budget, 1)
        if not _purge_run(session, root, at=at, budget=budget):
            return False
    return False
