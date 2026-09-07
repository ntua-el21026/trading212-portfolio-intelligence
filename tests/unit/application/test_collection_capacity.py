"""Isolate the source-consumption bound; PostgreSQL tests prove atomic storage."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from trading212_application.queries import CollectionSnapshotCapacityError, CursorCodec
from trading212_persistence import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from trading212_persistence import collection_snapshots as snapshots


@pytest.mark.parametrize(
    ("active_snapshots", "active_members", "member_quota"),
    [(0, 0, 3), (1, 2, 3), (0, 0, 1_003), (2, 998, 2_001)],
    ids=["first", "one-remaining", "first-beyond-insert-batch", "remaining-beyond-insert-batch"],
)
def test_every_materialization_stops_at_remaining_capacity_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    active_snapshots: int,
    active_members: int,
    member_quota: int,
) -> None:
    session = MagicMock(spec=Session)
    codec = Mock(spec=CursorCodec)
    definition = CollectionSnapshotDefinition(
        resource=CollectionSnapshotResource.INSTRUMENTS,
        owner_id=uuid4(),
        broker_account_id=None,
        filter_fingerprint=collection_filter_fingerprint("bounded-source"),
    )
    store = CollectionSnapshotStore(session, codec, max_active_members_per_owner=member_quota)
    capacity = Mock(return_value=(active_snapshots, active_members))
    lock = Mock()
    read_page = Mock()
    monkeypatch.setattr(store, "_require_materialization_scope", Mock())
    monkeypatch.setattr(store, "_active_capacity", capacity)
    monkeypatch.setattr(store, "cleanup_expired", Mock())
    monkeypatch.setattr(store, "_read_page", read_page)
    monkeypatch.setattr(snapshots, "_acquire_owner_capacity_lock", lock)
    monkeypatch.setattr(snapshots, "_database_now", lambda _: datetime(2026, 9, 7, tzinfo=UTC))
    remaining = member_quota - active_members
    consumed = 0

    def source() -> Iterator[UUID]:
        nonlocal consumed
        capacity.assert_called_once()
        lock.assert_called_once_with(session, definition.owner_id)
        for _ in range(remaining + 1):
            consumed += 1
            yield uuid4()
        pytest.fail("source consumed beyond remaining capacity plus one")

    with pytest.raises(CollectionSnapshotCapacityError):
        store.materialize(definition, source, limit=1)

    assert consumed == remaining + 1
    read_page.assert_not_called()
    codec.encode.assert_not_called()
    # Earlier full batches may have been written before overflow. The exception
    # must reach the savepoint context so SQLAlchemy rolls those writes back.
    session.begin_nested.assert_called_once()
    assert (
        session.begin_nested.return_value.__exit__.call_args.args[0]
        is CollectionSnapshotCapacityError
    )
    inserted_ordinals = [
        row["ordinal"] for call in session.execute.call_args_list for row in call.args[1]
    ]
    assert inserted_ordinals == list(range(1, remaining // 1_000 * 1_000 + 1))


@pytest.mark.parametrize("active_capacity", [(2, 0), (1, 3)])
def test_exhausted_capacity_does_not_start_source_or_create_cursor_state(
    monkeypatch: pytest.MonkeyPatch,
    active_capacity: tuple[int, int],
) -> None:
    session = MagicMock(spec=Session)
    codec = Mock(spec=CursorCodec)
    source = Mock()
    definition = CollectionSnapshotDefinition(
        resource=CollectionSnapshotResource.INSTRUMENTS,
        owner_id=uuid4(),
        broker_account_id=None,
        filter_fingerprint=collection_filter_fingerprint("exhausted-source"),
    )
    store = CollectionSnapshotStore(
        session,
        codec,
        max_active_snapshots_per_owner=2,
        max_active_members_per_owner=3,
    )
    monkeypatch.setattr(store, "_require_materialization_scope", Mock())
    monkeypatch.setattr(store, "_active_capacity", Mock(return_value=active_capacity))
    monkeypatch.setattr(store, "cleanup_expired", Mock())
    monkeypatch.setattr(snapshots, "_acquire_owner_capacity_lock", Mock())
    monkeypatch.setattr(snapshots, "_database_now", lambda _: datetime(2026, 9, 7, tzinfo=UTC))

    with pytest.raises(CollectionSnapshotCapacityError):
        store.materialize(definition, source, limit=1)

    source.assert_not_called()
    session.add.assert_not_called()
    session.begin_nested.assert_not_called()
    codec.encode.assert_not_called()
