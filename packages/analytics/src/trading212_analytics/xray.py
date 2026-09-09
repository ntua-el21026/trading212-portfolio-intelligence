"""Pure X-ray calculation, verification and bounded retained-composition projections."""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations
from uuid import UUID

from trading212_domain.xray import XrayBound, XrayDimension, XrayInput
from trading212_domain.xray_codec import encode_xray_input, encode_xray_result
from trading212_domain.xray_result import (
    CanonicalCommonEntities,
    CanonicalCommonEntity,
    CanonicalFundPair,
    CanonicalOverlapPair,
    CompanyExposureBasis,
    FundComposition,
    XrayCalculation,
    XrayCommonEntitiesTop,
)
from trading212_domain.xray_validation import bound, invalid

from trading212_analytics._xray_aggregate import aggregate, ratio_metric
from trading212_analytics._xray_decimal import UNIT, ZERO, arithmetic, verify_broker_fx
from trading212_analytics._xray_graph import walk
from trading212_analytics._xray_sources import SourceIndex, confidence, quality
from trading212_analytics._xray_valuation import (
    build_xray_reconciliation as build_xray_reconciliation,
)
from trading212_analytics._xray_valuation import (
    convert_xray_money as convert_xray_money,
)
from trading212_analytics._xray_valuation import (
    verify_licensed_fx,
)


def calculate_xray(value: XrayInput) -> XrayCalculation:
    """Calculate the entire capture; request projections never enter this signature."""
    with arithmetic():
        encode_xray_input(value)
        verify_broker_fx(value)
        verify_licensed_fx(value)
        sources = SourceIndex(value)
        graph = walk(value, sources)
        result = aggregate(value, sources, graph)
        encode_xray_result(result)
        return result


def verify_xray_result(value: XrayInput, result: XrayCalculation) -> None:
    """Audit coefficients independently, then bind all source/graph/output decisions."""
    from trading212_analytics._xray_verify import verify

    verify(value, result)


def _compositions(result: XrayCalculation) -> dict[UUID, FundComposition]:
    if type(result) is not XrayCalculation:
        invalid("result.type")
    held = {item.instrument_id: item for item in result.held_funds}
    output: dict[UUID, FundComposition] = {}
    for item in result.fund_compositions:
        if item.fund_instrument_id in output or item.fund_instrument_id not in held:
            invalid("fund_composition.identity")
        root = held[item.fund_instrument_id]
        if item.composition_root_key != root.composition_root_key or (
            root.composition_root_key != min(root.root_keys)
        ):
            invalid("fund_composition.representative")
        if len({entity.entity_id for entity in item.entities}) != len(item.entities):
            invalid("fund_composition.entities")
        if sum((entity.relative_coefficient for entity in item.entities), ZERO) + (
            item.cash_coefficient + item.unresolved_coefficient
        ) != UNIT or item.complete != (item.unresolved_coefficient == ZERO):
            invalid("fund_composition.unit_conservation")
        output[item.fund_instrument_id] = item
    if set(output) != set(held):
        invalid("fund_composition.inventory")
    return output


def _pair(
    pair: CanonicalFundPair, first: FundComposition, second: FundComposition, digest: str
) -> tuple[CanonicalOverlapPair, tuple[tuple[UUID, Decimal, Decimal], ...]]:
    left = {item.entity_id: item.relative_coefficient for item in first.entities}
    right = {item.entity_id: item.relative_coefficient for item in second.entities}
    common = tuple(
        (entity, left[entity], right[entity])
        for entity in sorted(left.keys() & right.keys(), key=str)
        if min(left[entity], right[entity]) > ZERO
    )
    numerator = sum((min(left_value, right_value) for _, left_value, right_value in common), ZERO)
    partial = not first.complete or not second.complete
    state, certainty = (
        quality((first.quality, second.quality)),
        confidence((first.confidence, second.confidence)),
    )
    references = tuple(
        sorted(set(first.source_reference_ids + second.source_reference_ids), key=str)
    )
    result = CanonicalOverlapPair(
        pair,
        digest,
        numerator,
        ratio_metric(
            numerator,
            UNIT,
            partial=partial,
            state=state,
            certainty=certainty,
            references=references,
        ),
        first.coverage,
        second.coverage,
        first.composition_root_key,
        second.composition_root_key,
        len(common),
    )
    return result, common


def calculate_overlap_pairs(
    result: XrayCalculation, fund_ids: tuple[UUID, ...]
) -> tuple[CanonicalOverlapPair, ...]:
    with arithmetic():
        if type(fund_ids) is not tuple or any(type(item) is not UUID for item in fund_ids):
            invalid("fund_ids")
        bound(2 <= len(fund_ids) <= 32, "fund_ids")
        if len(set(fund_ids)) != len(fund_ids):
            invalid("fund_ids.duplicate")
        compositions = _compositions(result)
        if not set(fund_ids).issubset(compositions):
            invalid("fund_ids.not_held")
        digest = result.content_digest
        return tuple(
            _pair(
                CanonicalFundPair(first, second), compositions[first], compositions[second], digest
            )[0]
            for first, second in combinations(sorted(fund_ids, key=str), 2)
        )


def calculate_common_entities(
    result: XrayCalculation, pair: CanonicalFundPair
) -> CanonicalCommonEntities:
    with arithmetic():
        if type(pair) is not CanonicalFundPair:
            invalid("pair.type")
        compositions = _compositions(result)
        if pair.first_fund_id not in compositions or pair.second_fund_id not in compositions:
            invalid("pair.not_held")
        first, second = compositions[pair.first_fund_id], compositions[pair.second_fund_id]
        overlap, common = _pair(pair, first, second, result.content_digest)
        partial = overlap.overlap.bound is XrayBound.LOWER_BOUND
        rows = tuple(
            CanonicalCommonEntity(
                entity,
                left,
                right,
                min(left, right),
                ratio_metric(
                    left,
                    UNIT,
                    partial=not first.complete,
                    state=first.quality,
                    certainty=first.confidence,
                    references=first.source_reference_ids,
                ),
                ratio_metric(
                    right,
                    UNIT,
                    partial=not second.complete,
                    state=second.quality,
                    certainty=second.confidence,
                    references=second.source_reference_ids,
                ),
                ratio_metric(
                    min(left, right),
                    UNIT,
                    partial=partial,
                    state=overlap.overlap.quality,
                    certainty=overlap.overlap.confidence,
                    references=overlap.overlap.source_reference_ids,
                ),
            )
            for entity, left, right in sorted(
                common, key=lambda row: (-min(row[1], row[2]), str(row[0]))
            )
        )
        return CanonicalCommonEntities(overlap, rows)


def company_exposure_basis(result: XrayCalculation) -> CompanyExposureBasis:
    with arithmetic():
        if type(result) is not XrayCalculation:
            invalid("result.type")
        exposures = tuple(
            item for item in result.exposure_buckets if item.dimension is XrayDimension.COMPANY
        )
        return CompanyExposureBasis(
            result.content_digest,
            result.input_digest,
            result.reporting_currency,
            result.portfolio_summary.total,
            result.portfolio_summary.company_known_weight,
            exposures,
            tuple(
                item
                for item in result.exact_state.buckets
                if item.dimension is XrayDimension.COMPANY
            ),
            tuple(
                sorted(
                    {source for item in exposures for source in item.source_reference_ids}, key=str
                )
            ),
        )


def project_common_entities_top(
    common: CanonicalCommonEntities, top_n: int
) -> XrayCommonEntitiesTop:
    """Round the exact omitted sum once; never subtract displayed rounded totals."""
    with arithmetic():
        if type(common) is not CanonicalCommonEntities or type(top_n) is not int:
            invalid("common_top.type")
        bound(1 <= top_n <= 50, "common_top.limit")
        expected_order = tuple(
            sorted(
                common.entities, key=lambda item: (-item.common_coefficient, str(item.entity_id))
            )
        )
        if common.entities != expected_order or len(
            {item.entity_id for item in common.entities}
        ) != len(common.entities):
            invalid("common_top.order")
        numerator = sum((item.common_coefficient for item in common.entities[top_n:]), ZERO)
        parent = common.pair.overlap
        omitted = ratio_metric(
            numerator,
            UNIT,
            partial=parent.bound is XrayBound.LOWER_BOUND,
            state=parent.quality,
            certainty=parent.confidence,
            references=parent.source_reference_ids,
        )
        items = common.entities[:top_n]
        return XrayCommonEntitiesTop(
            items, len(common.entities), len(items), len(common.entities) - len(items), omitted
        )
