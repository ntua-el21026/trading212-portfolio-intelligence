"""Checkpoint work stays bounded without changing the requested financial population."""

from dataclasses import replace
from decimal import Decimal

import pytest
from trading212_analytics import projection as kernel
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionInput,
)
from trading212_domain.projection_result import ProjectionChunk
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_domain.values import CurrencyCode, Money
from trading212_worker import projection_process as process

from tests.unit.persistence.projection_codec_factories import capture

pytestmark = pytest.mark.unit


def dense_inputs() -> ProjectionInput:
    value = capture(observed=False, goal=False, sensitive=False).inputs
    assumptions = ProjectionAssumptions(
        assets=tuple(
            ProjectionAsset(
                key=f"document-asset-{index:02d}",
                annual_mean_log_return=Decimal(0),
                annual_volatility=Decimal(0),
                weight=Decimal("0.1"),
            )
            for index in range(10)
        ),
        correlation=tuple(
            tuple(Decimal(int(left == right)) for right in range(10)) for left in range(10)
        ),
        reporting_currency=CurrencyCode("EUR"),
        annual_tax_drag=Decimal(0),
    )
    return replace(
        value,
        assumptions=assumptions,
        initial=replace(value.initial, value=Money(Decimal("100"), CurrencyCode("EUR"))),
        schedule=replace(
            value.schedule,
            base_monthly=Money(Decimal(0), CurrencyCode("EUR")),
            annual_growth=Decimal(0),
            paused_months=(),
            entries=(),
        ),
        allocation=tuple(
            ProjectionAllocation(key=asset.key, weight=asset.weight) for asset in assumptions.assets
        ),
        paths=42,
        months=120,
        retained_months=(*range(111), 120),
    )


def test_dense_checkpoint_limits_work_without_reducing_any_requested_path_or_point() -> None:
    inputs = dense_inputs()
    limit = process._checkpoint_path_limit(inputs)
    assert limit == 1
    assert (
        inputs.paths,
        inputs.months,
        len(inputs.retained_months),
        len(inputs.assumptions.assets),
    ) == (
        42,
        120,
        112,
        10,
    )
    rows_per_path = len(inputs.retained_months) * len(inputs.assumptions.assets)
    assert limit * rows_per_path <= max(1024, rows_per_path)


def test_small_checkpoint_keeps_original_32_path_ceiling() -> None:
    inputs = capture(observed=False, goal=False, sensitive=False).inputs
    assert process._checkpoint_path_limit(inputs) == 32


def test_one_path_is_indivisible_when_its_own_asset_rows_exceed_the_work_target() -> None:
    inputs = replace(dense_inputs(), retained_months=tuple(range(121)))
    assert len(inputs.retained_months) * len(inputs.assumptions.assets) > 1024
    assert process._checkpoint_path_limit(inputs) == 1


def test_different_checkpointing_and_legacy_resume_have_identical_complete_canonical_bytes() -> (
    None
):
    inputs = dense_inputs()
    expected = kernel.calculate_projection(inputs)
    expected_bytes = projection_canonical_bytes(expected)
    limit = process._checkpoint_path_limit(inputs)
    chunks = tuple(
        kernel.calculate_projection_chunk(inputs, start, min(limit, inputs.paths - start))
        for start in range(0, inputs.paths, limit)
    )
    assert len(chunks) == 42
    assert tuple(path.index for chunk in chunks for path in chunk.paths) == tuple(range(42))
    assert all(len(path.points) == 112 for chunk in chunks for path in chunk.paths)
    assert projection_canonical_bytes(kernel.finalize_projection(inputs, chunks)) == expected_bytes
    # The old maximal first checkpoint remains legal evidence after an upgrade.
    # Resume publishes only its missing absolute paths using the new granularity.
    legacy = kernel.calculate_projection_chunk(inputs, 0, 32)
    resumed: tuple[ProjectionChunk, ...] = (legacy, *chunks[32:])
    inventory = process._Inventory(inputs)
    for chunk in resumed:
        inventory.add(chunk, projection_canonical_bytes(chunk))
    inventory.verify_result(expected)
    assert inventory.chunks == 11 and len(inventory.paths) == 42
    assert inventory.bytes_used <= 32 * 1024 * 1024
    assert projection_canonical_bytes(kernel.finalize_projection(inputs, resumed)) == expected_bytes
    for variant in expected.variants:
        for path in variant.paths:
            for point in path.points:
                assert point.nominal == point.real == Decimal("100")
                assert all(asset.value == Decimal("10") for asset in point.assets)
