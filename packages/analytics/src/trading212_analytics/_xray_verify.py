"""Independent retained-value audit plus replay binding of the full semantic body."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading212_domain.xray import XrayCash, XrayDimension, XrayInput, XrayPosition
from trading212_domain.xray_codec import encode_xray_input, encode_xray_result
from trading212_domain.xray_result import XrayCalculation, XrayTerminalPath
from trading212_domain.xray_validation import invalid

from trading212_analytics._xray_aggregate import aggregate, bucket_key
from trading212_analytics._xray_decimal import (
    MONEY,
    UNIT,
    ZERO,
    arithmetic,
    coefficient18,
    q18,
    verify_broker_fx,
)
from trading212_analytics._xray_graph import walk
from trading212_analytics._xray_sources import SourceIndex
from trading212_analytics._xray_valuation import verify_licensed_fx


def _audit(value: XrayInput, result: XrayCalculation) -> None:
    verify_broker_fx(value)
    verify_licensed_fx(value)
    if result.input_digest != sha256(encode_xray_input(value)).hexdigest():
        invalid("result.input_digest")
    root_rows: tuple[XrayPosition | XrayCash, ...] = (*value.positions, *value.cash)
    roots = {item.root.key: item for item in root_rows}
    exact_roots = {item.root_key: item.money_coefficient for item in result.exact_state.roots}
    if len(exact_roots) != len(result.exact_state.roots) or set(exact_roots) != set(roots):
        invalid("result.root_inventory")
    relative_by_root: dict[str, Decimal] = defaultdict(lambda: ZERO)
    money_by_root: dict[str, Decimal] = defaultdict(lambda: ZERO)
    path_keys: set[str] = set()
    for path in result.terminal_paths:
        if path.key in path_keys or path.root_key not in roots:
            invalid("result.path_identity")
        path_keys.add(path.key)
        # Reconstruct using fixed-place edge scaling, independently of graph path_relative.
        coefficient = UNIT
        for edge in path.fund_edges:
            coefficient *= edge.weight
        coefficient = coefficient.quantize(Decimal("1"))
        if coefficient != path.relative_coefficient:
            invalid("result.path_relative")
        source_money = roots[path.root_key].reporting_value.value
        expected = None if source_money is None else coefficient18(source_money.amount)
        if exact_roots[path.root_key] != expected:
            invalid("result.root_money")
        numerator = None if expected is None else expected * coefficient
        if path.money_coefficient != numerator:
            invalid("result.path_money")
        if (path.reporting_value.value is None) != (numerator is None):
            invalid("result.path_metric")
        if numerator is not None:
            if path.reporting_value.value is None or path.reporting_value.value.amount != q18(
                numerator, MONEY
            ):
                invalid("result.path_rounding")
            money_by_root[path.root_key] += numerator
        if path.relative_weight.value != q18(coefficient, UNIT):
            invalid("result.relative_rounding")
        relative_by_root[path.root_key] += coefficient
    for root, root_coefficient in exact_roots.items():
        if relative_by_root[root] != UNIT or (
            root_coefficient is not None and money_by_root[root] != root_coefficient * UNIT
        ):
            invalid("result.root_conservation")
    complete = all(item is not None for item in exact_roots.values())
    total = sum(money_by_root.values(), ZERO) if complete else None
    if result.exact_state.portfolio_coefficient != total:
        invalid("result.portfolio_coefficient")
    public_buckets = {(item.dimension, item.bucket_key): item for item in result.exposure_buckets}
    dimension_states = {item.dimension: item for item in result.exact_state.dimensions}
    for dimension in XrayDimension:
        expected_buckets: dict[str, list[Decimal]] = {}
        cash, unknown = ZERO, ZERO
        for path in result.terminal_paths:
            amount = path.money_coefficient
            if amount is None:
                amount = ZERO  # Known subtotal only; the missing root remains explicit above.
            key = bucket_key(path, dimension)
            if key is not None:
                pair = expected_buckets.setdefault(key, [ZERO, ZERO])
                location = 1 if path.fund_edges else 0
                pair[location] += amount
            elif path.explicit_cash:
                cash += amount
            else:
                unknown += amount
        actual = tuple(item for item in result.exact_state.buckets if item.dimension is dimension)
        if len(actual) != len(expected_buckets) or {item.bucket_key for item in actual} != set(
            expected_buckets
        ):
            invalid("result.bucket_inventory")
        known = ZERO
        for item in actual:
            direct, indirect = expected_buckets[item.bucket_key]
            if (item.direct_coefficient, item.indirect_coefficient) != (direct, indirect):
                invalid("result.bucket_coefficient")
            known += direct + indirect
            public = public_buckets[(dimension, item.bucket_key)]
            for metric, numerator in (
                (public.direct, direct),
                (public.indirect, indirect),
                (public.effective, direct + indirect),
            ):
                if metric.value is None or metric.value.amount != q18(numerator, MONEY):
                    invalid("result.bucket_rounding")
        state = dimension_states[dimension]
        if (state.known_coefficient, state.cash_coefficient, state.unresolved_coefficient) != (
            known,
            cash,
            unknown,
        ):
            invalid("result.dimension_coefficients")
        if total is not None and known + cash + unknown != total:
            invalid("result.dimension_conservation")
    entities: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for path in result.terminal_paths:
        if path.entity_id is None or path.money_coefficient is None:
            continue
        roots_for_entity = entities[str(path.entity_id)]
        roots_for_entity[path.root_key] = (
            roots_for_entity.get(path.root_key, ZERO) + path.money_coefficient
        )
    duplicated, squared = ZERO, ZERO
    for rows in entities.values():
        amount = sum(rows.values(), ZERO)
        squared += amount * amount
        duplicated += amount - max(rows.values())
    if (
        result.exact_state.hhi_coefficient != squared
        or result.exact_state.duplication_coefficient != duplicated
    ):
        invalid("result.company_coefficients")
    position_roots: dict[UUID, list[str]] = defaultdict(list)
    paths_by_root: dict[str, list[XrayTerminalPath]] = defaultdict(list)
    for position in value.positions:
        position_roots[position.root.instrument_id].append(position.root.key)
    for path in result.terminal_paths:
        paths_by_root[path.root_key].append(path)
    compositions = {item.fund_instrument_id: item for item in result.fund_compositions}
    for held in result.held_funds:
        positions = tuple(position_roots[held.instrument_id])
        if (
            not positions
            or held.composition_root_key != min(positions)
            or set(held.root_keys) != set(positions)
        ):
            invalid("result.representative")
        composition = compositions[held.instrument_id]
        relative: dict[str, Decimal] = defaultdict(lambda: ZERO)
        cash, unknown = ZERO, ZERO
        for path in paths_by_root[held.composition_root_key]:
            if path.entity_id is not None:
                relative[str(path.entity_id)] += path.relative_coefficient
            elif path.explicit_cash:
                cash += path.relative_coefficient
            else:
                unknown += path.relative_coefficient
        actual_relative = {
            str(item.entity_id): item.relative_coefficient for item in composition.entities
        }
        if (
            actual_relative != relative
            or composition.cash_coefficient != cash
            or composition.unresolved_coefficient != unknown
        ):
            invalid("result.fund_composition")
        if sum(relative.values(), ZERO) + cash + unknown != UNIT:
            invalid("result.fund_conservation")


def verify(value: XrayInput, result: XrayCalculation) -> None:
    with arithmetic():
        if type(value) is not XrayInput or type(result) is not XrayCalculation:
            invalid("result.type")
        _audit(value, result)
        sources = SourceIndex(value)
        graph = walk(value, sources)
        expected = aggregate(value, sources, graph)
        # This comparison supplements the independent financial audit: it binds every
        # source choice, cutoff, confidence, warning, quality gate and public field.
        if encode_xray_result(expected) != encode_xray_result(result):
            invalid("result.semantic_binding")
