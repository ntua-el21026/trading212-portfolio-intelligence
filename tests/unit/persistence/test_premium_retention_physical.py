"""Independent budget and original-clock regressions for premium maintenance."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from trading212_persistence import premium_retention_runtime as runtime
from trading212_persistence import premium_retention_scan as scan
from trading212_persistence.premium_retention_costs import premium_mutation_cost
from trading212_persistence.premium_retention_models import (
    PremiumRetentionScanModel,
    PremiumRetentionSweepModel,
)
from trading212_persistence.source_retention import PayloadCopyCost, SourcePurgeBudget

NOW = datetime(2026, 9, 15, tzinfo=UTC)


def test_full_32_mib_saved_copy_reserves_second_counter_inspection_exactly() -> None:
    cost = premium_mutation_cost("scenario_results", delete_rows=False)
    assert cost is not None
    row = PayloadCopyCost(
        row_id=uuid4(),
        payload_bytes=32 * 1024 * 1024,
        inspection_rows=cost.mutation_rows,
        payload_inspections=cost.payload_inspections,
    )
    budget = SourcePurgeBudget()
    assert budget.reserve_clear_batch((row,)) == (row.row_id,)
    assert budget.bytes_inspected == 0
    assert budget.bytes_removed == 32 * 1024 * 1024
    assert budget.rows_inspected == 4096 - cost.mutation_rows
    assert budget.rows_removed == 4095


def test_nonfitting_weighted_row_never_consumes_or_skips_later_row() -> None:
    budget = SourcePurgeBudget(rows_inspected=31)
    first = PayloadCopyCost(
        row_id=uuid4(), payload_bytes=3, inspection_rows=32, payload_inspections=2
    )
    later = PayloadCopyCost(row_id=uuid4(), payload_bytes=1)
    assert budget.reserve_clear_batch((first, later)) == ()
    assert budget.rows_inspected == 31 and budget.bytes_removed == 64 * 1024 * 1024


@pytest.mark.parametrize("days,restricted", [(1, True), (30, False)])
def test_current_tightening_uses_original_source_clock(days: int, restricted: bool) -> None:
    session = MagicMock()
    policies = [
        SimpleNamespace(
            effective_at=NOW - timedelta(days=10),
            store_permission="allowed",
            display_permission="allowed",
            retention_days=30,
        ),
        SimpleNamespace(
            effective_at=NOW,
            store_permission="allowed",
            display_permission="allowed",
            retention_days=days,
        ),
    ]
    session.execute.side_effect = [SimpleNamespace(first=lambda row=row: row) for row in policies]
    slot = PremiumRetentionScanModel(owner_id=uuid4(), earliest_deadline=None)
    budget = SourcePurgeBudget(rows_inspected=2)
    assert (
        scan._license(session, slot, uuid4(), uuid4(), NOW - timedelta(days=2), NOW, budget)
        is restricted
    )
    assert slot.earliest_deadline == NOW - timedelta(days=2) + timedelta(days=days)
    assert budget.rows_inspected == 0
    assert all("canonical" not in str(call.args[0]) for call in session.execute.call_args_list)


def test_unfinished_original_proof_cannot_be_evicted_by_next_owner_subject() -> None:
    session = MagicMock()
    owner = uuid4()
    slot = SimpleNamespace(owner_id=owner, subject_id=uuid4(), phase=4)
    session.scalar.return_value = slot
    session.execute.return_value.first.return_value = None
    value = scan.PremiumScanInput(owner, uuid4(), "scenario", NOW, NOW + timedelta(days=30))
    assert scan._slot(session, value, NOW, SourcePurgeBudget(rows_inspected=8)) == "deferred"
    assert session.execute.call_count == 1
    assert session.flush.call_count == 0


def test_keyset_charges_every_healthy_candidate_before_next_page() -> None:
    owner = uuid4()
    roots = [
        SimpleNamespace(
            id=UUID(int=i + 1),
            owner_id=owner,
            kind="risk",
            created_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
        for i in range(80)
    ]
    session = MagicMock()
    session.execute.side_effect = [
        SimpleNamespace(first=lambda root=root: SimpleNamespace(run_id=root.id, owner_id=owner))
        for root in roots
    ] + [SimpleNamespace(first=lambda: None)]
    session.scalar.side_effect = roots
    session.get.return_value = None
    sweep = PremiumRetentionSweepModel(
        scope_id=UUID(int=0), family="risk", deferred=False, policy_epoch=0, evaluated_at=NOW
    )
    positions = []
    purge = MagicMock(side_effect=AssertionError("Healthy metadata cannot authorize deletion"))
    with (
        patch.object(runtime, "open_sweep", return_value=sweep),
        patch.object(runtime, "lock_owner", return_value=True),
        patch.object(runtime, "scan_premium_restriction", return_value="clean"),
    ):
        for _ in range(30):
            budget = SourcePurgeBudget(rows_inspected=24)
            complete = runtime.expire_runs(session, "risk", purge, at=NOW, budget=budget)
            assert 0 <= budget.rows_inspected <= 24
            if complete:
                break
            assert sweep.after_id is not None
            positions.append(sweep.after_id)
        else:
            pytest.fail("Bounded healthy prefix did not progress")
    assert len(positions) > 1 and positions == sorted(set(positions))
    assert session.execute.call_count == 81
    assert all(
        "EXISTS" not in str(call.args[0]) and "NOT IN" not in str(call.args[0])
        for call in session.execute.call_args_list
    )
    assert any("run_id >" in str(call.args[0]) for call in session.execute.call_args_list[1:])
    purge.assert_not_called()


def test_unstarted_proof_at_budget_boundary_keeps_same_absolute_root() -> None:
    owner, identifier = uuid4(), uuid4()
    root = SimpleNamespace(
        id=identifier,
        owner_id=owner,
        kind="risk",
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    candidate = SimpleNamespace(first=lambda: SimpleNamespace(run_id=identifier, owner_id=owner))
    session = MagicMock()
    session.execute.side_effect = [candidate, candidate, SimpleNamespace(first=lambda: None)]
    session.scalar.return_value = root
    session.get.return_value = None
    sweep = PremiumRetentionSweepModel(
        scope_id=UUID(int=0), family="risk", deferred=False, policy_epoch=0, evaluated_at=NOW
    )
    purge = MagicMock(side_effect=AssertionError("No restriction witness"))
    with (
        patch.object(runtime, "open_sweep", return_value=sweep),
        patch.object(runtime, "lock_owner", return_value=True),
        patch.object(runtime, "scan_premium_restriction", side_effect=["pending", "clean"]),
    ):
        assert not runtime.expire_runs(
            session, "risk", purge, at=NOW, budget=SourcePurgeBudget(rows_inspected=24)
        )
        assert sweep.after_id is None and not sweep.deferred
        assert runtime.expire_runs(
            session, "risk", purge, at=NOW, budget=SourcePurgeBudget(rows_inspected=24)
        )
    assert session.execute.call_count == 3
