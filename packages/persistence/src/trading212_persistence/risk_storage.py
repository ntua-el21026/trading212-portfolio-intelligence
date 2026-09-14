"""Fixed risk projections; callers authorize sources and own the publication transaction."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from sqlalchemy import insert, select
from sqlalchemy.orm import Session
from trading212_domain.risk import RiskMetric
from trading212_domain.risk_result import RiskCalculation
from trading212_domain.risk_serialization import canonical_risk_bytes, risk_result_from_json
from trading212_domain.serialization import canonical_json

from .premium_models import PremiumOwned
from .risk_models import (
    RiskComponentModel,
    RiskIntervalModel,
    RiskMatrixCellModel,
    RiskMetricModel,
    RiskResultModel,
    RiskRunModel,
    RiskSeriesModel,
)


class RiskIntegrityError(Exception):
    def __str__(self) -> str:
        return "The retained risk result is unavailable."


_RESULT_MODELS = (
    RiskSeriesModel,
    RiskIntervalModel,
    RiskMatrixCellModel,
    RiskMetricModel,
    RiskComponentModel,
)
_FIELDS: dict[type[PremiumOwned], tuple[str, ...]] = {
    model: tuple(
        column.name
        for column in model.__table__.columns
        if column.name not in {"created_at", "owner_id", "account_id", "result_id"}
    )
    for model in _RESULT_MODELS
}
_LIMITS = {
    RiskSeriesModel: 34,
    RiskIntervalModel: 100000,
    RiskMatrixCellModel: 3072,
    RiskMetricModel: 8192,
    RiskComponentModel: 32,
}


def _pair(metric: RiskMetric, name: str = "value", reason: str = "reason") -> dict[str, object]:
    return {name: metric.value, reason: None if metric.reason is None else metric.reason.value}


def normalized_risk_rows(
    value: RiskCalculation,
    result_id: UUID,
) -> dict[type[PremiumOwned], list[dict[str, object]]]:
    """Project only this closed result schema, with stable child identities per result."""
    rows: dict[type[PremiumOwned], list[dict[str, object]]] = {m: [] for m in _RESULT_MODELS}

    def append(model: type[PremiumOwned], key: str, fields: dict[str, object]) -> None:
        rows[model].append({"id": uuid5(result_id, model.__tablename__ + ":" + key), **fields})

    series = (
        value.history.portfolio,
        *value.history.assets,
        *((value.history.benchmark,) if value.history.benchmark else ()),
    )
    series_ids = {s.key: uuid5(result_id, "risk_series:" + s.key) for s in series}
    for s in series:
        kind = s.key if s.key in ("portfolio", "benchmark") else "asset"
        append(
            RiskSeriesModel,
            s.key,
            {
                "series_key": s.key,
                "kind": kind,
                "instrument_id": UUID(s.key) if kind == "asset" else None,
                "interval_count": len(s.intervals),
            },
        )
        for ordinal, interval in enumerate(s.intervals):
            append(
                RiskIntervalModel,
                f"{s.key}:{ordinal}",
                {
                    "series_id": series_ids[s.key],
                    "ordinal": ordinal,
                    "start_at": interval.start_at,
                    "end_at": interval.end_at,
                    "simple_return": interval.simple_return,
                    "quality": interval.quality.value,
                    "reason": None if interval.reason is None else interval.reason.value,
                },
            )
    for kind, matrix in (
        ("covariance", value.matrix.covariance_periodic),
        ("regularized_covariance", value.matrix.regularized_covariance_periodic),
        ("correlation", value.matrix.correlation),
    ):
        for i, key in enumerate(value.matrix.keys):
            for j, column in enumerate(value.matrix.keys):
                append(
                    RiskMatrixCellModel,
                    f"{kind}:{key}:{column}",
                    {
                        "kind": kind,
                        "row_series_id": series_ids[key],
                        "column_series_id": series_ids[column],
                        **_pair(matrix[i][j]),
                    },
                )

    def metric(key: str, item: RiskMetric, ordinal: int = 0, at: datetime | None = None) -> None:
        append(
            RiskMetricModel,
            f"{key}:{ordinal}",
            {
                "key": key,
                "ordinal": ordinal,
                "at": at,
                **_pair(item),
            },
        )

    for key in (
        "mean_periodic_return",
        "volatility_periodic",
        "volatility_annualized",
        "downside_annualized",
        "beta",
        "alpha_annualized",
    ):
        metric("observed." + key, getattr(value.observed, key))
    for ordinal, point in enumerate(value.observed.rolling):
        metric("observed.rolling_volatility", point.volatility, ordinal, point.end_at)
    # The canonical historical metric also retains partial-value warnings/quality.
    # Preserve those reasons here: historical availability differs from RiskMetric.
    drawdown = value.history.maximum_drawdown
    append(
        RiskMetricModel,
        "observed.maximum_drawdown:0",
        {
            "key": "observed.maximum_drawdown",
            "ordinal": 0,
            "at": None,
            "value": drawdown.value,
            "reason": None if drawdown.reason_code is None else drawdown.reason_code.value,
        },
    )
    for name, tail in (
        ("historical_tail", value.historical_tail),
        ("parametric_tail", value.parametric_tail),
    ):
        metric(name + ".value_at_risk", tail.value_at_risk)
        metric(name + ".expected_shortfall", tail.expected_shortfall)
    for key in (
        "coverage",
        "volatility_annualized",
        "diversification_ratio",
        "component_sum",
        "component_display_residual",
        "weight_display_residual",
    ):
        metric("modeled." + key, getattr(value.modeled, key))
    for key in (
        "hhi",
        "effective_holdings",
        "company_known_weight",
        "cash_weight",
        "unresolved_weight",
    ):
        metric("concentration." + key, getattr(value.concentration, key))
    for component in value.modeled.components:
        append(
            RiskComponentModel,
            component.instrument_id,
            {
                "instrument_id": UUID(component.instrument_id),
                **_pair(component.weight, "weight", "weight_reason"),
                **_pair(component.marginal_annualized, "marginal", "marginal_reason"),
                **_pair(component.component_annualized, "component", "component_reason"),
            },
        )
    if any(len(items) > _LIMITS[model] for model, items in rows.items()):
        raise RiskIntegrityError()
    return rows


def _bind(run: RiskRunModel, value: RiskCalculation) -> None:
    window = value.history.canonical_performance_context.window
    if (
        not run.sealed
        or (
            value.history.owner_id,
            value.history.account_id,
            value.history.historical_input_digest,
            window.start_at,
            window.end_at,
            window.source_cutoff_at,
            window.reporting_currency.value,
        )
        != (
            str(run.owner_id),
            str(run.account_id),
            run.historical_input_digest,
            run.window_start_at,
            run.window_end_at,
            run.source_cutoff_at,
            run.reporting_currency,
        )
        or (
            value.portfolio_snapshot_id is not None
            and value.portfolio_snapshot_id != str(run.portfolio_snapshot_id)
        )
    ):
        raise RiskIntegrityError()


def persist_risk_result(
    session: Session,
    run: RiskRunModel,
    value: RiskCalculation,
    *,
    at: datetime,
) -> RiskResultModel:
    _bind(run, value)
    payload = canonical_risk_bytes(value)
    result_id = uuid4()
    rows = normalized_risk_rows(value, result_id)
    result = RiskResultModel(
        id=result_id,
        owner_id=run.owner_id,
        account_id=run.account_id,
        run_id=run.id,
        created_at=at,
        content_digest=sha256(payload).hexdigest(),
        canonical_result=payload,
        sealed=False,
        series_count=len(rows[RiskSeriesModel]),
        interval_count=len(rows[RiskIntervalModel]),
        matrix_cell_count=len(rows[RiskMatrixCellModel]),
        metric_count=len(rows[RiskMetricModel]),
        component_count=len(rows[RiskComponentModel]),
    )
    session.add(result)
    session.flush()
    common = {
        "owner_id": run.owner_id,
        "account_id": run.account_id,
        "result_id": result_id,
        "created_at": at,
    }
    # Ordered parent-first batches keep both SQL parameter counts and ORM residency bounded.
    for model, items in rows.items():
        for start in range(0, len(items), 500):
            session.execute(
                insert(model), [{**common, **item} for item in items[start : start + 500]]
            )
    result.sealed = True
    session.flush()
    return result


def verify_risk_result(
    session: Session,
    run: RiskRunModel,
    row: RiskResultModel,
) -> RiskCalculation:
    """Only invoke after current identity, source and retention checks, before projection."""
    if (
        not row.sealed
        or row.run_id != run.id
        or row.owner_id != run.owner_id
        or row.account_id != run.account_id
    ):
        raise RiskIntegrityError()
    value = risk_result_from_json(row.canonical_result, expected_digest=row.content_digest)
    _bind(run, value)
    expected = normalized_risk_rows(value, row.id)
    for model, items in expected.items():
        records = (
            session.execute(
                select(*(getattr(model, key) for key in _FIELDS[model]))
                .where(
                    model.owner_id == run.owner_id,
                    model.account_id == run.account_id,
                    model.__table__.c.result_id == row.id,
                )
                .limit(_LIMITS[model] + 1)
            )
            .mappings()
            .all()
        )
        if sorted((dict(record) for record in records), key=canonical_json) != sorted(
            items, key=canonical_json
        ):
            raise RiskIntegrityError()
    counts = (
        row.series_count,
        row.interval_count,
        row.matrix_cell_count,
        row.metric_count,
        row.component_count,
    )
    if counts != tuple(len(expected[m]) for m in _RESULT_MODELS):
        raise RiskIntegrityError()
    return value
