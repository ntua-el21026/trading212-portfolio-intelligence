"""Closed six-dimensional aggregation and declared Q18 publication boundaries."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import (
    ConcentrationThresholdPolicy,
    XrayAvailability,
    XrayBound,
    XrayBrokerFx,
    XrayCash,
    XrayDependencyKind,
    XrayDimension,
    XrayFxLeg,
    XrayInput,
    XrayMoneyMetric,
    XrayPosition,
    XrayRatioMetric,
    XrayReason,
    XrayResidualKind,
    XrayWarningCode,
)
from trading212_domain.xray_codec import encode_xray_input
from trading212_domain.xray_result import (
    FundComposition,
    XrayBucketExact,
    XrayCalculation,
    XrayDimensionExact,
    XrayDimensionSummary,
    XrayDirectPosition,
    XrayDisplayResidual,
    XrayExactState,
    XrayExposureBucket,
    XrayFundEntity,
    XrayPathDimensionMetric,
    XrayPortfolioSummary,
    XrayQualityCoverage,
    XrayTerminalPath,
    XrayThresholdConclusion,
    XrayTopConcentration,
    XrayWarning,
)
from trading212_domain.xray_validation import invalid

from trading212_analytics._xray_decimal import (
    MONEY,
    UNIT,
    ZERO,
    arithmetic,
    coefficient18,
    path_relative,
    q18,
    residual,
    threshold,
)
from trading212_analytics._xray_graph import Graph, RawPath
from trading212_analytics._xray_sources import SourceIndex, confidence, quality


def money_metric(
    numerator: Decimal | None,
    currency: CurrencyCode,
    *,
    partial: bool = False,
    state: QualityState = QualityState.FRESH,
    certainty: Decimal | None = None,
    references: tuple[UUID, ...] = (),
    reason: XrayReason = XrayReason.INCOMPLETE_VALUATION,
) -> XrayMoneyMetric:
    return XrayMoneyMetric(
        None if numerator is None else Money(q18(numerator, MONEY), currency),
        reason if numerator is None else None,
        quality((state, QualityState.PARTIAL)) if partial or numerator is None else state,
        ValueOrigin.UNAVAILABLE if numerator is None else ValueOrigin.DERIVED_DETERMINISTIC,
        XrayBound.LOWER_BOUND if partial else XrayBound.EXACT,
        XrayAvailability.UNAVAILABLE if numerator is None else XrayAvailability.AVAILABLE,
        certainty,
        references,
    )


def ratio_metric(
    numerator: Decimal | None,
    denominator: Decimal | None,
    *,
    partial: bool = False,
    state: QualityState = QualityState.FRESH,
    certainty: Decimal | None = None,
    references: tuple[UUID, ...] = (),
    reason: XrayReason = XrayReason.INCOMPLETE_VALUATION,
) -> XrayRatioMetric:
    available = numerator is not None and denominator is not None and denominator > ZERO
    value = None
    if available:
        assert numerator is not None and denominator is not None
        value = q18(numerator, denominator)
    return XrayRatioMetric(
        value,
        None if available else (XrayReason.ZERO_DENOMINATOR if denominator == ZERO else reason),
        quality((state, QualityState.PARTIAL)) if partial or not available else state,
        XrayBound.LOWER_BOUND if partial else XrayBound.EXACT,
        XrayAvailability.AVAILABLE if available else XrayAvailability.UNAVAILABLE,
        certainty,
        references,
        numerator is not None and available and numerator > ZERO and value == ZERO,
    )


def bucket_key(path: RawPath | XrayTerminalPath, dimension: XrayDimension) -> str | None:
    if path.entity_id is None:
        return None
    if dimension is XrayDimension.COMPANY:
        return str(path.entity_id)
    return next(item.bucket_key for item in path.classifications if item.dimension is dimension)


def _refs(paths: tuple[RawPath, ...]) -> tuple[UUID, ...]:
    return tuple(
        sorted({reference for path in paths for reference in path.source_reference_ids}, key=str)
    )


def _confidence(paths: tuple[RawPath, ...]) -> Decimal | None:
    return confidence(tuple(path.confidence for path in paths))


def _quality(paths: tuple[RawPath, ...]) -> QualityState:
    return quality(tuple(path.quality for path in paths))


def _sum(paths: tuple[RawPath, ...]) -> Decimal:
    return sum(
        (path.money_coefficient for path in paths if path.money_coefficient is not None), ZERO
    )


def _dimension_partial(paths: tuple[RawPath, ...], dimension: XrayDimension) -> bool:
    return any(
        path.money_coefficient is None
        or (
            path.relative_coefficient > ZERO
            and not path.explicit_cash
            and bucket_key(path, dimension) is None
        )
        for path in paths
    )


def _fund_compositions(graph: Graph) -> tuple[FundComposition, ...]:
    output: list[FundComposition] = []
    by_root: dict[str, list[RawPath]] = defaultdict(list)
    for path in graph.paths:
        by_root[path.root_key].append(path)
    for held in graph.held_funds:
        paths = tuple(by_root[held.composition_root_key])
        grouped: dict[UUID, list[RawPath]] = defaultdict(list)
        for path in paths:
            if path.entity_id is not None:
                grouped[path.entity_id].append(path)
        entities: list[XrayFundEntity] = []
        unknown = sum(
            (path.relative_coefficient for path in paths if path.unresolved_reason is not None),
            ZERO,
        )
        cash = sum((path.relative_coefficient for path in paths if path.explicit_cash), ZERO)
        for entity, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
            relative = sum((path.relative_coefficient for path in rows), ZERO)
            entities.append(
                XrayFundEntity(
                    entity,
                    relative,
                    ratio_metric(
                        relative,
                        UNIT,
                        partial=unknown > ZERO,
                        state=_quality(tuple(rows)),
                        certainty=_confidence(tuple(rows)),
                        references=_refs(tuple(rows)),
                    ),
                    tuple(path.key for path in rows),
                )
            )
        if sum((item.relative_coefficient for item in entities), ZERO) + cash + unknown != UNIT:
            invalid("fund.unit_conservation")
        references, certainty, state = _refs(paths), _confidence(paths), _quality(paths)
        output.append(
            FundComposition(
                held.instrument_id,
                held.composition_root_key,
                tuple(entities),
                cash,
                unknown,
                ratio_metric(cash, UNIT, state=state, certainty=certainty, references=references),
                ratio_metric(
                    unknown, UNIT, state=state, certainty=certainty, references=references
                ),
                ratio_metric(
                    UNIT - unknown, UNIT, state=state, certainty=certainty, references=references
                ),
                unknown == ZERO,
                tuple(path.key for path in paths),
                references,
                state,
                certainty,
            )
        )
    return tuple(output)


def _quality_coverage(
    value: XrayInput, index: SourceIndex, graph: Graph, total: Decimal | None
) -> XrayQualityCoverage:
    roots: tuple[XrayPosition | XrayCash, ...] = (*value.positions, *value.cash)
    metrics = tuple(index.root_metric(item) for item in roots)
    valued_count = sum(root.money_coefficient is not None for root in graph.roots)
    direct = (
        sum(
            (root.money_coefficient for root in graph.roots if root.money_coefficient is not None),
            ZERO,
        )
        * UNIT
    )
    direct_refs = tuple(
        sorted(
            {reference for item in roots for reference in (*item.valuation_refs, *item.fx_refs)},
            key=str,
        )
    )
    direct_state = quality(tuple(item.quality for item in metrics))
    direct_confidence = confidence(tuple(item.confidence for item in metrics))
    incomplete = valued_count != len(roots)
    estimated_ids = {
        evidence.id
        for evidence in index.evidence.values()
        if evidence.quality is QualityState.ESTIMATED
        and index.dependencies[evidence.source_reference_id].kind
        in (XrayDependencyKind.IDENTITY, XrayDependencyKind.RELATIONSHIP)
    }
    inferred_paths = tuple(
        path
        for path in graph.paths
        if path.entity_id is not None
        and any(item in estimated_ids for item in path.identity_decision_ids)
    )
    inferred_ids = {
        item
        for path in inferred_paths
        for item in path.identity_decision_ids
        if item in estimated_ids
    }
    stale_refs = {
        evidence.source_reference_id
        for evidence in index.evidence.values()
        if evidence.quality is QualityState.STALE or index.stale(evidence)
    }
    stale_fx_roots: set[str] = set()
    quotes: tuple[tuple[str, XrayBrokerFx | XrayFxLeg], ...] = (
        *((quote.root_key, quote) for quote in value.broker_fx),
        *(
            (conversion.consumer_key, leg)
            for conversion in value.licensed_fx
            for leg in conversion.legs
        ),
    )
    for root_key, quote in quotes:
        if quote.quality is QualityState.STALE or (
            index.quality_evaluated_at.value - quote.observed_at.value
            > timedelta(seconds=value.policy.freshness_policy.stale_after_seconds)
        ):
            stale_fx_roots.add(root_key)
    stale_paths = tuple(
        path
        for path in graph.paths
        if path.root_key in stale_fx_roots
        or any(reference in stale_refs for reference in path.source_reference_ids)
    )
    inferred, stale = _sum(inferred_paths), _sum(stale_paths)
    inferred_partial = any(path.money_coefficient is None for path in inferred_paths)
    stale_partial = any(path.money_coefficient is None for path in stale_paths)
    return XrayQualityCoverage(
        len(roots),
        valued_count,
        money_metric(
            direct,
            value.reporting_currency,
            partial=incomplete,
            state=direct_state,
            certainty=direct_confidence,
            references=direct_refs,
        ),
        ratio_metric(
            direct,
            total,
            partial=incomplete,
            state=direct_state,
            certainty=direct_confidence,
            references=direct_refs,
        ),
        len(inferred_ids),
        money_metric(
            inferred,
            value.reporting_currency,
            partial=inferred_partial,
            state=_quality(inferred_paths),
            certainty=_confidence(inferred_paths),
            references=_refs(inferred_paths),
        ),
        ratio_metric(
            inferred,
            total,
            partial=inferred_partial,
            state=_quality(inferred_paths),
            certainty=_confidence(inferred_paths),
            references=_refs(inferred_paths),
        ),
        money_metric(
            stale,
            value.reporting_currency,
            partial=stale_partial,
            state=_quality(stale_paths),
            certainty=_confidence(stale_paths),
            references=_refs(stale_paths),
        ),
        ratio_metric(
            stale,
            total,
            partial=stale_partial,
            state=_quality(stale_paths),
            certainty=_confidence(stale_paths),
            references=_refs(stale_paths),
        ),
    )


def aggregate(value: XrayInput, index: SourceIndex, graph: Graph) -> XrayCalculation:
    with arithmetic():
        valued = all(root.money_coefficient is not None for root in graph.roots)
        total = (
            (
                sum(
                    (
                        root.money_coefficient
                        for root in graph.roots
                        if root.money_coefficient is not None
                    ),
                    ZERO,
                )
                * UNIT
            )
            if valued
            else None
        )
        if total is not None:
            # This boundary rejects a total overflow before constructing any successful result.
            q18(total, MONEY)
        _reconcile(value, graph, total)
        all_refs, all_confidence, all_quality = (
            _refs(graph.paths),
            _confidence(graph.paths),
            _quality(graph.paths),
        )
        dimensions_exact: list[XrayDimensionExact] = []
        dimensions: list[XrayDimensionSummary] = []
        buckets_exact: list[XrayBucketExact] = []
        buckets: list[XrayExposureBucket] = []
        residuals: list[XrayDisplayResidual] = []
        for dimension in XrayDimension:
            grouped: dict[str, list[RawPath]] = defaultdict(list)
            for path in graph.paths:
                key = bucket_key(path, dimension)
                if key is not None:
                    grouped[key].append(path)
            cash_paths = tuple(path for path in graph.paths if path.explicit_cash)
            unknown_paths = tuple(
                path
                for path in graph.paths
                if not path.explicit_cash and bucket_key(path, dimension) is None
            )
            known_paths = tuple(path for rows in grouped.values() for path in rows)
            known, cash, unknown = _sum(known_paths), _sum(cash_paths), _sum(unknown_paths)
            if total is not None and known + cash + unknown != total:
                invalid("dimension.conservation")
            partial = _dimension_partial(graph.paths, dimension)
            dimension_exact = XrayDimensionExact(dimension, known, cash, unknown)
            dimensions_exact.append(dimension_exact)
            unknown_money = money_metric(
                unknown,
                value.reporting_currency,
                partial=not valued,
                state=_quality(unknown_paths),
                certainty=_confidence(unknown_paths),
                references=_refs(unknown_paths),
            )
            dimensions.append(
                XrayDimensionSummary(
                    dimension,
                    money_metric(
                        known,
                        value.reporting_currency,
                        partial=partial,
                        state=_quality(known_paths),
                        certainty=_confidence(known_paths),
                        references=_refs(known_paths),
                    ),
                    money_metric(
                        cash,
                        value.reporting_currency,
                        partial=not valued,
                        state=_quality(cash_paths),
                        certainty=_confidence(cash_paths),
                        references=_refs(cash_paths),
                    ),
                    unknown_money,
                    ratio_metric(
                        known,
                        total,
                        partial=partial,
                        state=all_quality,
                        certainty=all_confidence,
                        references=all_refs,
                    ),
                    ratio_metric(
                        cash,
                        total,
                        state=all_quality,
                        certainty=all_confidence,
                        references=all_refs,
                    ),
                    ratio_metric(
                        unknown,
                        total,
                        state=all_quality,
                        certainty=all_confidence,
                        references=all_refs,
                    ),
                    not partial,
                    unknown > ZERO
                    and unknown_money.value is not None
                    and unknown_money.value.amount == ZERO,
                )
            )
            amount_children: list[Decimal] = []
            weight_children: list[Decimal] = []
            for key, rows in sorted(grouped.items()):
                paths = tuple(rows)
                direct = _sum(tuple(path for path in paths if not path.fund_edges))
                indirect = _sum(tuple(path for path in paths if path.fund_edges))
                effective = direct + indirect
                references, certainty, state = _refs(paths), _confidence(paths), _quality(paths)
                exact = XrayBucketExact(dimension, key, direct, indirect)
                buckets_exact.append(exact)
                output = XrayExposureBucket(
                    dimension,
                    key,
                    money_metric(
                        direct,
                        value.reporting_currency,
                        partial=partial,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    money_metric(
                        indirect,
                        value.reporting_currency,
                        partial=partial,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    money_metric(
                        effective,
                        value.reporting_currency,
                        partial=partial,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    ratio_metric(
                        effective,
                        total,
                        partial=partial,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    ratio_metric(
                        direct,
                        total,
                        partial=partial,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    ratio_metric(
                        indirect,
                        total,
                        partial=partial,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    certainty,
                    ratio_metric(
                        effective,
                        known if valued else None,
                        state=state,
                        certainty=certainty,
                        references=references,
                    ),
                    tuple(path.key for path in paths),
                    references,
                )
                buckets.append(output)
                assert (
                    output.effective.value is not None
                    and output.direct.value is not None
                    and output.indirect.value is not None
                )
                amount_children.append(output.effective.value.amount)
                if output.absolute_weight.value is not None:
                    weight_children.append(output.absolute_weight.value)
                residuals.append(
                    _display_residual(
                        f"{dimension.value}:{key}:direct_indirect",
                        residual(
                            output.effective.value.amount,
                            (output.direct.value.amount, output.indirect.value.amount),
                            rounded_parent=True,
                        ),
                        2,
                        True,
                        value.reporting_currency,
                        XrayResidualKind.DIRECT_INDIRECT,
                        f"bucket:{dimension.value}:{key}",
                    )
                )
                path_values = tuple(
                    q18(path.money_coefficient, MONEY)
                    for path in paths
                    if path.money_coefficient is not None
                )
                residuals.append(
                    _display_residual(
                        f"{dimension.value}:{key}:paths",
                        residual(output.effective.value.amount, path_values, rounded_parent=True),
                        len(path_values),
                        True,
                        value.reporting_currency,
                        XrayResidualKind.PARENT_CHILD,
                        f"bucket:{dimension.value}:{key}",
                    )
                )
            if total is not None:
                amounts = (*amount_children, q18(cash, MONEY), q18(unknown, MONEY))
                residuals.append(
                    _display_residual(
                        f"{dimension.value}:amount_partition",
                        residual(q18(total, MONEY), amounts, rounded_parent=False),
                        len(amounts),
                        False,
                        value.reporting_currency,
                        XrayResidualKind.MONEY_PARTITION,
                        f"dimension:{dimension.value}",
                    )
                )
                if total > ZERO:
                    weights = (*weight_children, q18(cash, total), q18(unknown, total))
                    residuals.append(
                        _display_residual(
                            f"{dimension.value}:weight_partition",
                            residual(Decimal("1"), weights, rounded_parent=False),
                            len(weights),
                            False,
                            None,
                            XrayResidualKind.WEIGHT_PARTITION,
                            f"dimension:{dimension.value}",
                        )
                    )
        residuals.extend(_edge_residuals(graph, value.reporting_currency))
        by_dimension = {item.dimension: item for item in dimensions_exact}
        company = tuple(item for item in buckets_exact if item.dimension is XrayDimension.COMPANY)
        ranked = tuple(
            sorted(
                company,
                key=lambda item: (
                    -(item.direct_coefficient + item.indirect_coefficient),
                    item.bucket_key,
                ),
            )
        )
        hhi = sum(
            (
                (item.direct_coefficient + item.indirect_coefficient)
                * (item.direct_coefficient + item.indirect_coefficient)
                for item in company
            ),
            ZERO,
        )
        square = None if total is None else total * total
        if square is not None and hhi > square:
            invalid("hhi.conservation")
        original: dict[UUID, dict[str, Decimal]] = defaultdict(dict)
        for path in graph.paths:
            if (
                path.entity_id is not None
                and path.money_coefficient is not None
                and path.root_key.startswith("position:")
            ):
                previous = original[path.entity_id].get(path.root_key, ZERO)
                original[path.entity_id][path.root_key] = previous + path.money_coefficient
        duplication = sum(
            (sum(rows.values(), ZERO) - max(rows.values()) for rows in original.values()), ZERO
        )
        partial_company = _dimension_partial(graph.paths, XrayDimension.COMPANY)
        top = tuple(
            XrayTopConcentration(
                count,
                tuple(UUID(item.bucket_key) for item in ranked[:count]),
                ratio_metric(
                    sum(
                        (
                            item.direct_coefficient + item.indirect_coefficient
                            for item in ranked[:count]
                        ),
                        ZERO,
                    ),
                    total,
                    partial=partial_company,
                    state=all_quality,
                    certainty=all_confidence,
                    references=all_refs,
                ),
            )
            for count in (1, 5, 10, 25, 50)
        )
        conclusions = _thresholds(value, ranked, hhi, total, square, partial_company)
        company_summary = next(
            item for item in dimensions if item.dimension is XrayDimension.COMPANY
        )
        summary = XrayPortfolioSummary(
            money_metric(
                total,
                value.reporting_currency,
                state=all_quality,
                certainty=all_confidence,
                references=all_refs,
            ),
            company_summary.known_weight,
            company_summary.cash_weight,
            company_summary.unresolved_weight,
            ratio_metric(
                duplication,
                total,
                partial=partial_company,
                state=all_quality,
                certainty=all_confidence,
                references=all_refs,
            ),
            top,
            ratio_metric(
                hhi,
                square,
                partial=partial_company,
                state=all_quality,
                certainty=all_confidence,
                references=all_refs,
            ),
            conclusions,
            _quality_coverage(value, index, graph, total),
        )
        paths_out = tuple(
            _path_output(path, value.reporting_currency, total, by_dimension, valued)
            for path in graph.paths
        )
        fund_ids = {item.instrument_id for item in graph.held_funds}
        root_by_key = {item.root_key: item for item in graph.roots}
        root_metrics = {item.root.key: index.root_metric(item) for item in value.positions}
        direct_positions = tuple(
            XrayDirectPosition(
                item.root,
                root_metrics[item.root.key],
                ratio_metric(
                    None
                    if (root_coefficient := root_by_key[item.root.key].money_coefficient) is None
                    else root_coefficient * UNIT,
                    total,
                    state=root_metrics[item.root.key].quality,
                    certainty=root_metrics[item.root.key].confidence,
                    references=tuple(sorted(set(item.valuation_refs + item.fx_refs), key=str)),
                ),
                item.root.instrument_id in fund_ids,
                tuple(sorted(set(item.valuation_refs + item.fx_refs), key=str)),
            )
            for item in sorted(value.positions, key=lambda item: str(item.root.position_id))
        )
        return XrayCalculation(
            sha256(encode_xray_input(value)).hexdigest(),
            value.owner_id,
            value.account_id,
            value.snapshot_id,
            value.valuation_at,
            value.source_cutoff_at,
            index.quality_evaluated_at,
            _warnings(index, graph),
            value.reporting_currency,
            replace(
                value.policy,
                taxonomy_versions=tuple(
                    sorted(value.policy.taxonomy_versions, key=lambda item: item.dimension.value)
                ),
            ),
            tuple(index.selections[key] for key in sorted(index.selections)),
            tuple(
                index.classification_decisions[key]
                for key in sorted(index.classification_decisions)
            ),
            tuple(index.uses[key] for key in sorted(index.uses)),
            tuple(sorted(value.source_dependencies, key=lambda item: str(item.id))),
            summary,
            value.reconciliation,
            direct_positions,
            tuple(dimensions),
            tuple(buckets),
            paths_out,
            graph.held_funds,
            _fund_compositions(graph),
            XrayExactState(
                graph.roots,
                total,
                tuple(buckets_exact),
                tuple(dimensions_exact),
                duplication,
                hhi,
                square,
                graph.visited_paths,
            ),
            tuple(residuals),
        )


def _path_output(
    path: RawPath,
    currency: CurrencyCode,
    total: Decimal | None,
    dimensions: dict[XrayDimension, XrayDimensionExact],
    valued: bool,
) -> XrayTerminalPath:
    metrics = tuple(
        XrayPathDimensionMetric(
            dimension,
            ratio_metric(
                path.money_coefficient if bucket_key(path, dimension) is not None else None,
                dimensions[dimension].known_coefficient if valued else None,
                state=path.quality,
                certainty=path.confidence,
                references=path.source_reference_ids,
                reason=XrayReason.MISSING_CLASSIFICATION
                if valued
                else XrayReason.INCOMPLETE_VALUATION,
            ),
        )
        for dimension in XrayDimension
    )
    return XrayTerminalPath(
        path.key,
        path.root_key,
        path.instrument_id,
        path.entity_id,
        path.explicit_cash,
        path.unresolved_reason,
        path.fund_edges,
        path.relative_coefficient,
        path.money_coefficient,
        path.identity_decision_ids,
        path.source_reference_ids,
        path.classifications,
        path.quality,
        path.confidence,
        money_metric(
            path.money_coefficient,
            currency,
            state=path.quality,
            certainty=path.confidence,
            references=path.source_reference_ids,
        ),
        ratio_metric(
            path.money_coefficient,
            total,
            state=path.quality,
            certainty=path.confidence,
            references=path.source_reference_ids,
        ),
        ratio_metric(
            path.relative_coefficient,
            UNIT,
            state=path.quality,
            certainty=path.confidence,
            references=path.source_reference_ids,
        ),
        metrics,
    )


def _thresholds(
    value: XrayInput,
    ranked: tuple[XrayBucketExact, ...],
    hhi: Decimal,
    total: Decimal | None,
    square: Decimal | None,
    partial: bool,
) -> tuple[XrayThresholdConclusion, ...]:
    policy = value.policy.thresholds
    output: list[XrayThresholdConclusion] = []
    for name, count in (("top1", 1), ("top5", 5), ("hhi", 0)):
        bound = XrayBound.LOWER_BOUND if partial else XrayBound.EXACT
        if not isinstance(policy, ConcentrationThresholdPolicy):
            output.append(XrayThresholdConclusion(name, None, XrayReason.UNCONFIGURED, bound))
            continue
        denominator = square if name == "hhi" else total
        if denominator is None or denominator <= ZERO:
            output.append(
                XrayThresholdConclusion(
                    name,
                    None,
                    XrayReason.ZERO_DENOMINATOR
                    if denominator == ZERO
                    else XrayReason.INCOMPLETE_VALUATION,
                    bound,
                )
            )
            continue
        numerator = (
            hhi
            if name == "hhi"
            else sum(
                (item.direct_coefficient + item.indirect_coefficient for item in ranked[:count]),
                ZERO,
            )
        )
        limit = {"top1": policy.top1_limit, "top5": policy.top5_limit, "hhi": policy.hhi_limit}[
            name
        ]
        comparison = {
            "top1": policy.top1_comparison,
            "top5": policy.top5_comparison,
            "hhi": policy.hhi_comparison,
        }[name]
        breached = threshold(numerator, denominator, limit, comparison)
        output.append(
            XrayThresholdConclusion(
                name,
                None if partial and not breached else breached,
                XrayReason.INCONCLUSIVE_LOWER_BOUND if partial and not breached else None,
                bound,
            )
        )
    return tuple(output)


def _reconcile(value: XrayInput, graph: Graph, total: Decimal | None) -> None:
    available = tuple(root.root_key for root in graph.roots if root.money_coefficient is not None)
    missing = tuple(root.root_key for root in graph.roots if root.money_coefficient is None)
    coverage = value.valuation_coverage
    if (
        set(coverage.valued_root_keys) != set(available)
        or set(coverage.unavailable_root_keys) != set(missing)
        or coverage.complete != (not missing)
    ):
        invalid("valuation_coverage")
    declared, root, difference = (
        value.reconciliation.declared_total.value,
        value.reconciliation.root_total.value,
        value.reconciliation.difference.value,
    )
    actual = value.portfolio_total.value
    if value.reconciliation.declared_total != value.portfolio_total:
        invalid("reconciliation.declared_total")
    if any(
        item.currency != value.reporting_currency
        for item in (actual, declared, root, difference)
        if item is not None
    ):
        invalid("reconciliation.currency")
    if total is None:
        if root is not None or difference is not None:
            invalid("incomplete_root_total")
        return
    if root is None or coefficient18(root.amount) * UNIT != total:
        invalid("reconciliation.root_total")
    if declared is None:
        if difference is not None:
            invalid("reconciliation.unavailable_difference")
        return
    if difference is None or declared.amount - root.amount != difference.amount:
        invalid("reconciliation.difference")
    if difference.amount != ZERO and not (
        value.reconciliation.source_reference_ids
        or value.reconciliation.difference.source_reference_ids
    ):
        invalid("reconciliation.provenance")


def _warnings(index: SourceIndex, graph: Graph) -> tuple[XrayWarning, ...]:
    warnings: dict[tuple[str, str, str], XrayWarning] = {}
    for use in index.uses.values():
        if use.evidence_id is None:
            continue
        evidence = index.evidence[use.evidence_id]
        codes: list[XrayWarningCode] = []
        if evidence.effective_at != index.value.valuation_at:
            codes.append(XrayWarningCode.SOURCE_DATE_MISMATCH)
        if index.stale(evidence):
            codes.append(XrayWarningCode.STALE_SOURCE)
        if evidence.quality is QualityState.ESTIMATED:
            codes.append(XrayWarningCode.ESTIMATED_SOURCE)
        if evidence.quality in (QualityState.PARTIAL, QualityState.FAILED):
            codes.append(XrayWarningCode.PARTIAL_SOURCE)
        if evidence.confidence is None:
            codes.append(XrayWarningCode.UNKNOWN_CONFIDENCE)
        for code in codes:
            warnings[(code.value, str(use.source_reference_id), "")] = XrayWarning(
                code, None, (use.source_reference_id,), ()
            )
    quotes: tuple[XrayBrokerFx | XrayFxLeg, ...] = (
        *index.value.broker_fx,
        *(leg for conversion in index.value.licensed_fx for leg in conversion.legs),
    )
    for quote in quotes:
        codes = []
        if quote.observed_at != index.value.valuation_at:
            codes.append(XrayWarningCode.SOURCE_DATE_MISMATCH)
        if index.quality_evaluated_at.value - quote.observed_at.value > timedelta(
            seconds=index.value.policy.freshness_policy.stale_after_seconds
        ):
            codes.append(XrayWarningCode.STALE_SOURCE)
        if quote.quality is QualityState.ESTIMATED:
            codes.append(XrayWarningCode.ESTIMATED_SOURCE)
        if quote.quality in (QualityState.PARTIAL, QualityState.FAILED) or quote.rate is None:
            codes.append(XrayWarningCode.PARTIAL_SOURCE)
        if quote.confidence is None:
            codes.append(XrayWarningCode.UNKNOWN_CONFIDENCE)
        for code in codes:
            warnings[(code.value, str(quote.source_reference_id), "")] = XrayWarning(
                code, None, (quote.source_reference_id,), ()
            )
    for path in graph.paths:
        reasons = tuple(
            item
            for item in (path.unresolved_reason, *(row.reason for row in path.classifications))
            if item is not None
        )
        for reason in set(reasons):
            code = (
                XrayWarningCode.BOUNDED_TRAVERSAL
                if reason
                in (
                    XrayReason.DEPTH_LIMIT,
                    XrayReason.PATH_LIMIT,
                    XrayReason.PROOF_LIMIT,
                    XrayReason.CYCLE,
                )
                else XrayWarningCode.AMBIGUOUS_EVIDENCE
                if reason
                in (
                    XrayReason.AMBIGUOUS_IDENTITY,
                    XrayReason.AMBIGUOUS_CLASSIFICATION,
                    XrayReason.AMBIGUOUS_SOURCE,
                )
                else XrayWarningCode.MISSING_INPUT
            )
            warnings[(code.value, path.key, reason.value)] = XrayWarning(
                code, reason, path.source_reference_ids, (path.key,)
            )
        if path.money_coefficient is None:
            warnings[(XrayWarningCode.MISSING_INPUT.value, path.key, "valuation")] = XrayWarning(
                XrayWarningCode.MISSING_INPUT,
                XrayReason.MISSING_VALUE,
                path.source_reference_ids,
                (path.key,),
            )
    difference = index.value.reconciliation.difference.value
    if difference is not None and difference.amount != ZERO:
        references = tuple(
            sorted(
                set(
                    index.value.reconciliation.source_reference_ids
                    + index.value.reconciliation.difference.source_reference_ids
                ),
                key=str,
            )
        )
        for offset in range(0, len(references), 256):
            warnings[(XrayWarningCode.UNRECONCILED_VALUE.value, str(offset), "")] = XrayWarning(
                XrayWarningCode.UNRECONCILED_VALUE,
                XrayReason.RECONCILIATION_DIFFERENCE,
                references[offset : offset + 256],
                (),
            )
    return tuple(warnings[key] for key in sorted(warnings))


def _display_residual(
    key: str,
    coefficient: Decimal,
    count: int,
    rounded: bool,
    currency: CurrencyCode | None,
    kind: XrayResidualKind,
    consumer: str,
) -> XrayDisplayResidual:
    return XrayDisplayResidual(
        key,
        coefficient,
        count,
        rounded,
        q18(coefficient, Decimal("1e18")),
        currency,
        kind,
        consumer,
    )


def _edge_residuals(graph: Graph, currency: CurrencyCode) -> tuple[XrayDisplayResidual, ...]:
    nodes: dict[str, tuple[Decimal, dict[str, Decimal], Decimal | None]] = {}
    root_money = {item.root_key: item.money_coefficient for item in graph.roots}
    for path in graph.paths:
        components = path.key.split("/")
        for depth in range(len(path.fund_edges)):
            parent_key = "/".join(components[: depth + 1])
            child = "/".join(components[: depth + 2])
            parent_relative = path_relative(tuple(edge.weight for edge in path.fund_edges[:depth]))
            child_relative = path_relative(
                tuple(edge.weight for edge in path.fund_edges[: depth + 1])
            )
            node = nodes.setdefault(parent_key, (parent_relative, {}, root_money[path.root_key]))
            existing = node[1].setdefault(child, child_relative)
            if existing != child_relative:
                invalid("edge.identity")
    output: list[XrayDisplayResidual] = []
    for key, (parent, children, money) in sorted(nodes.items()):
        values = tuple(children[child] for child in sorted(children))
        if sum(values, ZERO) != parent:
            invalid("edge.conservation")
        unit_residual = residual(
            q18(parent, UNIT), tuple(q18(item, UNIT) for item in values), rounded_parent=True
        )
        output.append(
            _display_residual(
                key + ":unit_children",
                unit_residual,
                len(values),
                True,
                None,
                XrayResidualKind.UNIT_PARENT_CHILD,
                key,
            )
        )
        if money is not None:
            amount_residual = residual(
                q18(parent * money, MONEY),
                tuple(q18(item * money, MONEY) for item in values),
                rounded_parent=True,
            )
            output.append(
                _display_residual(
                    key + ":money_children",
                    amount_residual,
                    len(values),
                    True,
                    currency,
                    XrayResidualKind.PARENT_CHILD,
                    key,
                )
            )
    return tuple(output)
