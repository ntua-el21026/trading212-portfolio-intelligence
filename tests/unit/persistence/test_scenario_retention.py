"""Retention orchestration boundaries, including shared capacity and publication fencing."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table
from sqlalchemy.orm import Session
from trading212_persistence import scenario_retention as retention
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from trading212_persistence.scenario_models import ScenarioAppliedSensitivityModel
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivityVersionPayloadModel,
)
from trading212_persistence.scenario_source_retention import (
    EVIDENCE_PAYLOAD_COLUMNS,
    OBSERVATION_PAYLOAD_COLUMNS,
    VERSION_PAYLOAD_COLUMNS,
)
from trading212_persistence.source_retention import PayloadCopyCost, SourcePurgeBudget
from trading212_persistence.source_retention_sql import PayloadPurgeResult

NOW = datetime(2026, 9, 15, tzinfo=UTC)


@dataclass(frozen=True)
class Case:
    root: PremiumRunModel
    job: PremiumJobModel
    outbox: PremiumOutboxModel
    capacity: PremiumCapacityModel
    result_id: UUID


def case() -> Case:
    owner, account, run_id, job_id = (uuid4() for _ in range(4))
    root = PremiumRunModel(
        id=run_id,
        owner_id=owner,
        account_id=account,
        kind="scenario",
        expires_at=NOW - timedelta(seconds=1),
        reserved_bytes=1200,
        retained_bytes=300,
    )
    job = PremiumJobModel(
        id=job_id,
        owner_id=owner,
        account_id=account,
        run_id=run_id,
        state="running",
        lease_token=uuid4(),
        lease_expires_at=NOW + timedelta(seconds=30),
        heartbeat_at=NOW,
        deadline_at=NOW + timedelta(minutes=1),
        consumer_id="synthetic",
        consumer_attempts=1,
    )
    outbox = PremiumOutboxModel(
        id=uuid4(),
        owner_id=owner,
        account_id=account,
        job_id=job_id,
        state="published",
        claim_token=None,
        claim_expires_at=None,
        dispatcher_id=None,
    )
    # Another premium run owns the remainder. Scenario cleanup must release only
    # its own reservation and decrement this shared active counter once.
    capacity = PremiumCapacityModel(
        owner_id=owner,
        active_jobs=2,
        reserved_bytes=1700,
        retained_bytes=1000,
    )
    return Case(root, job, outbox, capacity, uuid4())


def test_run_input_and_result_copies_hold_capacity_until_physical_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = case()
    session = Mock(spec=Session)
    session.scalar.side_effect = (
        None,
        value.job,
        value.capacity,
        value.outbox,
        value.result_id,
    )
    monkeypatch.setattr(retention, "premium_attempt", Mock())
    monkeypatch.setattr(retention, "purge_report_premium_copies", lambda *args, **kwargs: True)
    cleared: list[str] = []

    def purge(
        _session: Session, table: Table, *_args: object, **_kwargs: object
    ) -> PayloadPurgeResult:
        cleared.append(table.name)
        return PayloadPurgeResult(
            complete=table.name != "scenario_run_payloads",
            removed_rows=0,
            removed_bytes=0,
        )

    monkeypatch.setattr(retention, "purge_payload_rows", purge)
    assert not retention._purge_run(session, value.root, at=NOW, budget=SourcePurgeBudget())
    assert cleared == [
        "scenario_applied_sensitivities",
        "scenario_components",
        "scenario_results",
        "scenario_run_payloads",
    ]
    marker = session.add.call_args.args[0]
    assert isinstance(marker, PremiumRetentionModel) and marker.completed_at is None
    assert value.job.state == "expired" and value.outbox.state == "dead_letter"
    assert value.job.lease_token is None and value.job.consumer_id is None
    assert value.job.lease_expires_at is value.job.deadline_at is value.job.heartbeat_at is None
    assert value.capacity.active_jobs == 1
    assert (value.root.reserved_bytes, value.root.retained_bytes) == (1200, 300)
    assert (value.capacity.reserved_bytes, value.capacity.retained_bytes) == (1700, 1000)

    session.scalar.side_effect = (marker, value.job, value.capacity, value.result_id)
    monkeypatch.setattr(
        retention,
        "purge_payload_rows",
        lambda *args, **kwargs: PayloadPurgeResult(
            complete=True,
            removed_rows=1,
            removed_bytes=100,
        ),
    )
    assert retention._purge_run(session, value.root, at=NOW, budget=SourcePurgeBudget())
    assert marker.completed_at == NOW
    assert value.capacity.active_jobs == 1
    assert (value.capacity.reserved_bytes, value.capacity.retained_bytes) == (500, 700)
    assert value.root.reserved_bytes == value.root.retained_bytes == 0
    session.scalar.side_effect = (marker,)
    assert retention._purge_run(session, value.root, at=NOW, budget=SourcePurgeBudget())
    assert (
        value.capacity.active_jobs,
        value.capacity.reserved_bytes,
        value.capacity.retained_bytes,
    ) == (1, 500, 700)


def test_incomplete_applied_use_purge_keeps_components_and_all_canonical_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = case()
    session = Mock(spec=Session)
    session.scalar.side_effect = (None, value.job, value.capacity, value.outbox, value.result_id)
    monkeypatch.setattr(retention, "premium_attempt", Mock())
    monkeypatch.setattr(retention, "purge_report_premium_copies", lambda *args, **kwargs: True)
    purge = Mock(return_value=PayloadPurgeResult(complete=False, removed_rows=0, removed_bytes=0))
    monkeypatch.setattr(retention, "purge_payload_rows", purge)
    assert not retention._purge_run(session, value.root, at=NOW, budget=SourcePurgeBudget())
    assert purge.call_count == 1
    assert purge.call_args.args[1] is ScenarioAppliedSensitivityModel.__table__
    assert value.root.retained_bytes == 300
    assert value.capacity.retained_bytes == 1000


def test_owner_locks_follow_source_then_parents_then_premium_and_stop_when_busy() -> None:
    session = Mock(spec=Session)
    session.scalar.side_effect = (True, True, False)
    owner = uuid4()
    assert not retention._lock_owner(session, owner)
    assert [call.args[1]["key"] for call in session.scalar.call_args_list] == [
        f"sources:{owner}",
        f"xray:{owner}",
        f"historical:{owner}",
    ]


def test_scenario_participants_share_existing_allowances_without_an_independent_budget() -> None:
    budget = SourcePurgeBudget(
        captures=2, runs=2, rows_inspected=4, rows_removed=2, bytes_inspected=8, bytes_removed=8
    )
    identifier = uuid4()
    assert budget.enter_capture("risk", identifier)
    assert budget.enter_capture("scenario", identifier)
    assert budget.enter_run("scenario", identifier)
    assert budget.enter_run("historical", identifier)
    assert not budget.enter_capture("xray", identifier)
    assert not budget.enter_run("risk", identifier)
    assert budget.inspect(rows=2)
    copies = (
        PayloadCopyCost(row_id=uuid4(), payload_bytes=4),
        PayloadCopyCost(row_id=uuid4(), payload_bytes=4),
    )
    assert budget.reserve_clear_batch(copies) == tuple(row.row_id for row in copies)
    assert budget.rows_removed == budget.rows_inspected == budget.bytes_removed == 0


def test_closed_payload_inventory_covers_every_nonidentity_column() -> None:
    participants = (
        *retention.SCENARIO_PAYLOADS,
        (ScenarioSensitivityVersionPayloadModel, VERSION_PAYLOAD_COLUMNS),
        (ScenarioSensitivityObservationPayloadModel, OBSERVATION_PAYLOAD_COLUMNS),
        (ScenarioSensitivityEvidencePayloadModel, EVIDENCE_PAYLOAD_COLUMNS),
    )
    # These retained identity columns describe ownership, ordering and the exact
    # immutable parent. All other normalized licensed fields must be charged.
    retained = {
        "id",
        "owner_id",
        "account_id",
        "created_at",
        "result_id",
        "version_id",
        "observation_id",
        "evidence_id",
    }
    for model, columns in participants:
        table = cast(Table, model.__table__)
        expected = set(table.c.keys()) - retained
        assert expected <= set(columns), table.name
        assert set(columns) <= set(table.c.keys()), table.name
        assert len(columns) == len(set(columns)), table.name
