from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st
from trading212_domain import CurrencyCode, DomainError, canonical_json, exact_decimal
from trading212_domain.targets import (
    TargetCatalog,
    TargetContent,
    TargetHoldingMapping,
    TargetIdentifier,
    TargetIdentifierKind,
    TargetMappingState,
    TargetNode,
    TargetNodeKind,
    validate_target_content,
)

pytestmark = pytest.mark.property
AS_OF = datetime(2026, 9, 7, tzinfo=UTC)
EUR = CurrencyCode("EUR")
UNRESOLVED = TargetHoldingMapping(
    TargetMappingState.UNRESOLVED,
    requested_identifier=TargetIdentifier(
        TargetIdentifierKind.PROVIDER_KEY, "unmapped", "synthetic"
    ),
    reason="Unresolved synthetic mapping",
)


def content_for_weights(weights: tuple[Decimal, ...]) -> TargetContent:
    return TargetContent(
        tuple(
            TargetNode(
                str(index), None, TargetNodeKind.HOLDING, str(index), index, weight, UNRESOLVED
            )
            for index, weight in enumerate(weights)
        )
    )


@given(parts=st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=20))
def test_explicit_normalization_conserves_exact_weight_and_is_idempotent(parts: list[int]) -> None:
    with localcontext() as context:
        context.prec = 80
        total = sum(parts)
        weights = tuple((Decimal(part) / total).quantize(Decimal("1e-18")) for part in parts)
    content = content_for_weights(weights)
    result = validate_target_content(
        content, reporting_currency=EUR, effective_at=AS_OF, catalog=TargetCatalog(), normalize=True
    )
    assert result.valid
    with localcontext() as context:
        context.prec = 80
        assert sum(node.weight for node in result.content.nodes) == 1
    replay = validate_target_content(
        result.content,
        reporting_currency=EUR,
        effective_at=AS_OF,
        catalog=TargetCatalog(),
        normalize=True,
    )
    assert replay.valid
    assert replay.adjustments == ()
    assert result.result_digest == replay.result_digest


@given(
    units=st.integers(min_value=0, max_value=10**18),
    precision=st.integers(min_value=2, max_value=100),
)
def test_input_order_and_ambient_precision_preserve_canonical_validation(
    units: int, precision: int
) -> None:
    with localcontext() as context:
        context.prec = 80
        first = Decimal(units).scaleb(-18)
        content = content_for_weights((first, 1 - first))
    expected = validate_target_content(
        content, reporting_currency=EUR, effective_at=AS_OF, catalog=TargetCatalog()
    )
    with localcontext() as context:
        context.prec = precision
        actual = validate_target_content(
            replace(content, nodes=tuple(reversed(content.nodes))),
            reporting_currency=EUR,
            effective_at=AS_OF,
            catalog=TargetCatalog(),
        )
    assert expected.valid and actual.valid
    assert canonical_json(actual) == canonical_json(expected)


@given(value=st.integers(min_value=10**20, max_value=10**38 - 1), negative=st.booleans())
def test_database_integer_capacity_is_independent_of_unused_fractional_scale(
    value: int, negative: bool
) -> None:
    signed = -value if negative else value
    for representation in (signed, str(signed), Decimal(signed)):
        with pytest.raises(DomainError, match="NUMERIC"):
            exact_decimal(representation)


@given(value=st.integers(min_value=-(10**20 - 1), max_value=10**20 - 1))
def test_every_twenty_digit_integer_fits_numeric_38_18(value: int) -> None:
    assert exact_decimal(value) == Decimal(value)


@given(
    depth=st.integers(min_value=1, max_value=8),
    weight_units=st.integers(min_value=1, max_value=999_999),
)
def test_deep_products_reconstruct_from_factors_without_leaf_renormalization(
    depth: int, weight_units: int
) -> None:
    with localcontext() as context:
        context.prec = 160
        weight = Decimal(weight_units).scaleb(-6)
        other = 1 - weight
        nodes: list[TargetNode] = []
        for index in range(depth):
            parent = f"g{index - 1}" if index else None
            nodes.append(
                TargetNode(
                    f"side{index}", parent, TargetNodeKind.HOLDING, "side", 1, other, UNRESOLVED
                )
            )
            kind = TargetNodeKind.GROUP if index < depth - 1 else TargetNodeKind.HOLDING
            nodes.append(
                TargetNode(
                    f"g{index}",
                    parent,
                    kind,
                    "path",
                    0,
                    weight,
                    None if kind is TargetNodeKind.GROUP else UNRESOLVED,
                )
            )
        exact = weight**depth
    result = validate_target_content(
        TargetContent(tuple(nodes)),
        reporting_currency=EUR,
        effective_at=AS_OF,
        catalog=TargetCatalog(),
    )
    assert result.valid
    with localcontext() as context:
        context.prec = 160
        leaf = next(item for item in result.flattened_nodes if item.node.key == f"g{depth - 1}")
        assert leaf.effective_weight == exact.quantize(Decimal("1e-18"))
        assert leaf.path_factors == (weight,) * depth
        total = sum(
            item.effective_weight
            for item in result.flattened_nodes
            if item.node.kind is not TargetNodeKind.GROUP
        )
        assert result.effective_weight_rounding_residual is not None
        assert total + result.effective_weight_rounding_residual == 1
