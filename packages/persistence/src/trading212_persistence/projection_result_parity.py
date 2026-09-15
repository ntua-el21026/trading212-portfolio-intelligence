"""Bounded exact insertion/comparison for closed projection row families."""

from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from itertools import islice
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, insert, select
from sqlalchemy.orm import Session
from trading212_application.projection import ProjectionErrorCode

from . import projection_models as m
from .projection_definition_store import ProjectionStorageError
from .projection_result_rows import ProjectionChunkRows, ProjectionResultRows

PROJECTION_ROW_BATCH = 256
_CHUNK_MODELS = (m.ProjectionPathModel, m.ProjectionPointModel, m.ProjectionPointAssetModel)
_RESULT_MODELS = (
    m.ProjectionZeroPivotModel,
    m.ProjectionDistributionModel,
    m.ProjectionDistributionQuantileModel,
    m.ProjectionHistogramModel,
    m.ProjectionHistogramBinModel,
    m.ProjectionGoalAnalysisModel,
    m.ProjectionGoalShortfallQuantileModel,
)


def _batches(rows: Iterable[dict[str, object]]) -> Iterator[tuple[dict[str, object], ...]]:
    iterator = iter(rows)
    while batch := tuple(islice(iterator, PROJECTION_ROW_BATCH)):
        yield batch


def _scoped(model: Any, owner: UUID, account: UUID, root: UUID, child: UUID) -> Select[Any]:
    if model not in (*_CHUNK_MODELS, *_RESULT_MODELS):
        raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
    statement = select(model.id).where(model.owner_id == owner, model.account_id == account)
    if model is m.ProjectionPathModel:
        return statement.where(model.run_id == root, model.chunk_id == child)
    if model is m.ProjectionPointModel:
        return statement.join(
            m.ProjectionPathModel, model.path_id == m.ProjectionPathModel.id
        ).where(model.run_id == root, m.ProjectionPathModel.chunk_id == child)
    if model is m.ProjectionPointAssetModel:
        return (
            statement.join(m.ProjectionPointModel, model.point_id == m.ProjectionPointModel.id)
            .join(m.ProjectionPathModel, m.ProjectionPointModel.path_id == m.ProjectionPathModel.id)
            .where(model.run_id == root, m.ProjectionPathModel.chunk_id == child)
        )
    if model is m.ProjectionDistributionQuantileModel:
        return statement.join(
            m.ProjectionDistributionModel, model.distribution_id == m.ProjectionDistributionModel.id
        ).where(m.ProjectionDistributionModel.result_id == child)
    if model is m.ProjectionHistogramBinModel:
        return statement.join(
            m.ProjectionHistogramModel, model.histogram_id == m.ProjectionHistogramModel.id
        ).where(m.ProjectionHistogramModel.result_id == child)
    if model is m.ProjectionGoalShortfallQuantileModel:
        return statement.join(
            m.ProjectionGoalAnalysisModel, model.analysis_id == m.ProjectionGoalAnalysisModel.id
        ).where(m.ProjectionGoalAnalysisModel.result_id == child)
    return statement.where(model.result_id == child)


def _rows(
    session: Session,
    model: Any,
    rows: Iterable[dict[str, object]],
    *,
    owner: UUID,
    account: UUID,
    root: UUID,
    child: UUID,
    created_at: datetime,
    publish: bool,
    boundary: Callable[[], None],
) -> None:
    scope = _scoped(model, owner, account, root, child)
    columns = tuple(model.__table__.columns)
    names = frozenset(column.name for column in columns)
    expected_count = 0
    for raw_batch in _batches(rows):
        boundary()
        batch = tuple(
            dict(row, owner_id=owner, account_id=account, created_at=created_at)
            for row in raw_batch
        )
        if any(frozenset(row) != names for row in batch):
            raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        identifiers = tuple(row["id"] for row in batch)
        if len(set(identifiers)) != len(batch):
            raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        if publish:
            session.execute(insert(model), list(batch))
        # Read scalar columns, never accumulating ORM instances or all financial rows.
        actual = tuple(
            session.execute(
                select(*columns)
                .where(model.id.in_(identifiers), model.id.in_(scope))
                .limit(PROJECTION_ROW_BATCH + 1)
            ).mappings()
        )
        expected = {row["id"]: row for row in batch}
        if len(actual) != len(batch) or any(dict(row) != expected.get(row["id"]) for row in actual):
            raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        expected_count += len(batch)
    boundary()
    actual_count = session.scalar(select(func.count()).select_from(scope.subquery()))
    if actual_count != expected_count:
        raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)


def reconcile_chunk_rows(
    session: Session,
    value: ProjectionChunkRows,
    *,
    owner: UUID,
    account: UUID,
    created_at: datetime,
    publish: bool,
    boundary: Callable[[], None],
) -> None:
    for model, rows in zip(
        _CHUNK_MODELS, (value.paths(), value.points(), value.assets()), strict=True
    ):
        _rows(
            session,
            model,
            rows,
            owner=owner,
            account=account,
            root=value.run_id,
            child=value.chunk_id,
            created_at=created_at,
            publish=publish,
            boundary=boundary,
        )


def reconcile_result_rows(
    session: Session,
    value: ProjectionResultRows,
    *,
    owner: UUID,
    account: UUID,
    root: UUID,
    created_at: datetime,
    publish: bool,
    boundary: Callable[[], None],
) -> None:
    iterators = (
        value.pivots(),
        value.distributions(),
        value.distribution_quantiles(),
        value.histograms(),
        value.histogram_bins(),
        value.goals(),
        value.goal_quantiles(),
    )
    for model, rows in zip(_RESULT_MODELS, iterators, strict=True):
        _rows(
            session,
            model,
            rows,
            owner=owner,
            account=account,
            root=root,
            child=value.result_id,
            created_at=created_at,
            publish=publish,
            boundary=boundary,
        )
