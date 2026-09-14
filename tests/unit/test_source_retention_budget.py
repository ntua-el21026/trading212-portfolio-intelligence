"""Boundary contracts for the shared expiry allowance; no database fixture."""

from __future__ import annotations

from uuid import UUID

import pytest
from trading212_persistence.source_retention import (
    MAX_PURGE_BATCH_ROWS,
    MAX_PURGE_BYTES,
    PayloadCopyCost,
    PurgeFamily,
    SourcePurgeBudget,
)


def _cost(identifier: int, size: int) -> PayloadCopyCost:
    return PayloadCopyCost(row_id=UUID(int=identifier), payload_bytes=size)


def _remaining(budget: SourcePurgeBudget) -> tuple[int, ...]:
    return (
        budget.captures,
        budget.runs,
        budget.rows_inspected,
        budget.rows_removed,
        budget.bytes_inspected,
        budget.bytes_removed,
    )


def test_source_and_both_analytics_families_share_one_allowance() -> None:
    budget = SourcePurgeBudget(captures=2, runs=2)
    families: tuple[PurgeFamily, ...] = ("historical", "xray")
    for family in families:
        assert budget.enter_capture(family, UUID(int=1))
        assert budget.enter_run(family, UUID(int=2))
    assert not budget.enter_capture("historical", UUID(int=3))
    assert not budget.enter_run("xray", UUID(int=4))
    # Returning to a phase in the same invocation does not claim another parent.
    assert budget.enter_capture("historical", UUID(int=1))
    assert budget.enter_run("xray", UUID(int=2))
    for identifier in (10, 11, 12):
        assert budget.inspect(rows=1)
        assert budget.reserve_clear_batch((_cost(identifier, 7),)) == (UUID(int=identifier),)
    assert _remaining(budget) == (0, 0, 4090, 4093, MAX_PURGE_BYTES - 21, MAX_PURGE_BYTES - 21)


def test_largest_legal_document_progresses_and_copies_are_charged_separately() -> None:
    budget = SourcePurgeBudget()
    document_size = 32 * 1024 * 1024
    assert budget.inspect(rows=2)
    assert budget.reserve_clear_batch((_cost(1, document_size), _cost(2, document_size))) == (
        UUID(int=1),
        UUID(int=2),
    )
    assert budget.bytes_inspected == budget.bytes_removed == 0
    assert budget.rows_inspected == 4092
    assert budget.rows_removed == 4094
    assert budget.reserve_clear_batch((_cost(3, 1),)) == ()


def test_pending_prefix_is_not_skipped_for_a_smaller_later_row() -> None:
    budget = SourcePurgeBudget(bytes_inspected=10, bytes_removed=10)
    assert budget.inspect(rows=3)
    assert budget.reserve_clear_batch((_cost(1, 7), _cost(2, 4), _cost(3, 1))) == (UUID(int=1),)
    assert budget.bytes_inspected == budget.bytes_removed == 3
    before = _remaining(budget)
    assert budget.reserve_clear_batch((_cost(2, 4), _cost(3, 1))) == ()
    assert _remaining(budget) == before
    resumed = SourcePurgeBudget()
    assert resumed.inspect(rows=2)
    assert resumed.reserve_clear_batch((_cost(2, 4), _cost(3, 1))) == (UUID(int=2), UUID(int=3))


@pytest.mark.parametrize(
    "limited",
    ["rows_inspected", "rows_removed", "bytes_inspected", "bytes_removed"],
)
def test_each_remaining_counter_independently_limits_clear_work(limited: str) -> None:
    budget = SourcePurgeBudget(**{limited: 1})
    assert budget.reserve_clear_batch((_cost(1, 1), _cost(2, 1))) == (UUID(int=1),)
    assert getattr(budget, limited) == 0
    before = _remaining(budget)
    assert budget.reserve_clear_batch((_cost(2, 1),)) == ()
    assert _remaining(budget) == before


def test_repeated_metadata_inspection_is_charged_even_when_payload_cannot_fit() -> None:
    budget = SourcePurgeBudget(rows_inspected=3, bytes_inspected=1, bytes_removed=1)
    cost = _cost(1, 2)
    for remaining in (2, 1, 0):
        assert budget.inspect(rows=1)
        assert budget.reserve_clear_batch((cost,)) == ()
        assert budget.rows_inspected == remaining
    assert budget.metadata_limit == 0
    assert not budget.inspect(rows=1)
    assert budget.rows_removed == 4096


def test_metadata_row_limit_is_bounded_before_query() -> None:
    budget = SourcePurgeBudget(rows_inspected=513)
    assert budget.metadata_limit == MAX_PURGE_BATCH_ROWS
    assert budget.inspect(rows=512)
    assert budget.metadata_limit == 1
    assert budget.inspect(rows=1)
    assert budget.metadata_limit == 0


def test_over_budget_inspection_has_no_partial_charge() -> None:
    budget = SourcePurgeBudget(rows_inspected=1, bytes_inspected=1)
    before = _remaining(budget)
    assert not budget.inspect(rows=1, payload_bytes=2)
    assert not budget.inspect(rows=2, payload_bytes=1)
    assert _remaining(budget) == before


def test_oversized_legacy_payload_stays_pending_without_byte_loading() -> None:
    budget = SourcePurgeBudget()
    assert budget.inspect(rows=1)
    before = _remaining(budget)
    assert budget.reserve_clear_batch((_cost(1, MAX_PURGE_BYTES + 1),)) == ()
    assert _remaining(budget) == before


def test_zero_payload_tombstone_still_consumes_physical_removal_allowance() -> None:
    budget = SourcePurgeBudget(bytes_inspected=0, bytes_removed=0, rows_removed=1)
    assert budget.inspect(rows=1)
    assert budget.reserve_clear_batch((_cost(1, 0),)) == (UUID(int=1),)
    assert budget.rows_removed == 0
    assert budget.bytes_inspected == budget.bytes_removed == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("captures", 101),
        ("runs", -1),
        ("rows_removed", 4097),
        ("bytes_inspected", MAX_PURGE_BYTES + 1),
    ],
)
def test_invalid_initial_allowances_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="bounded nonnegative"):
        SourcePurgeBudget(**{field: value})


def test_duplicate_or_oversized_batch_fails_before_any_charge() -> None:
    budget = SourcePurgeBudget()
    before = _remaining(budget)
    with pytest.raises(ValueError, match="once"):
        budget.reserve_clear_batch((_cost(1, 1), _cost(1, 1)))
    with pytest.raises(ValueError, match="batch size"):
        budget.reserve_clear_batch(tuple(_cost(n, 0) for n in range(513)))
    assert _remaining(budget) == before


def test_premium_and_existing_families_share_run_capacity() -> None:
    families: tuple[PurgeFamily, ...] = ("historical", "xray", "report", "export", "alert", "risk")
    budget = SourcePurgeBudget(runs=len(families))
    identifier = UUID(int=1)
    for family in families:
        assert budget.enter_run(family, identifier)
    assert budget.runs == 0
    assert budget.enter_run("risk", identifier)
    assert not budget.enter_run("risk", UUID(int=2))
    assert not budget.enter_run("historical", UUID(int=2))
