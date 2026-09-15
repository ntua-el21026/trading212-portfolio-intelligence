"""Indexed, resumable risk cleanup under the shared physical allowance."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from .premium_models import PremiumRunModel
from .premium_retention_runtime import (
    begin_run,
    charge,
    drain_parent,
    expire_runs,
    finish_run,
    lock_owner,
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
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

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
    charge(budget, rows)


def _lock_owner(session: Session, owner: UUID) -> bool:
    return lock_owner(session, owner)


def _purge_run(
    session: Session,
    root: PremiumRunModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    reason: Literal["run_expired", "source_restricted", "owner_erasure"] | None = None,
) -> bool:
    marker = begin_run(session, root, at, budget, reason=reason)
    if marker is None:
        return False
    if marker.completed_at is not None:
        return True
    if not budget.inspect(rows=1):
        return False
    result_id = session.scalar(
        select(RiskResultModel.id).where(
            RiskResultModel.owner_id == root.owner_id,
            RiskResultModel.run_id == root.id,
        )
    )
    if result_id is not None:
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
    return finish_run(session, root, marker, at, budget)


def expire_risk_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget, owner: UUID | None = None
) -> bool:
    return expire_runs(
        session,
        "risk",
        lambda session, root, at, budget: _purge_run(session, root, at=at, budget=budget),
        at=at,
        budget=budget,
        owner=owner,
    )


def purge_risk_xray_copies(
    session: Session, owner: UUID, input_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    return drain_parent(session, owner, "xray_input", input_id, at=at, budget=budget)


def purge_risk_historical_copies(
    session: Session, owner: UUID, input_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    return drain_parent(session, owner, "historical", input_id, at=at, budget=budget)
