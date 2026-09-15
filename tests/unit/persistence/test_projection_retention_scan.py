"""Budget exhaustion preserves exact graph cursors without a private decode."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from trading212_persistence import projection_retention as retention
from trading212_persistence import projection_retention_scan as scanner
from trading212_persistence.historical_models import HistoricalDependencyModel
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.projection_models import ProjectionRunModel, ProjectionRunSourceModel
from trading212_persistence.projection_retention_models import (
    ProjectionRetentionEpochModel as Epoch,
)
from trading212_persistence.projection_retention_models import (
    ProjectionRetentionFrontierModel as Frontier,
)
from trading212_persistence.projection_retention_models import (
    ProjectionRetentionScanModel as Scan,
)
from trading212_persistence.projection_retention_models import (
    ProjectionRetentionTargetModel as Target,
)
from trading212_persistence.source_retention import SourcePurgeBudget

pytestmark = pytest.mark.unit
AT = datetime(2026, 9, 15, 12, tzinfo=UTC)


def root_and_scan() -> tuple[PremiumRunModel, Scan]:
    root = PremiumRunModel(
        id=uuid4(),
        owner_id=uuid4(),
        account_id=uuid4(),
        kind="projection",
        created_at=AT - timedelta(days=1),
        expires_at=AT + timedelta(days=10),
        reserved_bytes=33554432,
        retained_bytes=0,
    )
    scan = Scan(
        id=uuid4(),
        owner_id=root.owner_id,
        account_id=root.account_id,
        run_id=root.id,
        purpose="expiry",
        target_kind=None,
        target_id=None,
        phase="walk",
        policy_epoch=0,
        evaluated_at=AT,
        next_policy_at=None,
        earliest_deadline=AT + timedelta(days=5),
        source_cursor=None,
        current_source_id=uuid4(),
        history_input_id=uuid4(),
        history_created_at=AT - timedelta(days=1),
        source_count=0,
        dependencies_seen=0,
        node_count=1,
        created_at=AT,
    )
    return root, scan


def test_tiny_allowance_returns_pending_without_any_sql() -> None:
    root, _ = root_and_scan()
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    budget = SourcePurgeBudget(rows_inspected=2)
    assert scanner.scan_projection_sources(session, root, at=AT, budget=budget) == "pending"
    session.scalar.assert_not_called()
    session.execute.assert_not_called()
    assert budget.rows_inspected == 2


@pytest.mark.parametrize("mode", ("expiry", "source_match", "report_expiry"))
def test_more_than_one_batch_of_dependencies_resumes_each_exact_link_once(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    root, scan = root_and_scan()
    alternating = mode == "source_match"
    scan.purpose = mode
    target_a, target_b = uuid4(), uuid4()
    if alternating:
        scan.purpose, scan.target_kind, scan.target_id = "source_match", "price", target_a
    outcomes_by_target: dict[UUID, Any] = {}
    node = Frontier(
        id=uuid4(),
        owner_id=root.owner_id,
        account_id=root.account_id,
        scan_id=scan.id,
        subject_id=scan.history_input_id,
        is_evidence=False,
        dependency_cursor=None,
        complete=False,
        created_at=AT,
    )
    links = [
        HistoricalDependencyModel(
            id=UUID(int=index),
            owner_id=root.owner_id,
            input_id=scan.history_input_id,
            evidence_id=None,
            reference_key=f"opening-{index}",
            portfolio_snapshot_id=uuid4(),
            created_at=AT,
        )
        for index in range(1, 701)
    ]
    visited: list[tuple[UUID | None, UUID]] = []
    queries: list[str] = []

    def scalar(query: Any) -> Any:
        sql = str(query)
        queries.append(sql)
        assert "canonical_" not in sql and "projection_history_links" not in sql
        assert "projection_storage_bytes" not in sql and "projection_source_proofs" not in sql
        assert root.owner_id in query.compile().params.values()
        entity = query.column_descriptions[0]["entity"]
        if entity is Target:
            return outcomes_by_target.get(query.compile().params["target_id_1"])
        if entity is Epoch:
            return 0
        if entity is Scan:
            return scan
        if entity is Frontier:
            return None if node.complete else node
        if entity is HistoricalDependencyModel:
            after = query.compile().params.get("id_1")
            index = 0 if after is None else after.int
            if index == len(links):
                return None
            item = links[index]
            visited.append((scan.target_id, item.id))
            return item
        if entity is ProjectionRunSourceModel:
            return None
        if entity is ProjectionRunModel:
            return 1
        raise AssertionError(sql)

    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    session.scalar.side_effect = scalar
    session.scalars.side_effect = lambda query: list(outcomes_by_target.values())
    session.add.side_effect = lambda row: outcomes_by_target.__setitem__(row.target_id, row)
    if alternating:

        def reset(
            session: Session, value: Scan, epoch: int, at: datetime, budget: SourcePurgeBudget
        ) -> bool:
            # Only completed traversal may be replaced; this assertion catches the
            # former two-target restart loop before the second graph begins.
            assert len(visited) == len(links)
            value.phase, value.policy_epoch, value.evaluated_at = "walk", epoch, at
            value.source_cursor, value.current_source_id = None, uuid4()
            value.history_input_id, value.history_created_at = node.subject_id, AT
            value.source_count, value.dependencies_seen, value.node_count = 0, 0, 1
            node.complete, node.dependency_cursor = False, None
            return True

        monkeypatch.setattr(scanner, "_reset", reset)
    # The frontier cleanup helper has independent SQL budget tests; this harness
    # retains the real scanner, query predicates, 700 source rows and checkpoints.
    monkeypatch.setattr(
        scanner, "_clear_frontier", lambda session, scan, budget: budget.inspect(rows=1)
    )
    outcomes: list[str] = []
    previous_cursor = None
    done: set[UUID] = set()
    for iteration in range(200):
        budget = SourcePurgeBudget(rows_inspected=96)
        start = len(queries)
        current_target = target_a if iteration % 2 == 0 else target_b
        result = scanner.scan_projection_sources(
            session,
            root,
            at=AT,
            budget=budget,
            target=("price", current_target) if alternating else None,
            report=mode == "report_expiry",
        )
        outcomes.append(result)
        assert 0 <= budget.rows_inspected <= 96
        assert len(queries) - start <= 96 - budget.rows_inspected
        if not alternating and node.dependency_cursor is not None and previous_cursor is not None:
            assert node.dependency_cursor >= previous_cursor
        previous_cursor = node.dependency_cursor
        if alternating and result == "no_match":
            done.add(current_target)
        if result == "clean" or done == {target_a, target_b}:
            break
    else:
        pytest.fail("bounded source traversal did not finish")
    assert outcomes[0] == "pending" and len(outcomes) > 2
    assert visited == [
        (target, row.id)
        for target in ((target_a, target_b) if alternating else (None,))
        for row in links
    ]
    if alternating:
        assert done == {target_a, target_b}
    assert scan.phase == "clean" and scan.source_count == 1
    assert scan.dependencies_seen == scan.node_count == 0


@pytest.mark.parametrize("change", ("epoch", "future_activation", "backwards_clock"))
def test_changed_policy_or_clock_resets_before_using_a_cached_expired_deadline(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    root, scan = root_and_scan()
    scan.phase = "clean"
    scan.earliest_deadline = AT - timedelta(seconds=1)
    if change == "future_activation":
        scan.next_policy_at = AT
    if change == "backwards_clock":
        scan.evaluated_at = AT + timedelta(seconds=1)
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    session.scalar.side_effect = (1 if change == "epoch" else 0, scan)
    resets: list[int] = []

    def reset(
        session: Session, value: Scan, epoch: int, at: datetime, budget: SourcePurgeBudget
    ) -> bool:
        resets.append(epoch)
        value.policy_epoch, value.evaluated_at = epoch, at
        value.next_policy_at, value.earliest_deadline = None, None
        value.phase = "clean"
        return True

    monkeypatch.setattr(scanner, "_reset", reset)
    assert (
        scanner.scan_projection_sources(session, root, at=AT, budget=SourcePurgeBudget()) == "clean"
    )
    assert len(resets) == 1


def test_pending_scan_never_creates_a_purge_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = root_and_scan()
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    session.execute.return_value.first.return_value = SimpleNamespace(
        id=root.id, owner_id=root.owner_id
    )
    session.scalar.side_effect = (root, None)
    monkeypatch.setattr(
        retention,
        "begin_sweep",
        lambda *args, **kwargs: SimpleNamespace(after_id=None, deferred=False),
    )
    monkeypatch.setattr(retention, "_lock_owner", lambda *args: True)
    monkeypatch.setattr(retention, "scan_projection_sources", lambda *args, **kwargs: "pending")
    purge = Mock()
    monkeypatch.setattr(retention, "_purge_run", purge)
    assert not retention.expire_projection_payloads(session, at=AT, budget=SourcePurgeBudget())
    purge.assert_not_called()
    session.add.assert_not_called()


def test_dispatch_and_counter_queries_have_no_hidden_recursive_or_payload_aggregate() -> None:
    root, _ = root_and_scan()
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    session.scalar.return_value = 12345
    assert retention._storage_bytes(cast(Session, session), root) == 12345
    query = session.scalar.call_args.args[0]
    sql = str(query)
    assert "stored_bytes" in sql and "projection_storage_bytes" not in sql
    assert {root.id, root.owner_id, root.account_id} <= set(query.compile().params.values())


def test_long_clean_root_prefix_advances_a_persisted_keyset_with_every_row_charged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = root_and_scan()
    roots = [
        PremiumRunModel(
            id=UUID(int=index),
            owner_id=root.owner_id,
            account_id=root.account_id,
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
    seen: list[UUID] = []
    queries: list[str] = []
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()

    def candidate(query: Any) -> Any:
        sql = str(query)
        queries.append(sql)
        assert "EXISTS" not in sql and "projection_retention_scans" not in sql
        assert "projection_original_sources_restricted" not in sql
        after = query.compile().params.get("id_1")
        index = 0 if after is None else after.int
        row = None if index == len(roots) else roots[index]
        if row is not None:
            seen.append(row.id)
        return SimpleNamespace(first=lambda: row)

    def scalar(query: Any) -> Any:
        queries.append(str(query))
        values = query.compile().params
        if query.column_descriptions[0]["entity"] is PremiumRunModel:
            return roots[values["id_1"].int - 1]
        return SimpleNamespace(completed_at=AT)

    session.execute.side_effect, session.scalar.side_effect = candidate, scalar
    purge = Mock()
    monkeypatch.setattr(retention, "_purge_run", purge)
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=96)
        before = len(queries)
        complete = retention.expire_projection_payloads(
            session, at=AT, owner=root.owner_id, budget=budget
        )
        assert 0 <= budget.rows_inspected <= 96
        assert len(queries) - before <= 96 - budget.rows_inspected
        if complete:
            break
    else:
        pytest.fail("healthy prefix starved the bounded root sweep")
    assert seen == [row.id for row in roots]
    assert sweep.after_id == roots[-1].id
    purge.assert_not_called()
