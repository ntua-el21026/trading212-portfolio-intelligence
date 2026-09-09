from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from typing import cast
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trading212_analytics.xray import calculate_overlap_pairs, calculate_xray, verify_xray_result
from trading212_domain import xray as d
from trading212_domain.xray_codec import encode_xray_result
from trading212_domain.xray_result import XrayCalculation, XrayDisplayResidual

from tests.unit.analytics.test_xray_decimal import oracle
from tests.unit.analytics.xray_factories import Builder, reversed_input, uid

pytestmark = pytest.mark.property


def reference_paths(
    value: d.XrayInput,
) -> dict[str, list[tuple[UUID | None, str, Fraction, Fraction]]]:
    """Independent recursive Fraction graph; never reads calculator paths/coefficients."""
    mappings = {item.fund_instrument_id: item.id for item in value.fund_mappings}
    candidates = {item.fund_mapping_id: item for item in value.constituent_candidates}
    identities = {item.instrument_id: item.entity_id for item in value.entity_evidence}
    output: dict[str, list[tuple[UUID | None, str, Fraction, Fraction]]] = defaultdict(list)

    def visit(
        root: str,
        instrument: UUID,
        fraction: Fraction,
        amount: Fraction,
        ancestry: tuple[UUID, ...] = (),
    ) -> None:
        if instrument in ancestry:
            output[root].append((None, "unknown", fraction, amount * fraction))
        elif instrument not in mappings:
            entity = identities.get(instrument)
            output[root].append(
                (entity, "entity" if entity is not None else "unknown", fraction, amount * fraction)
            )
        elif len(ancestry) >= 4:
            output[root].append((None, "unknown", fraction, amount * fraction))
        else:
            candidate = candidates[mappings[instrument]]
            remainder = Fraction(1)
            for holding in candidate.holdings:
                weight = Fraction(holding.weight)
                remainder -= weight
                if holding.kind is d.XrayHoldingKind.CASH:
                    output[root].append(
                        (None, "cash", fraction * weight, amount * fraction * weight)
                    )
                else:
                    assert holding.instrument_id is not None
                    visit(
                        root,
                        holding.instrument_id,
                        fraction * weight,
                        amount,
                        (*ancestry, instrument),
                    )
            if remainder:
                output[root].append(
                    (None, "unknown", fraction * remainder, amount * fraction * remainder)
                )

    for position in value.positions:
        assert position.reporting_value.value is not None
        visit(
            position.root.key,
            position.root.instrument_id,
            Fraction(1),
            Fraction(position.reporting_value.value.amount),
        )
    return output


@pytest.mark.parametrize("fund_edges", [4, 5])
def test_fraction_graph_preserves_equity_at_four_edges_and_stops_fifth_expansion(
    fund_edges: int,
) -> None:
    builder = Builder()
    root = builder.position(uid(20), "7.25", position_id=uid(1000)).root.key
    entity = uid(110)
    builder.identity(uid(10), entity)
    for edge in range(fund_edges):
        child = uid(10) if edge == fund_edges - 1 else uid(21 + edge)
        builder.fund(uid(20 + edge), ((child, "0.5"),))

    value = builder.finish()
    expected = reference_paths(value)[root]
    expected_known = Fraction(1, 16) if fund_edges == 4 else Fraction(0)
    oracle_known = sum(
        (relative for subject, _, relative, _ in expected if subject == entity), Fraction()
    )
    assert oracle_known == expected_known
    assert sum((relative for _, _, relative, _ in expected), Fraction()) == 1
    assert sum((money for _, _, _, money in expected), Fraction()) == Fraction(29, 4)

    result = calculate_xray(value)
    actual = sorted(
        (
            str(path.entity_id),
            "unknown" if path.unresolved_reason is not None else "entity",
            Fraction(path.relative_coefficient) / 10**72,
            Fraction(cast(Decimal, path.money_coefficient)) / 10**90,
        )
        for path in result.terminal_paths
    )
    assert actual == sorted(
        (str(subject), kind, relative, money) for subject, kind, relative, money in expected
    )
    assert sum((relative for _, _, relative, _ in actual), Fraction()) == 1
    assert sum((money for _, _, _, money in actual), Fraction()) == Fraction(29, 4)
    composition = result.fund_compositions[0]
    assert composition.coverage.value == oracle(expected_known)
    assert composition.unresolved_weight.value == oracle(1 - expected_known)

    depth_limited = [
        path for path in result.terminal_paths if path.unresolved_reason is d.XrayReason.DEPTH_LIMIT
    ]
    if fund_edges == 4:
        assert not depth_limited
        resolved = [path for path in result.terminal_paths if path.entity_id == entity]
        assert len(resolved) == 1 and len(resolved[0].fund_edges) == 4
        assert resolved[0].reporting_value.value is not None
        assert resolved[0].reporting_value.value.amount == oracle(Fraction(29, 64))
    else:
        assert len(depth_limited) == 1 and len(depth_limited[0].fund_edges) == 4
        assert Fraction(depth_limited[0].relative_coefficient) / 10**72 == Fraction(1, 16)
        assert Fraction(cast(Decimal, depth_limited[0].money_coefficient)) / 10**90 == Fraction(
            29, 64
        )


def test_source_graph_preserves_fourth_edge_tail_through_entity_money_publication() -> None:
    # Fixture totals must retain both minimum-quantum roots beside the large direct root.
    with localcontext(Context(prec=256, rounding=ROUND_HALF_EVEN)):
        builder = Builder()
        builder.position(uid(10), "1000000000000000000", position_id=uid(1000))
        builder.position(uid(20), "0.000000000000000001", position_id=uid(1001))
        builder.position(uid(30), "0.000000000000000001", position_id=uid(1002))
        builder.identity(uid(10), uid(110))
        builder.fund(uid(20), ((uid(10), "0.5"),))
        for edge in range(4):
            child = uid(10) if edge == 3 else uid(31 + edge)
            builder.fund(uid(30 + edge), ((child, "0.000000000000000001"),))
        value = builder.finish()

    expected_paths = reference_paths(value)
    exact_entity = sum(
        (
            money
            for paths in expected_paths.values()
            for entity, _, _, money in paths
            if entity == uid(110)
        ),
        Fraction(),
    )
    assert exact_entity == Fraction(10**18) + Fraction(5, 10**19) + Fraction(1, 10**90)
    expected = oracle(exact_entity)
    assert expected == Decimal("1000000000000000000.000000000000000001")
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        lost_tail = Decimal("1e18") + Decimal("5e-19") + Decimal("1e-90")
        rounded_without_tail = lost_tail.quantize(Decimal("1e-18"))
    assert rounded_without_tail == Decimal("1000000000000000000.000000000000000000")
    assert rounded_without_tail != expected

    result = calculate_xray(value)
    entity_paths = [path for path in result.terminal_paths if path.entity_id == uid(110)]
    assert sorted(len(path.fund_edges) for path in entity_paths) == [0, 1, 4]
    assert (
        sum(
            (Fraction(cast(Decimal, path.money_coefficient)) / 10**90 for path in entity_paths),
            Fraction(),
        )
        == exact_entity
    )
    bucket = next(
        row
        for row in result.exposure_buckets
        if row.dimension is d.XrayDimension.COMPANY and row.bucket_key == str(uid(110))
    )
    assert bucket.effective.value is not None
    assert bucket.effective.value.amount == expected
    assert bucket.effective.value.amount.as_tuple().exponent == -18
    expected_total = Fraction(10**18) + Fraction(2, 10**18)
    assert value.portfolio_total.value is not None
    assert Fraction(value.portfolio_total.value.amount) == expected_total
    assert result.portfolio_summary.total.value is not None
    assert result.portfolio_summary.total.value.amount == oracle(expected_total)
    assert (
        sum(
            (
                Fraction(cast(Decimal, path.money_coefficient)) / 10**90
                for path in result.terminal_paths
            ),
            Fraction(),
        )
        == expected_total
    )


def assert_fraction_residual(
    actual: XrayDisplayResidual,
    kind: d.XrayResidualKind,
    parent: Fraction,
    children: tuple[Fraction, ...],
    *,
    rounded_parent: bool,
) -> None:
    """Derive the signed display difference from exact source fractions, independently."""
    assert sum(children, Fraction()) == parent
    rounded_parent_value = Fraction(oracle(parent))
    if not rounded_parent:
        assert rounded_parent_value == parent
    expected = rounded_parent_value - sum(
        (Fraction(oracle(child)) for child in children), Fraction()
    )
    expected_coefficient = expected * 10**18
    assert expected_coefficient.denominator == 1
    assert 2 * abs(expected_coefficient) <= len(children) + int(rounded_parent)
    assert actual.kind is kind
    assert actual.child_count == len(children)
    assert actual.parent_separately_rounded is rounded_parent
    assert Fraction(actual.coefficient) == expected_coefficient
    assert Fraction(actual.value) == expected


def assert_company_fraction_residuals(value: d.XrayInput, result: XrayCalculation) -> None:
    paths = reference_paths(value)
    funds = {mapping.fund_instrument_id for mapping in value.fund_mappings}
    direct_roots = {
        position.root.key
        for position in value.positions
        if position.root.instrument_id not in funds
    }
    entities: dict[UUID, list[tuple[str, Fraction]]] = defaultdict(list)
    cash, unknown, total = Fraction(), Fraction(), Fraction()
    for root, rows in paths.items():
        for entity, kind, _, money in rows:
            total += money
            if entity is not None:
                entities[entity].append((root, money))
            elif kind == "cash":
                cash += money
            else:
                unknown += money
    assert total == sum(
        (
            Fraction(position.reporting_value.value.amount)
            for position in value.positions
            if position.reporting_value.value is not None
        ),
        Fraction(),
    )
    residuals = {row.key: row for row in result.residuals}
    buckets = {
        row.bucket_key: row
        for row in result.exposure_buckets
        if row.dimension is d.XrayDimension.COMPANY
    }
    assert set(buckets) == {str(entity) for entity in entities}
    known = []
    for entity, entity_terms in sorted(entities.items(), key=lambda item: str(item[0])):
        children = tuple(money for _, money in entity_terms)
        effective = sum(children, Fraction())
        direct = sum((money for root, money in entity_terms if root in direct_roots), Fraction())
        indirect = sum(
            (money for root, money in entity_terms if root not in direct_roots), Fraction()
        )
        bucket = buckets[str(entity)]
        for metric, exact in (
            (bucket.direct, direct),
            (bucket.indirect, indirect),
            (bucket.effective, effective),
        ):
            assert metric.value is not None and metric.value.amount == oracle(exact)
        assert bucket.absolute_weight.value == oracle(effective / total)
        assert_fraction_residual(
            residuals[f"company:{entity}:direct_indirect"],
            d.XrayResidualKind.DIRECT_INDIRECT,
            effective,
            (direct, indirect),
            rounded_parent=True,
        )
        assert_fraction_residual(
            residuals[f"company:{entity}:paths"],
            d.XrayResidualKind.PARENT_CHILD,
            effective,
            children,
            rounded_parent=True,
        )
        known.append(effective)
    partition = (*known, cash, unknown)
    dimension = next(row for row in result.dimensions if row.dimension is d.XrayDimension.COMPANY)
    for metric, weight, exact in (
        (dimension.known, dimension.known_weight, sum(known, Fraction())),
        (dimension.cash, dimension.cash_weight, cash),
        (dimension.unresolved, dimension.unresolved_weight, unknown),
    ):
        assert metric.value is not None and metric.value.amount == oracle(exact)
        assert weight.value == oracle(exact / total)
    assert_fraction_residual(
        residuals["company:amount_partition"],
        d.XrayResidualKind.MONEY_PARTITION,
        total,
        partition,
        rounded_parent=False,
    )
    assert_fraction_residual(
        residuals["company:weight_partition"],
        d.XrayResidualKind.WEIGHT_PARTITION,
        Fraction(1),
        tuple(amount / total for amount in partition),
        rounded_parent=False,
    )
    assert all(
        residual.currency
        == (
            None
            if residual.kind is d.XrayResidualKind.WEIGHT_PARTITION
            else value.reporting_currency
        )
        for residual in result.residuals
        if residual.key.startswith("company:")
    )


@pytest.mark.parametrize(
    ("fund_amount", "signed_coefficient"),
    [("0.000000000000000001", 1), ("0.000000000000000003", -1)],
)
def test_fraction_residuals_preserve_direct_indirect_and_parent_child_ties(
    fund_amount: str, signed_coefficient: int
) -> None:
    builder = Builder()
    builder.position(uid(10), "0.000000000000000001")
    fund_root = builder.position(uid(20), fund_amount).root.key
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(111))
    builder.fund(uid(20), ((uid(10), "0.5"), (uid(11), "0.5")))
    value = builder.finish()
    result = calculate_xray(value)
    assert_company_fraction_residuals(value, result)
    residuals = {row.key: row for row in result.residuals}
    for suffix in ("direct_indirect", "paths"):
        assert residuals[f"company:{uid(110)}:{suffix}"].coefficient == signed_coefficient
    amount = Fraction(fund_amount)
    assert_fraction_residual(
        residuals[f"{fund_root}:money_children"],
        d.XrayResidualKind.PARENT_CHILD,
        amount,
        (amount / 2, amount / 2),
        rounded_parent=True,
    )
    assert residuals[f"{fund_root}:money_children"].coefficient == signed_coefficient


@pytest.mark.parametrize(
    ("weight", "signed_coefficient"),
    [("0.000000000000000001", 1), ("0.000000000000000003", -1)],
)
def test_fraction_residuals_preserve_money_weight_and_nested_unit_partitions(
    weight: str, signed_coefficient: int
) -> None:
    builder = Builder()
    root = builder.position(uid(20), "1").root.key
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(111))
    outer = builder.fund(uid(20), ((uid(21), weight),))
    builder.fund(uid(21), ((uid(10), "0.5"), (uid(11), "0.5")))
    value = builder.finish()
    result = calculate_xray(value)
    assert_company_fraction_residuals(value, result)
    residuals = {row.key: row for row in result.residuals}
    for key in ("company:amount_partition", "company:weight_partition"):
        assert residuals[key].coefficient == signed_coefficient
    parent_key = f"{root}/holding:{outer.holdings[0].id}"
    parent = Fraction(weight)
    for key, exact_parent, children in (
        (root, Fraction(1), (parent, 1 - parent)),
        (parent_key, parent, (parent / 2, parent / 2)),
    ):
        for suffix, kind in (
            ("unit_children", d.XrayResidualKind.UNIT_PARENT_CHILD),
            ("money_children", d.XrayResidualKind.PARENT_CHILD),
        ):
            residual = residuals[f"{key}:{suffix}"]
            assert_fraction_residual(residual, kind, exact_parent, children, rounded_parent=True)
            assert residual.currency == (
                None if suffix == "unit_children" else value.reporting_currency
            )
            if key == parent_key:
                assert residual.coefficient == signed_coefficient


@pytest.mark.parametrize(("count", "signed_coefficient"), [(3, 1), (6, -2)])
def test_fraction_residuals_preserve_recurring_absolute_weight_partitions(
    count: int, signed_coefficient: int
) -> None:
    builder = Builder()
    for index in range(count):
        builder.position(uid(10 + index), "1")
        builder.identity(uid(10 + index), uid(110 + index))
    value = builder.finish()
    result = calculate_xray(value)
    assert_company_fraction_residuals(value, result)
    residual = next(row for row in result.residuals if row.key == "company:weight_partition")
    assert residual.coefficient == signed_coefficient


@settings(max_examples=50, deadline=None)
@given(
    st.integers(0, 100),
    st.integers(0, 100),
    st.integers(0, 100),
    st.integers(1, 10000),
    st.integers(0, 10000),
)
def test_bounded_dag_matches_independent_fraction_graph_and_global_metrics(
    first: int, second: int, third: int, amount: int, other_amount: int
) -> None:
    builder = Builder()
    builder.position(uid(20), str(amount), position_id=uid(1000))
    builder.position(uid(30), str(other_amount), position_id=uid(1001))
    builder.position(uid(10), "7", position_id=uid(1002))
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(111))

    def weight(number: int) -> str:
        return str(Decimal(number).scaleb(-2))

    builder.fund(uid(20), ((uid(21), weight(first)), (uid(10), weight((100 - first) // 2))))
    builder.fund(uid(21), ((uid(22), weight(second)), (None, weight((100 - second) // 2))))
    builder.fund(uid(22), ((uid(10), weight(third)), (uid(11), weight(100 - third))))
    builder.fund(uid(30), ((uid(11), "0.4"), (uid(21), "0.6")))
    value = builder.finish()
    expected = reference_paths(value)
    result = calculate_xray(value)
    entities: dict[UUID, Fraction] = defaultdict(Fraction)
    roots_per_entity: dict[UUID, dict[str, Fraction]] = defaultdict(dict)
    total = Fraction(amount + other_amount + 7)
    for root, paths in expected.items():
        actual_paths = [path for path in result.terminal_paths if path.root_key == root]
        actual_relative = sorted(
            (
                str(path.entity_id),
                "cash"
                if path.explicit_cash
                else "unknown"
                if path.unresolved_reason is not None
                else "entity",
                Fraction(path.relative_coefficient) / 10**72,
                Fraction(cast(Decimal, path.money_coefficient)) / 10**90,
            )
            for path in actual_paths
        )
        expected_relative = sorted(
            (str(entity), kind, relative, money) for entity, kind, relative, money in paths
        )
        assert actual_relative == expected_relative
        assert sum((relative for _, _, relative, _ in paths), Fraction()) == 1
        for entity, _, _, money in paths:
            if entity is not None:
                entities[entity] += money
                roots_per_entity[entity][root] = (
                    roots_per_entity[entity].get(root, Fraction()) + money
                )
    exact_hhi = sum((amount * amount for amount in entities.values()), Fraction()) / (total * total)
    duplication = (
        sum(
            (sum(rows.values()) - max(rows.values()) for rows in roots_per_entity.values()),
            Fraction(),
        )
        / total
    )
    assert result.portfolio_summary.hhi.value == oracle(exact_hhi)
    assert result.portfolio_summary.duplicated_exposure.value == oracle(duplication)
    pairs = calculate_overlap_pairs(result, (uid(30), uid(20)))
    fund_vectors: dict[UUID, dict[UUID, Fraction]] = {}
    for instrument, root in (
        (uid(20), f"position:{uid(1000)}"),
        (uid(30), f"position:{uid(1001)}"),
    ):
        vector: dict[UUID, Fraction] = defaultdict(Fraction)
        for entity, _, relative, _ in expected[root]:
            if entity is not None:
                vector[entity] += relative
        fund_vectors[instrument] = vector
    left, right = fund_vectors[uid(20)], fund_vectors[uid(30)]
    exact_overlap = sum(
        (min(left[entity], right[entity]) for entity in left.keys() & right.keys()), Fraction()
    )
    assert pairs[0].overlap.value == oracle(exact_overlap)
    assert encode_xray_result(calculate_xray(reversed_input(value))) == encode_xray_result(result)
    verify_xray_result(value, result)
