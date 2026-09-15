"""Physical refunds, partial progress, fencing and closed cleanup participants."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import Table
from sqlalchemy.orm import Session
from trading212_persistence import projection_job_lifecycle as lifecycle
from trading212_persistence import projection_retention as retention
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from trading212_persistence.source_retention import PayloadCopyCost, SourcePurgeBudget
from trading212_persistence.source_retention_sql import PayloadPurgeResult

pytestmark = pytest.mark.unit
AT = datetime(2026, 9, 15, 12, tzinfo=UTC)
RESERVATION = 33554432


@dataclass(frozen=True)
class Case:
    root: PremiumRunModel
    job: PremiumJobModel
    capacity: PremiumCapacityModel
    outbox: PremiumOutboxModel


def case() -> Case:
    owner, account, run, job = (uuid4() for _ in range(4))
    return Case(
        PremiumRunModel(
            id=run,
            owner_id=owner,
            account_id=account,
            kind="projection",
            created_at=AT - timedelta(days=1),
            expires_at=AT - timedelta(seconds=1),
            reserved_bytes=RESERVATION,
            retained_bytes=0,
        ),
        PremiumJobModel(
            id=job,
            owner_id=owner,
            account_id=account,
            run_id=run,
            state="running",
            lease_token=uuid4(),
            lease_expires_at=AT + timedelta(seconds=30),
            deadline_at=AT + timedelta(seconds=40),
            consumer_attempts=2,
            consumer_id="synthetic",
        ),
        PremiumCapacityModel(
            owner_id=owner, active_jobs=2, reserved_bytes=2 * RESERVATION, retained_bytes=1200
        ),
        PremiumOutboxModel(
            id=uuid4(),
            owner_id=owner,
            account_id=account,
            job_id=job,
            task_name="projections.calculate.v1",
            state="published",
        ),
    )


def test_active_fence_precedes_reports_and_partial_refund_is_actual_sql_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = case()
    session = Mock(spec=Session)
    session.scalar.side_effect = (
        None,
        value.job,
        900,
        value.capacity,
        value.outbox,
        value.capacity,
        600,
    )
    attempt = Mock()
    monkeypatch.setattr(lifecycle, "premium_attempt", attempt)
    visited: list[str] = []

    def reports(*args: object, **kwargs: object) -> bool:
        assert value.job.state == "expired" and value.job.lease_token is None
        assert value.outbox.state == "dead_letter"
        assert value.capacity.active_jobs == 1
        assert value.root.retained_bytes == 900 and value.root.reserved_bytes == 0
        visited.append("reports")
        return True

    def clear(*args: object, **kwargs: object) -> PayloadPurgeResult:
        assert visited == ["reports"]
        visited.append("financial")
        # Logical payload cost is deliberately different from SQL physical bytes.
        return PayloadPurgeResult(complete=False, removed_rows=1, removed_bytes=17)

    monkeypatch.setattr(retention, "purge_report_premium_copies", reports)
    monkeypatch.setattr(retention, "purge_payload_rows", clear)
    monkeypatch.setattr(retention, "_clear_indirect", lambda *args: clear(*args).complete)
    assert not retention._purge_run(
        cast(Session, session), value.root, at=AT, budget=SourcePurgeBudget()
    )
    assert value.root.retained_bytes == 600
    assert value.capacity.retained_bytes == 1800  # other1200 + exact remaining600
    assert value.capacity.reserved_bytes == RESERVATION
    marker = session.add.call_args.args[0]
    assert isinstance(marker, PremiumRetentionModel) and marker.completed_at is None
    attempt.assert_called_once()

    session.scalar.side_effect = (marker, value.job, value.capacity, 0)
    monkeypatch.setattr(retention, "clear_projection_scans", lambda *a, **kw: True)
    monkeypatch.setattr(retention, "_clear_indirect", lambda *a, **kw: True)
    monkeypatch.setattr(retention, "purge_report_premium_copies", lambda *a, **kw: True)
    monkeypatch.setattr(
        retention,
        "purge_payload_rows",
        lambda *a, **kw: PayloadPurgeResult(complete=True, removed_rows=0, removed_bytes=0),
    )
    assert retention._purge_run(
        cast(Session, session), value.root, at=AT + timedelta(seconds=1), budget=SourcePurgeBudget()
    )
    assert marker.completed_at == AT + timedelta(seconds=1)
    assert value.root.retained_bytes == 0 and value.capacity.retained_bytes == 1200
    assert value.capacity.active_jobs == 1
    attempt.assert_called_once()


def test_report_backlog_keeps_all_projection_bytes_after_job_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = case()
    session = Mock(spec=Session)
    session.scalar.side_effect = (None, value.job, 901, value.capacity, value.outbox)
    monkeypatch.setattr(lifecycle, "premium_attempt", Mock())
    monkeypatch.setattr(retention, "purge_report_premium_copies", lambda *a, **kw: False)
    clear = Mock()
    monkeypatch.setattr(retention, "purge_payload_rows", clear)
    assert not retention._purge_run(
        cast(Session, session), value.root, at=AT, budget=SourcePurgeBudget()
    )
    assert value.job.state == "expired" and value.root.retained_bytes == 901
    assert value.capacity.retained_bytes == 2101
    clear.assert_not_called()


def test_completion_requires_zero_measured_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    value = case()
    value.job.state = "cancelled"
    value.root.reserved_bytes, value.root.retained_bytes = 0, 600
    session = Mock(spec=Session)
    session.scalar.side_effect = (None, value.job, value.capacity, 1)
    monkeypatch.setattr(retention, "purge_report_premium_copies", lambda *a, **kw: True)
    monkeypatch.setattr(
        retention,
        "purge_payload_rows",
        lambda *a, **kw: PayloadPurgeResult(complete=True, removed_rows=0, removed_bytes=0),
    )
    monkeypatch.setattr(retention, "_clear_indirect", lambda *a, **kw: True)
    with pytest.raises(RuntimeError, match="physical copies"):
        retention._purge_run(cast(Session, session), value.root, at=AT, budget=SourcePurgeBudget())
    assert session.add.call_args.args[0].completed_at is None


def test_closed_payload_inventory_includes_every_purgeable_financial_column() -> None:
    expected = {
        "projection_distribution_quantiles",
        "projection_histogram_bins",
        "projection_goal_shortfall_quantiles",
        "projection_distributions",
        "projection_histograms",
        "projection_goal_analyses",
        "projection_zero_pivots",
        "projection_point_assets",
        "projection_points",
        "projection_paths",
        "projection_chunks",
        "projection_run_allocations",
        "projection_calendar_boundaries",
        "projection_run_pauses",
        "projection_run_schedule_entries",
        "projection_source_proofs",
        "projection_inputs",
    }
    actual = {model.__tablename__ for model, _ in retention.PROJECTION_PAYLOADS}
    assert actual == expected
    for model, columns in retention.PROJECTION_PAYLOADS:
        assert set(columns) == set(model.__table__.columns.keys()) - {
            "id",
            "owner_id",
            "account_id",
            "created_at",
        }
    order = [model.__tablename__ for model, _ in retention.PROJECTION_PAYLOADS]
    for child, parent in (
        ("projection_histogram_bins", "projection_histograms"),
        ("projection_distribution_quantiles", "projection_distributions"),
        ("projection_goal_shortfall_quantiles", "projection_goal_analyses"),
        ("projection_point_assets", "projection_points"),
        ("projection_points", "projection_paths"),
        ("projection_paths", "projection_chunks"),
    ):
        assert order.index(child) < order.index(parent)


def test_scope_never_drops_owner_account_or_actual_result_membership() -> None:
    root = case().root
    for model, _ in retention.PROJECTION_PAYLOADS:
        predicate = retention._scope(cast(Table, model.__table__), root)
        text = str(predicate)
        params = tuple(predicate.compile().params.values())
        assert "owner_id" in text and "account_id" in text
        assert root.owner_id in params and root.account_id in params and root.id in params


def test_busy_owner_is_skipped_without_new_budget_or_execution_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_lock_owner = retention._lock_owner
    first, second = case(), case()
    session = Mock(spec=Session)
    session.execute.return_value.first.side_effect = (
        SimpleNamespace(id=first.root.id, owner_id=first.root.owner_id),
        SimpleNamespace(id=second.root.id, owner_id=second.root.owner_id),
        None,
    )
    session.scalar.side_effect = (second.root, None)
    sweep = SimpleNamespace(after_id=None, deferred=False)
    monkeypatch.setattr(retention, "begin_sweep", lambda *args, **kwargs: sweep)
    monkeypatch.setattr(retention, "end_sweep", lambda *args: not sweep.deferred)
    monkeypatch.setattr(retention, "_lock_owner", Mock(side_effect=(False, True)))
    purge = Mock(return_value=True)
    monkeypatch.setattr(retention, "_purge_run", purge)
    budget = SourcePurgeBudget()
    assert not retention.expire_projection_payloads(cast(Session, session), at=AT, budget=budget)
    purge.assert_called_once_with(session, second.root, at=AT, budget=budget, reason=None)
    locks = Mock(spec=Session)
    locks.scalar.side_effect = (True, True, False)
    assert not actual_lock_owner(cast(Session, locks), first.root.owner_id)
    keys = [call.args[1]["key"].split(":", 1)[0] for call in locks.scalar.call_args_list]
    assert keys == ["sources", "xray", "historical"]


def test_projection_uses_existing_global_purge_limits_and_stops_before_mutation() -> None:
    budget = SourcePurgeBudget(captures=1, runs=1, rows_inspected=9)
    value = case()
    assert budget.enter_capture("projection", value.root.id)
    assert budget.enter_capture("projection", value.root.id)
    assert not budget.enter_capture("scenario", uuid4())
    session = Mock(spec=Session)
    assert not retention._purge_run(cast(Session, session), value.root, at=AT, budget=budget)
    session.add.assert_not_called()
    session.execute.assert_not_called()
    with pytest.raises(ValueError):
        retention.purge_projection_source_copies(
            cast(Session, session),
            value.root.owner_id,
            cast(retention.ProjectionParentKind, "arbitrary"),
            uuid4(),
            at=AT,
            budget=budget,
        )
    tiny = SourcePurgeBudget(bytes_removed=1)
    assert tiny.reserve_clear_batch((PayloadCopyCost(row_id=uuid4(), payload_bytes=2),)) == ()
