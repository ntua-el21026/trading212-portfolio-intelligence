from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import Mock
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
    cursor_binding,
)
from trading212_domain import build_synthetic_identity
from trading212_persistence import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
    OwnerModel,
)
from trading212_persistence.seed import seed_synthetic

pytestmark = pytest.mark.integration

CURSOR_KEY = b"immutable-collection-snapshot-integration-key-v1"


def _base_url() -> str:
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="module")
def collection_snapshot_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    parsed = make_url(_base_url())
    database_name = f"t212pi_collection_snapshots_{uuid4().hex[:12]}"
    admin = parsed.set(database="postgres")
    admin_dsn = admin.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    database_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    engine: Engine | None = None
    try:
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        seed_synthetic(database_url, app_environment="test")
        engine = create_database_engine(database_url)
        yield engine, create_session_factory(engine)
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_collection_snapshots_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _definition(*, filter_name: str = "all") -> CollectionSnapshotDefinition:
    identity = build_synthetic_identity()
    return CollectionSnapshotDefinition(
        resource=CollectionSnapshotResource.ACTIVITY,
        owner_id=identity.owner.id,
        broker_account_id=identity.account.id,
        filter_fingerprint=collection_filter_fingerprint(filter_name),
    )


def _tamper(token: str) -> str:
    index = len(token) // 2
    replacement = "A" if token[index] != "A" else "B"
    return f"{token[:index]}{replacement}{token[index + 1 :]}"


def _create_isolated_scope(session: Session, *, label: str) -> tuple[UUID, UUID]:
    now = datetime.now(UTC)
    owner_id = uuid4()
    connection_id = uuid4()
    account_id = uuid4()
    session.add(
        OwnerModel(
            id=owner_id,
            display_name=f"Collection quota {label}",
        )
    )
    session.flush()
    session.add(
        BrokerConnectionModel(
            id=connection_id,
            owner_id=owner_id,
            provider="synthetic",
            environment="synthetic",
            credential_reference=None,
            status="active",
        )
    )
    session.flush()
    session.add(
        BrokerAccountModel(
            id=account_id,
            connection_id=connection_id,
            provider_account_id=f"collection-quota-{account_id}",
            account_type="invest",
            base_currency="EUR",
            display_name=f"Collection quota {label}",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    session.flush()
    return owner_id, account_id


def _scoped_definition(
    owner_id: UUID,
    account_id: UUID,
    *,
    filter_name: str,
) -> CollectionSnapshotDefinition:
    return CollectionSnapshotDefinition(
        resource=CollectionSnapshotResource.ACTIVITY,
        owner_id=owner_id,
        broker_account_id=account_id,
        filter_fingerprint=collection_filter_fingerprint(filter_name),
    )


def test_schema_has_fixed_scope_exact_total_and_membership_constraints(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, _ = collection_snapshot_database
    inspector = inspect(engine)
    assert {
        "collection_query_snapshots",
        "collection_query_snapshot_members",
    }.issubset(inspector.get_table_names())
    snapshot_checks = {
        item["name"] for item in inspector.get_check_constraints("collection_query_snapshots")
    }
    assert {
        "ck_collection_query_snapshots_schema_version_supported",
        "ck_collection_query_snapshots_resource_allowed",
        "ck_collection_query_snapshots_resource_sort_match",
        "ck_collection_query_snapshots_account_scope_match",
        "ck_collection_query_snapshots_filter_fingerprint_format",
        "ck_collection_query_snapshots_exact_total_nonnegative",
        "ck_collection_query_snapshots_expiry_after_creation",
    }.issubset(snapshot_checks)
    member_uniques = {
        item["name"]
        for item in inspector.get_unique_constraints("collection_query_snapshot_members")
    }
    assert "uq_collection_snapshot_member_record" in member_uniques
    index_names = {item["name"] for item in inspector.get_indexes("collection_query_snapshots")}
    assert {
        "ix_collection_query_snapshots_broker_account",
        "ix_collection_query_snapshots_expiry",
        "ix_collection_query_snapshots_owner_expiry",
        "ix_collection_query_snapshots_scope",
    }.issubset(index_names)


def test_streamed_membership_is_atomic_exact_and_restart_resumable(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    definition = _definition(filter_name="streaming-regression")
    expected = tuple(
        uuid5(NAMESPACE_URL, f"t212pi/collection-snapshot/record/{index}") for index in range(2_505)
    )
    codec = CursorCodec(CURSOR_KEY)

    with sessions.begin() as session:

        def streamed_ids() -> Iterator[UUID]:
            for index, record_id in enumerate(expected):
                if index in {1_000, 2_000}:
                    persisted = session.scalar(
                        select(func.count())
                        .select_from(CollectionQuerySnapshotMemberModel)
                        .join(CollectionQuerySnapshotModel)
                        .where(
                            CollectionQuerySnapshotModel.filter_fingerprint
                            == definition.filter_fingerprint
                        )
                    )
                    assert persisted == index
                yield record_id

        first = CollectionSnapshotStore(session, codec).materialize(
            definition,
            streamed_ids(),
            limit=100,
        )
        assert first.record_ids == expected[:100]
        assert first.exact_total == len(expected)
        assert first.next_cursor is not None
        assert session.scalar(
            select(func.count())
            .select_from(CollectionQuerySnapshotMemberModel)
            .where(CollectionQuerySnapshotMemberModel.snapshot_id == first.snapshot_id)
        ) == len(expected)

    seen = list(first.record_ids)
    cursor: str | None = first.next_cursor
    while cursor is not None:
        with sessions.begin() as session:
            page = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
                definition,
                cursor,
                limit=100,
            )
        seen.extend(page.record_ids)
        cursor = page.next_cursor
    assert tuple(seen) == expected


def test_cursor_scope_filter_resource_tamper_and_expiry_fail_closed(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    identity = build_synthetic_identity()
    definition = _definition(filter_name="cursor-binding")
    codec = CursorCodec(CURSOR_KEY)
    with sessions.begin() as session:
        first = CollectionSnapshotStore(session, codec).materialize(
            definition,
            (
                uuid5(NAMESPACE_URL, "t212pi/collection-snapshot/bound/1"),
                uuid5(NAMESPACE_URL, "t212pi/collection-snapshot/bound/2"),
            ),
            limit=1,
        )
    assert first.next_cursor is not None

    mismatches = (
        _definition(filter_name="different-filter"),
        CollectionSnapshotDefinition(
            resource=CollectionSnapshotResource.DIVIDENDS,
            owner_id=identity.owner.id,
            broker_account_id=identity.account.id,
            filter_fingerprint=definition.filter_fingerprint,
        ),
        CollectionSnapshotDefinition(
            resource=CollectionSnapshotResource.ACTIVITY,
            owner_id=uuid4(),
            broker_account_id=identity.account.id,
            filter_fingerprint=definition.filter_fingerprint,
        ),
        CollectionSnapshotDefinition(
            resource=CollectionSnapshotResource.ACTIVITY,
            owner_id=identity.owner.id,
            broker_account_id=uuid4(),
            filter_fingerprint=definition.filter_fingerprint,
        ),
    )
    for mismatch in mismatches:
        with sessions.begin() as session, pytest.raises(CursorValidationError):
            CollectionSnapshotStore(session, codec).resume(
                mismatch,
                first.next_cursor,
                limit=1,
            )
    with sessions.begin() as session, pytest.raises(CursorValidationError):
        CollectionSnapshotStore(session, codec).resume(
            definition,
            _tamper(first.next_cursor),
            limit=1,
        )

    cursor_clock = [datetime.now(UTC)]
    expiring_codec = CursorCodec(CURSOR_KEY, clock=lambda: cursor_clock[0], ttl_seconds=60)
    with sessions.begin() as session:
        expiring = CollectionSnapshotStore(
            session,
            expiring_codec,
            ttl_seconds=60,
        ).materialize(
            _definition(filter_name="expiry"),
            (
                uuid5(NAMESPACE_URL, "t212pi/collection-snapshot/expiry/1"),
                uuid5(NAMESPACE_URL, "t212pi/collection-snapshot/expiry/2"),
            ),
            limit=1,
        )
    assert expiring.next_cursor is not None
    cursor_clock[0] += timedelta(seconds=61)
    with sessions.begin() as session, pytest.raises(CursorValidationError):
        CollectionSnapshotStore(
            session,
            expiring_codec,
            ttl_seconds=60,
        ).resume(
            _definition(filter_name="expiry"),
            expiring.next_cursor,
            limit=1,
        )


def test_opportunistic_cleanup_is_bounded(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    identity = build_synthetic_identity()
    now = datetime.now(UTC)
    ids = tuple(uuid4() for _ in range(3))
    with sessions.begin() as session:
        session.add_all(
            CollectionQuerySnapshotModel(
                id=snapshot_id,
                schema_version=1,
                resource="activity",
                owner_id=identity.owner.id,
                broker_account_id=identity.account.id,
                sort_specification="occurred_at_desc_id_desc",
                filter_fingerprint=collection_filter_fingerprint("expired", snapshot_id),
                exact_total=0,
                created_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )
            for snapshot_id in ids
        )
    locker = sessions()
    locker.begin()
    try:
        assert (
            locker.scalar(
                select(CollectionQuerySnapshotModel.id)
                .where(CollectionQuerySnapshotModel.id == ids[0])
                .with_for_update()
            )
            == ids[0]
        )
        with sessions.begin() as session:
            deleted = CollectionSnapshotStore(
                session,
                CursorCodec(CURSOR_KEY),
                cleanup_batch_size=2,
            ).cleanup_expired()
            remaining = session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.id.in_(ids))
            )
    finally:
        locker.rollback()
        locker.close()
    assert deleted == 2
    assert remaining == 1


def test_filter_varied_first_pages_stop_before_source_query_at_snapshot_quota(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="snapshot-count")

    for index in range(3):
        with sessions.begin() as session:
            page = CollectionSnapshotStore(
                session,
                CursorCodec(CURSOR_KEY),
                max_active_snapshots_per_owner=3,
                max_active_members_per_owner=100,
            ).materialize(
                _scoped_definition(
                    owner_id,
                    account_id,
                    filter_name=f"filter-varied-limit-one-{index}",
                ),
                (uuid4(),),
                limit=1,
            )
            assert page.exact_total == 1

    source_started = False

    def blocked_source() -> Iterator[UUID]:
        nonlocal source_started
        source_started = True
        yield uuid4()

    with pytest.raises(CollectionSnapshotCapacityError), sessions.begin() as session:
        CollectionSnapshotStore(
            session,
            CursorCodec(CURSOR_KEY),
            max_active_snapshots_per_owner=3,
            max_active_members_per_owner=100,
        ).materialize(
            _scoped_definition(
                owner_id,
                account_id,
                filter_name="filter-varied-limit-one-blocked",
            ),
            blocked_source,
            limit=1,
        )

    assert source_started is False
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == owner_id)
            )
            == 3
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotMemberModel)
                .join(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == owner_id)
            )
            == 3
        )


def test_first_materialization_at_member_quota_is_exact_and_stable(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="exact-fit")
    definition = _scoped_definition(owner_id, account_id, filter_name="exact-fit")
    expected = tuple(uuid4() for _ in range(3))
    with sessions.begin() as session:
        first = CollectionSnapshotStore(
            session,
            CursorCodec(CURSOR_KEY),
            max_active_members_per_owner=3,
        ).materialize(definition, expected, limit=1)
    assert first.exact_total == 3
    assert first.record_ids == expected[:1]
    assert first.next_cursor is not None

    seen = list(first.record_ids)
    cursor: str | None = first.next_cursor
    while cursor is not None:
        with sessions.begin() as session:
            page = CollectionSnapshotStore(
                session,
                CursorCodec(CURSOR_KEY),
                max_active_members_per_owner=3,
            ).resume(definition, cursor, limit=1)
            assert page.exact_total == 3
            assert page.snapshot_id == first.snapshot_id
        seen.extend(page.record_ids)
        cursor = page.next_cursor
    assert tuple(seen) == expected
    with sessions.begin() as session:
        replay = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
            definition, first.next_cursor, limit=1
        )
    assert replay.record_ids == expected[1:2]


@pytest.mark.parametrize("capacity", [3, 1_003])
def test_first_overflow_is_bounded_atomic_and_never_resumable(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    capacity: int,
) -> None:
    _, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="first-overflow")
    definition = _scoped_definition(owner_id, account_id, filter_name="first-overflow")
    codec = CursorCodec(CURSOR_KEY)
    encode = Mock(wraps=codec.encode)
    monkeypatch.setattr(codec, "encode", encode)
    consumed = 0
    attempted_snapshot: CollectionQuerySnapshotModel | None = None

    with sessions.begin() as session:
        owner = session.get(OwnerModel, owner_id)
        assert owner is not None
        owner.display_name = "Unrelated caller change survives overflow"

        def overflow_source() -> Iterator[UUID]:
            nonlocal consumed, attempted_snapshot
            attempted_snapshot = session.scalar(
                select(CollectionQuerySnapshotModel).where(
                    CollectionQuerySnapshotModel.owner_id == owner_id
                )
            )
            assert attempted_snapshot is not None
            for _ in range(capacity + 1):
                if consumed == 1_000:
                    assert (
                        session.scalar(
                            select(func.count())
                            .select_from(CollectionQuerySnapshotMemberModel)
                            .where(
                                CollectionQuerySnapshotMemberModel.snapshot_id
                                == attempted_snapshot.id
                            )
                        )
                        == 1_000
                    )
                consumed += 1
                yield uuid4()
            pytest.fail("materialization consumed past the overflow identity")

        # The error is caught inside the surrounding transaction deliberately.
        # Only the failed materialization must roll back when that transaction commits.
        with pytest.raises(CollectionSnapshotCapacityError):
            CollectionSnapshotStore(
                session,
                codec,
                max_active_members_per_owner=capacity,
            ).materialize(definition, overflow_source, limit=1)
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == owner_id)
            )
            == 0
        )

    assert consumed == capacity + 1
    encode.assert_not_called()
    assert attempted_snapshot is not None
    with sessions() as session:
        assert session.get(CollectionQuerySnapshotModel, attempted_snapshot.id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotMemberModel)
                .where(CollectionQuerySnapshotMemberModel.snapshot_id == attempted_snapshot.id)
            )
            == 0
        )
        owner = session.get(OwnerModel, owner_id)
        assert owner is not None
        assert owner.display_name == "Unrelated caller change survives overflow"

    # Even a correctly authenticated token constructed for the attempted row
    # cannot recover failed state. No such token was emitted by materialization.
    signed_attempt = CursorCodec(CURSOR_KEY).encode(
        resource=f"collection_snapshot.{definition.resource.value}",
        binding=cursor_binding(
            "collection-query-snapshot",
            1,
            definition.owner_id,
            definition.broker_account_id,
            definition.resource,
            definition.sort_specification,
            definition.filter_fingerprint,
        ),
        read_cutoff=attempted_snapshot.created_at,
        key=(str(attempted_snapshot.id), "1"),
    )
    with sessions.begin() as session, pytest.raises(CursorValidationError):
        CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
            definition, signed_attempt, limit=1
        )


def test_remaining_member_quota_overflow_preserves_existing_traversal(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="member-count")

    first_definition = _scoped_definition(owner_id, account_id, filter_name="member-first")
    first_ids = (uuid4(), uuid4())
    with sessions.begin() as session:
        first = CollectionSnapshotStore(
            session,
            CursorCodec(CURSOR_KEY),
            max_active_members_per_owner=3,
        ).materialize(first_definition, first_ids, limit=1)
    assert first.exact_total == 2
    assert first.next_cursor is not None
    consumed = 0

    def over_capacity_source() -> Iterator[UUID]:
        nonlocal consumed
        for _ in range(2):
            consumed += 1
            yield uuid4()
        pytest.fail("materialization consumed beyond remaining capacity plus one")

    with sessions.begin() as session, pytest.raises(CollectionSnapshotCapacityError):
        CollectionSnapshotStore(
            session,
            CursorCodec(CURSOR_KEY),
            max_active_members_per_owner=3,
        ).materialize(
            _scoped_definition(owner_id, account_id, filter_name="member-blocked"),
            over_capacity_source,
            limit=1,
        )
    assert consumed == 2
    with sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == owner_id)
            )
            == 1
        )
        assert session.scalar(
            select(func.count())
            .select_from(CollectionQuerySnapshotMemberModel)
            .join(CollectionQuerySnapshotModel)
            .where(CollectionQuerySnapshotModel.owner_id == owner_id)
        ) == len(first_ids)
        resumed = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
            first_definition, first.next_cursor, limit=1
        )
    assert resumed.record_ids == first_ids[1:]
    assert resumed.exact_total == 2


@pytest.mark.parametrize(
    ("snapshot_quota", "member_quota", "request_size"),
    [(1, 100, 1), (10, 3, 2)],
    ids=["snapshot-quota", "member-quota"],
)
def test_concurrent_materializations_share_one_owner_capacity_decision(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
    snapshot_quota: int,
    member_quota: int,
    request_size: int,
) -> None:
    _, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="concurrent")
    start = Barrier(2)

    def materialize(index: int) -> str:
        start.wait(timeout=10)
        try:
            with sessions.begin() as session:
                CollectionSnapshotStore(
                    session,
                    CursorCodec(CURSOR_KEY),
                    max_active_snapshots_per_owner=snapshot_quota,
                    max_active_members_per_owner=member_quota,
                ).materialize(
                    _scoped_definition(
                        owner_id,
                        account_id,
                        filter_name=f"concurrent-{index}",
                    ),
                    tuple(uuid4() for _ in range(request_size)),
                    limit=1,
                )
        except CollectionSnapshotCapacityError:
            return "capacity"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(materialize, range(2)))

    assert sorted(outcomes) == ["capacity", "created"]
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == owner_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotMemberModel)
                .join(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == owner_id)
            )
            == request_size
        )


def test_expiry_releases_quota_before_bounded_cleanup_finishes(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="expired-capacity")
        expired_ids = []
        for index in range(3):
            page = CollectionSnapshotStore(
                session,
                CursorCodec(CURSOR_KEY),
                max_active_snapshots_per_owner=3,
                max_active_members_per_owner=3,
            ).materialize(
                _scoped_definition(owner_id, account_id, filter_name=f"expire-{index}"),
                (uuid4(),),
                limit=1,
            )
            expired_ids.append(page.snapshot_id)
    expired_at = datetime.now(UTC) - timedelta(days=365)
    with sessions.begin() as session:
        for snapshot_id in expired_ids:
            snapshot = session.get(CollectionQuerySnapshotModel, snapshot_id)
            assert snapshot is not None
            snapshot.created_at = expired_at - timedelta(hours=1)
            snapshot.expires_at = expired_at

    # A locked expired row and a cleanup batch smaller than the backlog cannot
    # prevent the next traversal from using the owner's released capacity.
    with sessions.begin() as locker:
        locker.scalar(
            select(CollectionQuerySnapshotModel.id)
            .where(CollectionQuerySnapshotModel.id == expired_ids[0])
            .with_for_update()
        )
        with sessions.begin() as session:
            expected = tuple(uuid4() for _ in range(3))
            page = CollectionSnapshotStore(
                session,
                CursorCodec(CURSOR_KEY),
                cleanup_batch_size=1,
                max_active_snapshots_per_owner=1,
                max_active_members_per_owner=3,
            ).materialize(
                _scoped_definition(owner_id, account_id, filter_name="after-expiry"),
                expected,
                limit=1,
            )
            assert page.exact_total == 3
            assert page.record_ids == expected[:1]
            assert page.next_cursor is not None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(CollectionQuerySnapshotModel)
                    .where(CollectionQuerySnapshotModel.id.in_(expired_ids))
                )
                == 2
            )
