"""REPORT-only policy checks preserve the separate saved projection payloads."""

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from trading212_persistence import projection_report_retention as retention
from trading212_persistence import projection_retention_scan as scanner
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.unit.persistence.test_projection_retention_scan import AT, root_and_scan

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("denied", ("pinned", "current"))
@pytest.mark.parametrize("report", (False, True))
def test_report_permission_is_additional_to_unchanged_projection_rights(
    monkeypatch: pytest.MonkeyPatch, denied: str, report: bool
) -> None:
    _, scan = root_and_scan()
    scan.purpose = "report_expiry" if report else "expiry"
    identifier = uuid4()
    pinned = SimpleNamespace(
        id=identifier,
        provider_id=uuid4(),
        effective_at=AT - timedelta(days=2),
        store_permission="allowed",
        display_permission="allowed",
        report_permission="denied" if denied == "pinned" else "allowed",
        retention_days=30,
    )
    current = SimpleNamespace(
        id=uuid4(),
        provider_id=pinned.provider_id,
        effective_at=AT,
        store_permission="allowed",
        display_permission="allowed",
        report_permission="denied" if denied == "current" else "allowed",
        retention_days=30,
    )
    rows = iter((pinned, current))
    queries: list[str] = []

    def read(session: Session, query: Any, budget: SourcePurgeBudget) -> Any:
        assert budget.inspect(rows=1)
        sql = str(query)
        queries.append(sql)
        assert "report_permission" in sql and "canonical_" not in sql
        assert scan.owner_id in query.compile().params.values()
        return next(rows)

    monkeypatch.setattr(scanner, "_row", read)
    budget = SourcePurgeBudget(rows_inspected=4)
    deadline = scanner._license_until(Mock(spec=Session), scan, identifier, AT, AT, budget)
    assert deadline == (None if report else AT + timedelta(days=30))
    assert 4 - budget.rows_inspected == len(queries)


@pytest.mark.parametrize("change", ("epoch", "future_activation", "backwards_clock"))
def test_report_clean_cache_is_invalidated_by_current_policy_and_clock(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root, scan = root_and_scan()
    scan.purpose, scan.phase = "report_expiry", "clean"
    scan.earliest_deadline = AT - timedelta(seconds=1)
    if change == "future_activation":
        scan.next_policy_at = AT
    if change == "backwards_clock":
        scan.evaluated_at = AT + timedelta(seconds=1)
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    session.scalar.side_effect = (1 if change == "epoch" else 0, scan)
    reset = Mock(return_value=True)

    def restore(
        session: Session, value: Any, epoch: int, at: Any, budget: SourcePurgeBudget
    ) -> bool:
        reset()
        value.earliest_deadline, value.next_policy_at = None, None
        value.policy_epoch, value.evaluated_at, value.phase = epoch, at, "clean"
        return True

    monkeypatch.setattr(scanner, "_reset", restore)
    assert (
        scanner.scan_projection_sources(
            session, root, at=AT, budget=SourcePurgeBudget(), report=True
        )
        == "clean"
    )
    reset.assert_called_once()
    query = session.scalar.call_args_list[1].args[0]
    assert query.compile().params["purpose_1"] == "report_expiry"


def test_report_scan_cannot_consume_or_replace_an_unfinished_source_match() -> None:
    root, _ = root_and_scan()
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    with pytest.raises(ValueError, match="own untargeted"):
        scanner.scan_projection_sources(
            session,
            root,
            at=AT,
            budget=SourcePurgeBudget(),
            report=True,
            target=("price", uuid4()),
        )
    session.scalar.assert_not_called()


@pytest.mark.parametrize("result", ("pending", "clean", "restricted"))
def test_report_expiry_only_purges_reports_after_a_complete_restriction(
    monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    root, _ = root_and_scan()
    original = (root.reserved_bytes, root.retained_bytes, root.expires_at)
    sweep = SimpleNamespace(after_id=None, deferred=False)
    session = Mock(spec=Session)
    session.execute.return_value.first.side_effect = (
        SimpleNamespace(id=root.id, owner_id=root.owner_id),
        None,
    )
    session.scalar.side_effect = (root, uuid4(), None, None)
    witness_id = uuid4()
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        restriction_kind="price", restriction_id=witness_id
    )
    begin = Mock(return_value=sweep)
    monkeypatch.setattr(retention, "begin_sweep", begin)
    monkeypatch.setattr(retention, "end_sweep", lambda *args: True)
    monkeypatch.setattr(retention, "_lock_owner", lambda *args: True)
    scan = Mock(return_value=result)
    monkeypatch.setattr(retention, "scan_projection_sources", scan)
    purge = Mock(return_value=True)
    monkeypatch.setattr(retention, "purge_report_premium_copies", purge)
    budget = SourcePurgeBudget(rows_inspected=96)
    complete = retention.expire_projection_report_payloads(session, at=AT, budget=budget)
    assert complete is (result != "pending")
    assert begin.call_args.kwargs["report"] is True
    assert scan.call_args.kwargs["report"] is True
    assert scan.call_args.kwargs["budget"] is budget
    if result == "restricted":
        purge.assert_called_once_with(
            session,
            root.owner_id,
            root.id,
            at=AT,
            budget=budget,
            projection_witness=("price", witness_id),
        )
    else:
        purge.assert_not_called()
    assert (root.reserved_bytes, root.retained_bytes, root.expires_at) == original
    session.add.assert_not_called()
    session.delete.assert_not_called()
    assert sweep.after_id == (None if result == "pending" else root.id)


def test_pending_copy_resumes_without_authorizing_an_unmarked_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = root_and_scan()
    pending, unmarked, marker = uuid4(), uuid4(), uuid4()
    sweep = SimpleNamespace(after_id=None, deferred=False)
    session = Mock(spec=Session)
    candidate = SimpleNamespace(id=root.id, owner_id=root.owner_id)
    session.execute.return_value.first.side_effect = (candidate, candidate, None)
    session.scalar.side_effect = (root, pending, marker, root, unmarked, None, None)
    monkeypatch.setattr(retention, "begin_sweep", lambda *args, **kwargs: sweep)
    monkeypatch.setattr(retention, "end_sweep", lambda *args: True)
    monkeypatch.setattr(retention, "_lock_owner", lambda *args: True)
    scan = Mock(return_value="clean")
    exact_purge, all_copies = Mock(return_value=True), Mock()
    monkeypatch.setattr(retention, "scan_projection_sources", scan)
    monkeypatch.setattr(retention, "purge_report_input", exact_purge)
    monkeypatch.setattr(retention, "purge_report_premium_copies", all_copies)
    budget = SourcePurgeBudget(rows_inspected=80)
    assert retention.expire_projection_report_payloads(session, at=AT, budget=budget)
    exact_purge.assert_called_once_with(
        session, owner=root.owner_id, input_id=pending, reason="source", at=AT, budget=budget
    )
    scan.assert_called_once_with(session, root, at=AT, budget=budget, report=True)
    all_copies.assert_not_called()
    assert sweep.after_id == root.id
    marker_query = session.scalar.call_args_list[2].args[0]
    assert {root.owner_id, pending} <= set(marker_query.compile().params.values())
    assert "completed_at IS NULL" in str(marker_query)
    assert 0 < budget.rows_inspected < 80


def test_long_reportless_prefix_is_charged_and_resumes_without_private_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, _ = root_and_scan()
    roots = [
        PremiumRunModel(
            id=UUID(int=index),
            owner_id=original.owner_id,
            account_id=original.account_id,
            kind="projection",
            created_at=AT,
            expires_at=AT + timedelta(days=1),
        )
        for index in range(1, 651)
    ]
    sweep = SimpleNamespace(after_id=None, deferred=False)
    monkeypatch.setattr(retention, "begin_sweep", lambda *args, **kwargs: sweep)
    monkeypatch.setattr(retention, "end_sweep", lambda *args: True)
    monkeypatch.setattr(retention, "_lock_owner", lambda *args: True)
    session = Mock(spec=Session)
    queries: list[str] = []
    seen: list[UUID] = []

    def candidate(query: Any) -> Any:
        sql = str(query)
        queries.append(sql)
        assert "EXISTS" not in sql and "JOIN" not in sql and "canonical_" not in sql
        assert "report_premium_restricted" not in sql
        after = query.compile().params.get("id_1")
        index = 0 if after is None else after.int
        row = None if index == len(roots) else roots[index]
        if row is not None:
            seen.append(row.id)
        return SimpleNamespace(first=lambda: row)

    def scalar(query: Any) -> Any:
        queries.append(str(query))
        values = query.compile().params
        assert original.owner_id in values.values()
        assert "canonical_" not in str(query) and "projection_history_links" not in str(query)
        if query.column_descriptions[0]["entity"] is PremiumRunModel:
            return roots[values["id_1"].int - 1]
        return None

    session.execute.side_effect, session.scalar.side_effect = candidate, scalar
    purge = Mock()
    monkeypatch.setattr(retention, "purge_report_premium_copies", purge)
    scan = Mock()
    monkeypatch.setattr(retention, "scan_projection_sources", scan)
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=96)
        before = len(queries)
        if retention.expire_projection_report_payloads(
            session, at=AT, owner=original.owner_id, budget=budget
        ):
            break
        assert len(queries) - before <= 96 - budget.rows_inspected
    else:
        pytest.fail("bounded report sweep did not clear its healthy prefix")
    assert seen == [row.id for row in roots]
    assert sweep.after_id == roots[-1].id
    purge.assert_not_called()
    scan.assert_not_called()


def test_physical_report_restriction_records_only_an_exact_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, scan = root_and_scan()
    scan.purpose = "report_expiry"
    source = uuid4()
    session = Mock(spec=Session)
    session.scalar.return_value = None
    monkeypatch.setattr(
        scanner,
        "_row",
        lambda *args: SimpleNamespace(
            id=source,
            created_at=AT - timedelta(days=1),
            expires_at=AT + timedelta(days=2),
            license_version_id=uuid4(),
            provider_id=uuid4(),
        ),
    )
    monkeypatch.setattr(scanner, "_license_until", lambda *args: None)
    assert scanner._physical(session, scan, "price", source, AT, SourcePurgeBudget())
    assert (scan.restriction_kind, scan.restriction_id) == ("price", source)


def test_pending_dependency_candidate_uses_exact_indexed_flag_and_charges_empty_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_persistence import report_retention

    root, _ = root_and_scan()
    session = Mock(spec=Session)
    session.scalar.return_value = None
    budget = SourcePurgeBudget(rows_inspected=3)
    assert report_retention.purge_report_premium_copies(
        session, root.owner_id, root.id, at=AT, budget=budget
    )
    query = session.scalar.call_args.args[0]
    sql = str(query)
    assert "copy_pending IS true" in sql and "JOIN" not in sql
    assert "canonical_" not in sql and "report_capture_pending" not in sql
    assert {root.owner_id, root.id} <= set(query.compile().params.values())
    assert budget.rows_inspected == 2


def test_report_payload_mutation_reserves_trigger_rows_before_any_update() -> None:
    from typing import cast

    from sqlalchemy import Table
    from trading212_persistence import report_retention
    from trading212_persistence.report_models import ReportInputChunkModel

    session = Mock(spec=Session)
    identifier, owner, input_id = uuid4(), uuid4(), uuid4()
    session.execute.return_value.all.return_value = [SimpleNamespace(id=identifier, size=100)]
    budget = SourcePurgeBudget(rows_inspected=report_retention.REPORT_PAYLOAD_MUTATION_ROWS)
    table = cast(Table, ReportInputChunkModel.__table__)
    assert not report_retention._clear_payloads(
        session,
        table,
        (table.c.owner_id == owner) & (table.c.input_id == input_id),
        columns=("payload",),
        at=AT,
        budget=budget,
    )
    assert session.execute.call_count == 1
    assert str(session.execute.call_args.args[0]).lstrip().startswith("SELECT")
    assert budget.rows_removed == 4096


def test_report_completion_defers_before_marker_and_flag_transition_when_budget_is_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_persistence import report_retention
    from trading212_persistence.report_models import ReportRetentionWorkModel

    root, _ = root_and_scan()
    input_id = uuid4()
    work = ReportRetentionWorkModel(
        id=uuid4(),
        owner_id=root.owner_id,
        input_id=input_id,
        created_at=AT,
        started_at=AT,
        reason="source",
        completed_at=None,
    )
    session = Mock(spec=Session)
    session.execute.return_value.first.return_value = SimpleNamespace(
        id=input_id,
        kind="report",
        account_id=root.account_id,
        purged_at=None,
    )
    session.scalar.return_value = work
    session.scalars.return_value = ()
    monkeypatch.setattr(report_retention, "_clear_payloads", lambda *args, **kwargs: True)
    budget = SourcePurgeBudget(rows_inspected=report_retention.REPORT_PURGE_COMPLETION_MAX_ROWS)
    assert not report_retention.purge_report_input(
        session,
        owner=root.owner_id,
        input_id=input_id,
        reason="source",
        at=AT,
        budget=budget,
    )
    assert work.completed_at is None
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_global_ttl_pending_and_legacy_phases_share_the_same_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_persistence import legacy_report_retention, report_retention

    session = Mock(spec=Session)
    session.execute.return_value.first.return_value = None
    pending, legacy, projection = (
        Mock(return_value=0),
        Mock(return_value=0),
        Mock(return_value=False),
    )
    monkeypatch.setattr(legacy_report_retention, "resume_report_retention_work", pending)
    monkeypatch.setattr(legacy_report_retention, "expire_legacy_report_payloads", legacy)
    monkeypatch.setattr(retention, "expire_projection_report_payloads", projection)
    budget = SourcePurgeBudget(rows_inspected=8)
    assert report_retention.expire_report_payloads(session, at=AT, budget=budget) == 0
    session.execute.assert_called_once()
    ttl = session.execute.call_args.args[0]
    assert "report_premium_restricted" not in str(ttl)
    assert "contract_version" not in str(ttl) and "expires_at <=" in str(ttl)
    assert budget.rows_inspected == 7
    for phase in (pending, legacy, projection):
        phase.assert_called_once_with(session, at=AT, budget=budget)


def test_inactive_grant_scan_uses_expiry_index_and_reserves_rejected_live_prefix() -> None:
    from trading212_persistence import report_retention

    session = Mock(spec=Session)
    session.execute.return_value.first.return_value = SimpleNamespace(id=uuid4(), byte_length=1)
    session.execute.return_value.all.return_value = []
    budget = SourcePurgeBudget(rows_inspected=12)
    assert not report_retention._artifact(
        session,
        uuid4(),
        uuid4(),
        export=False,
        at=AT,
        budget=budget,
    )
    assert budget.rows_inspected == 0
    assert session.execute.call_count == 2
    query = session.execute.call_args_list[1].args[0]
    assert "ORDER BY artifact_download_grants.expires_at, artifact_download_grants.id" in str(query)
    assert budget.rows_removed == 4096
