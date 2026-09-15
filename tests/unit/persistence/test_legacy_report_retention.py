"""Tiny budgets resume actual ordered metadata phases and preserve active owners."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from trading212_persistence import legacy_report_retention as expiry
from trading212_persistence import legacy_report_retention_scan as scanner
from trading212_persistence import report_physical_retention as flags
from trading212_persistence.legacy_report_retention_models import LegacyReportRetentionScanModel
from trading212_persistence.source_retention import SourcePurgeBudget

pytestmark = pytest.mark.unit
AT = datetime(2026, 9, 15, 12, tzinfo=UTC)


def value_and_slot() -> tuple[scanner.LegacyReportScanInput, LegacyReportRetentionScanModel]:
    value = scanner.LegacyReportScanInput(uuid4(), uuid4(), uuid4(), uuid4(), 3, "scenario")
    slot = LegacyReportRetentionScanModel(
        owner_id=value.owner_id,
        account_id=value.account_id,
        input_id=value.input_id,
        run_id=value.run_id,
        historical_input_id=None,
        phase=1,
        cursor=None,
        evidence_id=None,
        evidence_cursor=None,
        policy_epoch=0,
        evaluated_at=AT,
        earliest_deadline=None,
        next_policy_at=None,
    )
    return value, slot


def test_many_physical_flags_drain_in_charged_batches_without_claiming_payload_removal() -> None:
    owner, capture = uuid4(), uuid4()
    pending = [UUID(int=n) for n in range(1, 98)]
    seen: list[UUID] = []
    session = Mock(spec=Session)

    def ids(query: Any) -> tuple[UUID, ...]:
        sql = str(query)
        assert "copy_pending IS true" in sql and "JOIN" not in sql
        assert "ORDER BY report_input_dependencies.id" in sql
        assert {owner, capture} <= set(query.compile().params.values())
        limit = query.compile().params["param_1"]
        return tuple(pending[:limit])

    def update(statement: Any) -> None:
        assert str(statement).lstrip().startswith("UPDATE")
        batch = statement.compile().params["id_1"]
        assert len(batch) <= 512 // 33
        for identifier in batch:
            assert identifier == pending.pop(0)
            seen.append(identifier)

    session.scalars.side_effect, session.execute.side_effect = ids, update
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=80)
        complete = flags.clear_report_source_flags(session, owner, capture, budget=budget)
        assert 0 <= budget.rows_inspected <= 80
        assert budget.rows_removed == 4096 and budget.bytes_removed == 64 * 1024 * 1024
        if complete:
            break
    else:
        pytest.fail("source flags failed to make bounded progress")
    assert seen == [UUID(int=n) for n in range(1, 98)]


def test_flag_batch_waits_before_sql_when_guard_reservation_cannot_fit() -> None:
    session = Mock(spec=Session)
    assert not flags.clear_report_source_flags(
        session, uuid4(), uuid4(), budget=SourcePurgeBudget(rows_inspected=32)
    )
    session.scalars.assert_not_called()
    session.execute.assert_not_called()


def test_interrupted_owner_slot_is_not_evicted_by_another_report() -> None:
    value, slot = value_and_slot()
    slot.input_id = uuid4()
    session = Mock(spec=Session)
    session.scalar.side_effect = (slot, uuid4())
    budget = SourcePurgeBudget(rows_inspected=80)
    assert scanner._slot(session, value, AT, budget) == "deferred"
    assert slot.input_id != value.input_id and slot.phase == 1
    session.add.assert_not_called()
    session.flush.assert_not_called()
    assert budget.rows_inspected == 78


@pytest.mark.parametrize("change", ("epoch", "future", "deadline", "backwards"))
def test_partial_proof_resets_on_original_current_policy_or_clock(change: str) -> None:
    value, slot = value_and_slot()
    slot.phase, slot.cursor = 3, uuid4()
    if change == "future":
        slot.next_policy_at = AT
    if change == "deadline":
        slot.earliest_deadline = AT
    if change == "backwards":
        slot.evaluated_at = AT + timedelta(seconds=1)
    session = Mock(spec=Session)
    session.scalar.side_effect = (slot, 1 if change == "epoch" else 0, None, AT + timedelta(days=1))
    assert scanner._slot(session, value, AT, SourcePurgeBudget(rows_inspected=80)) is slot
    assert slot.phase == 1 and slot.cursor is None and slot.evidence_id is None
    assert slot.evaluated_at == AT and slot.next_policy_at == AT + timedelta(days=1)


def test_lawful_history_evidence_and_scenario_rows_resume_with_no_recursive_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, slot = value_and_slot()
    slot.phase, slot.historical_input_id = 5, uuid4()
    evidence = uuid4()
    root_dependency = UUID(int=1)
    children = [UUID(int=n) for n in range(2, 302)]
    scenario_rows = [UUID(int=n) for n in range(400, 701)]
    inspected: list[UUID] = []
    queries: list[str] = []
    monkeypatch.setattr(scanner, "_slot", lambda *args: slot)
    session = Mock(spec=Session)

    def point(
        session: Session, value: Any, kind: str, subject: UUID, at: Any, budget: SourcePurgeBudget
    ) -> scanner.RestrictionProbe | None:
        cost = 8 if kind in ("root", "parents") else 16
        if budget.rows_inspected < cost:
            return None
        assert budget.inspect(rows=cost)
        if kind not in ("root", "parents"):
            inspected.append(subject)
        return scanner.RestrictionProbe(False, AT + timedelta(days=1))

    def row(query: Any, params: dict[str, Any]) -> Any:
        sql = str(query)
        queries.append(sql)
        assert "RECURSIVE" not in sql and " IS NULL OR " not in sql
        assert "canonical" not in sql and "report_premium_restricted" not in sql
        assert params["owner"] == value.owner_id
        cursor = params.get("cursor")
        if "historical_dependencies" in sql and "evidence_id=:parent" in sql:
            identifiers, registered = children, None
        elif "historical_dependencies" in sql:
            identifiers, registered = [root_dependency], evidence
        elif "scenario_run_sensitivity_versions" in sql:
            identifiers, registered = scenario_rows, None
        else:
            identifiers, registered = [], None
        selected = next(
            (identifier for identifier in identifiers if cursor is None or identifier > cursor),
            None,
        )
        return SimpleNamespace(
            first=lambda: (
                None
                if selected is None
                else SimpleNamespace(id=selected, registered_evidence_id=registered)
            )
        )

    monkeypatch.setattr(scanner, "probe", point)
    session.execute.side_effect = row
    for _ in range(500):
        budget = SourcePurgeBudget(rows_inspected=80)
        outcome = scanner.scan_legacy_report(session, value, at=AT, budget=budget)
        assert 0 <= budget.rows_inspected <= 80
        if outcome == "clean":
            break
        assert outcome == "pending"
    else:
        pytest.fail("saved metadata phases failed to resume")
    assert inspected == [root_dependency, *children, *scenario_rows]
    assert slot.phase == 9
    assert len(queries) >= len(inspected)


def test_exact_point_cost_is_reserved_before_database_witness() -> None:
    value, _ = value_and_slot()
    session = Mock(spec=Session)
    budget = SourcePurgeBudget(rows_inspected=15)
    assert scanner.probe(session, value, "physical", uuid4(), AT, budget) is None
    session.execute.assert_not_called()
    assert budget.rows_inspected == 15


def test_completed_legacy_root_prefix_uses_pending_index_and_never_full_source_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = value_and_slot()
    sweep = SimpleNamespace(id=1, after_id=None, deferred=False)
    candidates = [
        SimpleNamespace(
            id=UUID(int=n),
            owner_id=value.owner_id,
            account_id=value.account_id,
            input_id=UUID(int=1000 + n),
            run_id=value.run_id,
            kind="risk",
        )
        for n in range(1, 301)
    ]
    seen: list[UUID] = []
    session = Mock(spec=Session)

    def scalar(query: Any) -> Any:
        sql = str(query)
        if "pg_try_advisory" in sql:
            return True
        if "legacy_report_retention_sweeps" in sql:
            return sweep
        return None

    def execute(query: Any) -> Any:
        sql = str(query)
        assert "report_premium_restricted" not in sql and "RECURSIVE" not in sql
        if "report_input_premium_dependencies" in sql:
            assert "copy_pending IS true" in sql and "JOIN" not in sql
            after = query.compile().params.get("id_1")
            candidate = next((row for row in candidates if after is None or row.id > after), None)
            if candidate is not None:
                seen.append(candidate.id)
            return SimpleNamespace(first=lambda: candidate)
        return SimpleNamespace(
            first=lambda: SimpleNamespace(
                id=uuid4(),
                created_at=AT - timedelta(days=1),
                contract_version=2,
                expires_at=AT + timedelta(days=1),
            )
        )

    session.scalar.side_effect, session.execute.side_effect = scalar, execute
    monkeypatch.setattr(expiry, "_lock_owner", lambda *args: True)
    monkeypatch.setattr(expiry, "scan_legacy_report", lambda *args, **kwargs: "clean")
    purge = Mock()
    monkeypatch.setattr(expiry, "purge_report_input", purge)
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=80)
        assert expiry.expire_legacy_report_payloads(session, at=AT, budget=budget) == 0
        assert 0 <= budget.rows_inspected <= 80
        if sweep.after_id is None:
            break
    else:
        pytest.fail("healthy legacy prefix did not resume")
    assert seen == [row.id for row in candidates]
    purge.assert_not_called()


def test_pending_report_work_resumes_after_header_clear_without_source_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = value_and_slot()
    sweep = SimpleNamespace(id=1, after_id=None, pending_after_id=None, deferred=False)
    selected = SimpleNamespace(
        id=uuid4(), owner_id=value.owner_id, input_id=value.input_id, reason="source"
    )
    session = Mock(spec=Session)
    session.scalar.side_effect = (True, sweep, True, sweep)
    session.execute.return_value.first.side_effect = (selected, selected, None)
    monkeypatch.setattr(expiry, "_lock_owner", lambda *args: True)
    purge = Mock(side_effect=(False, True))
    scan = Mock(side_effect=AssertionError("pending marker unnecessarily rescanned source graph"))
    monkeypatch.setattr(expiry, "purge_report_input", purge)
    monkeypatch.setattr(expiry, "scan_legacy_report", scan)
    first = SourcePurgeBudget(rows_inspected=80)
    assert expiry.resume_report_retention_work(session, at=AT, budget=first) == 0
    assert sweep.pending_after_id is None
    second = SourcePurgeBudget(rows_inspected=80)
    assert expiry.resume_report_retention_work(session, at=AT, budget=second) == 1
    assert sweep.pending_after_id is None
    assert first.rows_inspected == 77 and second.rows_inspected == 75
    for call in purge.call_args_list:
        assert call.kwargs["input_id"] == value.input_id
        assert "legacy_witness" not in call.kwargs and "projection_witness" not in call.kwargs
    for call in session.execute.call_args_list:
        sql = str(call.args[0])
        assert "completed_at IS NULL" in sql and "ORDER BY report_retention_work.id" in sql
        assert "JOIN" not in sql and "canonical_" not in sql
    scan.assert_not_called()


def test_busy_pending_report_prefix_has_a_persisted_charged_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = SimpleNamespace(id=1, after_id=None, pending_after_id=None, deferred=False)
    rows = [
        SimpleNamespace(id=UUID(int=index), owner_id=uuid4(), input_id=uuid4(), reason="source")
        for index in range(1, 301)
    ]
    session = Mock(spec=Session)
    session.scalar.side_effect = lambda query: True if "pg_try_advisory" in str(query) else sweep
    seen = []

    def candidate(query: Any) -> Any:
        assert "completed_at IS NULL" in str(query) and "JOIN" not in str(query)
        after = query.compile().params.get("id_1")
        row = next((row for row in rows if after is None or row.id > after), None)
        if row is not None:
            seen.append(row.id)
        return SimpleNamespace(first=lambda: row)

    session.execute.side_effect = candidate
    monkeypatch.setattr(expiry, "_lock_owner", lambda *args: False)
    purge = Mock()
    monkeypatch.setattr(expiry, "purge_report_input", purge)
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=80)
        assert expiry.resume_report_retention_work(session, at=AT, budget=budget) == 0
        assert budget.rows_inspected >= 0
        if sweep.pending_after_id is None:
            break
    else:
        pytest.fail("busy pending prefix failed to resume")
    assert seen == [row.id for row in rows]
    purge.assert_not_called()
