"""Canonical risk calculation from retained history and the same-scope X-ray basis."""

from __future__ import annotations

from decimal import Decimal

from trading212_domain.enums import QualityState
from trading212_domain.historical import HistoricalInput
from trading212_domain.historical_serialization import historical_canonical_bytes
from trading212_domain.risk import RiskDefinitionContent, RiskMetric, RiskReason
from trading212_domain.risk_history import RiskAssetSource, RiskHistory
from trading212_domain.risk_result import (
    RiskCalculation,
    RiskComponent,
    RiskConcentration,
    RiskMatrix,
    RiskModel,
    RiskTail,
)
from trading212_domain.xray import XrayBound, XrayDimension, XrayRatioMetric
from trading212_domain.xray_result import XrayCalculation

from ._premium_numeric import (
    ONE,
    ZERO,
    Matrix,
    arithmetic,
    correlations,
    invalid,
    modeled_risk_from_values,
    q18,
    sample_covariance,
    semidefinite_factor,
    shrink_covariance,
)
from ._premium_tails import TailEstimate, historical_tail, parametric_tail
from .risk_history import build_risk_history
from .risk_statistics import align_series, calculate_risk_statistics


def _metric(
    value: Decimal | None, reason: RiskReason = RiskReason.INSUFFICIENT_HISTORY
) -> RiskMetric:
    return (
        RiskMetric(value=q18(value)) if value is not None else RiskMetric(value=None, reason=reason)
    )


def _matrix(
    history: RiskHistory, definition: RiskDefinitionContent
) -> tuple[RiskMatrix, Matrix | None]:
    if not history.assets:
        return RiskMatrix(
            keys=(),
            requested_intervals=0,
            used_intervals=0,
            omitted_intervals=0,
            covariance_periodic=(),
            regularized_covariance_periodic=(),
            correlation=(),
            numerical_zero_pivots=(),
        ), None
    aligned = align_series(history.assets, definition.return_kind)
    count = len(aligned.boundaries)
    original = sample_covariance(aligned.values) if count >= 20 else None
    model = shrink_covariance(original, definition.shrinkage) if original is not None else None
    correlation = correlations(model) if model is not None else None
    missing = tuple(tuple(_metric(None) for _ in aligned.keys) for _ in aligned.keys)
    return RiskMatrix(
        keys=aligned.keys,
        requested_intervals=aligned.requested_intervals,
        used_intervals=count,
        omitted_intervals=aligned.omitted_intervals,
        covariance_periodic=tuple(tuple(_metric(cell) for cell in row) for row in original)
        if original is not None
        else missing,
        regularized_covariance_periodic=tuple(tuple(_metric(cell) for cell in row) for row in model)
        if model is not None
        else missing,
        correlation=tuple(
            tuple(_metric(cell, RiskReason.ZERO_DENOMINATOR) for cell in row) for row in correlation
        )
        if correlation is not None
        else missing,
        numerical_zero_pivots=semidefinite_factor(model).numerical_zero_pivots
        if model is not None
        else (),
    ), model


def _tail(value: TailEstimate) -> RiskTail:
    reason = (
        RiskReason(value.reason) if value.reason is not None else RiskReason.INSUFFICIENT_HISTORY
    )
    return RiskTail(
        method=value.method,
        confidence=value.confidence,
        horizon=value.horizon,
        observations=value.observations,
        tail_mass=q18(value.tail_mass) if value.tail_mass is not None else None,
        value_at_risk=_metric(value.value_at_risk, reason),
        expected_shortfall=_metric(value.expected_shortfall, reason),
        quantile="nearest_rank_fractional_tail"
        if value.method == "historical"
        else "gaussian_log_wealth",
        horizon_policy="overlapping_compounded"
        if value.method == "historical"
        else "iid_log_returns",
    )


def _concentration(value: XrayCalculation | None) -> RiskConcentration:
    if value is None:
        missing = _metric(None, RiskReason.INCOMPLETE_UNIVERSE)
        return RiskConcentration(
            hhi=missing,
            effective_holdings=missing,
            company_known_weight=missing,
            cash_weight=missing,
            unresolved_weight=missing,
            lower_bound=True,
            quality=QualityState.PARTIAL,
        )
    summary = value.portfolio_summary

    def metric(item: XrayRatioMetric) -> RiskMetric:
        return _metric(
            item.value,
            RiskReason.ZERO_DENOMINATOR
            if item.reason is not None and item.reason.value == "zero_denominator"
            else RiskReason.INCOMPLETE_UNIVERSE,
        )

    company = next(item for item in value.dimensions if item.dimension is XrayDimension.COMPANY)
    partial = not company.complete or summary.hhi.bound is XrayBound.LOWER_BOUND
    effective = None
    reason = RiskReason.INCOMPLETE_UNIVERSE if partial else RiskReason.ZERO_DENOMINATOR
    # Reuse the verified integer coefficient ratio, not 1 divided by an already
    # rounded HHI. Tiny positive concentrations must not become zero denominators.
    with arithmetic():
        if (
            not partial
            and value.exact_state.hhi_coefficient > ZERO
            and value.exact_state.portfolio_square_coefficient is not None
        ):
            effective = (
                value.exact_state.portfolio_square_coefficient / value.exact_state.hhi_coefficient
            )
    return RiskConcentration(
        hhi=metric(summary.hhi),
        effective_holdings=_metric(effective, reason),
        company_known_weight=metric(summary.company_known_weight),
        cash_weight=metric(summary.cash_weight),
        unresolved_weight=metric(summary.unresolved_weight),
        lower_bound=partial,
        quality=summary.hhi.quality,
    )


def _model(
    keys: tuple[str, ...], matrix: Matrix | None, value: XrayCalculation | None, factor: int
) -> RiskModel:
    weights: dict[str, Decimal] = {}
    coverage = None
    complete = False
    if value is not None:
        roots = {row.root_key: row.money_coefficient for row in value.exact_state.roots}
        material = tuple(row for row in value.direct_positions if roots[row.root.key] != ZERO)
        # Missing or non-observed valuation cannot establish today's exact weights.
        trusted = (
            all(coefficient is not None for coefficient in roots.values())
            and all(row.reporting_value.quality is QualityState.FRESH for row in material)
            and value.portfolio_summary.total.quality is QualityState.FRESH
        )
        if trusted:
            values: dict[str, Decimal] = {}
            for row in material:
                coefficient = roots[row.root.key]
                assert coefficient is not None
                key = str(row.root.instrument_id)
                values[key] = values.get(key, ZERO) + coefficient
            total = sum(
                (coefficient for coefficient in roots.values() if coefficient is not None), ZERO
            )
            selected = sum((values.get(key, ZERO) for key in keys), ZERO)
            if total > ZERO:
                coverage = selected / total
                weights = {key: values.get(key, ZERO) / total for key in keys}
                complete = bool(keys) and selected == total and set(values) == set(keys)
    reason = RiskReason.INSUFFICIENT_HISTORY if complete else RiskReason.INCOMPLETE_UNIVERSE
    estimate = None
    if complete and matrix is not None:
        estimate = modeled_risk_from_values(matrix, tuple(values[key] for key in keys), factor)
        reason = RiskReason.ZERO_DENOMINATOR
    components = tuple(
        RiskComponent(
            instrument_id=key,
            weight=_metric(weights.get(key), RiskReason.INCOMPLETE_UNIVERSE),
            marginal_annualized=_metric(
                estimate.marginal[i] if estimate and estimate.marginal is not None else None, reason
            ),
            component_annualized=_metric(
                estimate.components[i] if estimate and estimate.components is not None else None,
                reason,
            ),
        )
        for i, key in enumerate(keys)
    )
    component_sum = (
        sum(
            (
                row.component_annualized.value
                for row in components
                if row.component_annualized.value is not None
            ),
            ZERO,
        )
        if estimate and estimate.components is not None
        else None
    )
    volatility = q18(estimate.volatility) if estimate else None
    return RiskModel(
        coverage=_metric(coverage, RiskReason.INCOMPLETE_UNIVERSE),
        complete_universe=complete,
        volatility_annualized=_metric(volatility, reason),
        diversification_ratio=_metric(estimate.diversification if estimate else None, reason),
        components=components,
        component_sum=_metric(component_sum, reason),
        component_display_residual=_metric(
            volatility - component_sum
            if volatility is not None and component_sum is not None
            else None,
            reason,
        ),
        weight_display_residual=_metric(
            ONE - sum((q18(weights[key]) for key in keys), ZERO) if complete else None,
            RiskReason.INCOMPLETE_UNIVERSE,
        ),
    )


def calculate_risk(
    value: HistoricalInput,
    definition: RiskDefinitionContent,
    *,
    assets: tuple[RiskAssetSource, ...] = (),
    xray: XrayCalculation | None = None,
) -> RiskCalculation:
    if not isinstance(value, HistoricalInput) or not isinstance(definition, RiskDefinitionContent):
        invalid("risk.input")
    if xray is not None:
        if not isinstance(xray, XrayCalculation) or (
            str(xray.owner_id),
            str(xray.account_id),
            xray.reporting_currency,
            xray.source_cutoff_at.value,
        ) != (
            value.owner_id,
            value.account_id,
            value.selection.window.reporting_currency,
            value.selection.window.source_cutoff_at,
        ):
            invalid("risk.xray.scope")
        # A selected X-ray capture may value current holdings after the historic
        # estimation window; its distinct valuation date is retained in the capture.
        if xray.valuation_at.value < value.selection.window.end_at:
            invalid("risk.xray.valuation")
    history = build_risk_history(value, definition, assets=assets)
    with arithmetic():
        matrix, covariance = _matrix(history, definition)
        simple = tuple(
            item.simple_return if item.quality is QualityState.FRESH else None
            for item in history.portfolio.intervals
        )
        logs = tuple(
            (ONE + item).ln() if item is not None and item > -ONE else None for item in simple
        )
        factor = 252 if definition.frequency == "daily" else 12
        result = RiskCalculation(
            history=history,
            definition=definition,
            observed=calculate_risk_statistics(
                history.portfolio, definition, benchmark=history.benchmark
            ),
            matrix=matrix,
            historical_tail=_tail(
                historical_tail(
                    simple, definition.confidence, definition.horizon, definition.frequency
                )
            ),
            parametric_tail=_tail(
                parametric_tail(
                    logs, definition.confidence, definition.horizon, definition.frequency
                )
            ),
            modeled=_model(matrix.keys, covariance, xray, factor),
            concentration=_concentration(xray),
            xray_result_digest=xray.content_digest if xray is not None else None,
            portfolio_snapshot_id=str(xray.snapshot_id) if xray is not None else None,
            modeled_valuation_at=xray.valuation_at.value if xray is not None else None,
            annualization_factor=factor,
        )
        historical_canonical_bytes(result)
        return result
