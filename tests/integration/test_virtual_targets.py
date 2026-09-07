from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import targets as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain import build_synthetic_identity
from trading212_domain import targets as d
from trading212_domain.values import CurrencyCode
from trading212_persistence import (
    PostgresTargetService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerConnectionModel,
    CollectionQuerySnapshotModel,
    InstrumentModel,
    ListingModel,
    OwnerModel,
)
from trading212_persistence.seed import seed_synthetic
from trading212_persistence.target_models import (
    TARGET_MODELS,
    TargetCommandIdentityModel,
    TargetConstraintModel,
    TargetHoldingModel,
    TargetMappingDecisionModel,
    TargetNodeModel,
    TargetNormalizationAdjustmentModel,
    TargetValidationResultModel,
    TargetVersionEventModel,
    TargetVersionModel,
    VirtualPortfolioModel,
)
from trading212_security.principals import AuthorizationError, Principal, Scope

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
KEY = b"target-service-integration-cursor-signing-key"


@pytest.fixture(scope="module")
def target_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    name = "t212pi_targets_" + uuid4().hex[:12]
    admin = "postgresql://portfolio:portfolio@127.0.0.1:5432/postgres"
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/" + name
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    engine = None
    try:
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        command.check(cfg)
        seed_synthetic(url, app_environment="test")
        engine = create_database_engine(url)
        yield engine, create_session_factory(engine)
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def principal(owner_id: UUID | None = None) -> Principal:
    owner = owner_id or build_synthetic_identity().owner.id
    return Principal(
        str(uuid4()),
        str(owner),
        "target-tests",
        "synthetic-target-user",
        frozenset({Scope.TARGETS_READ, Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ}),
        NOW - timedelta(days=1),
        NOW + timedelta(days=90),
    )


def service(
    database: tuple[Engine, sessionmaker[Session]],
    *,
    max_active_collection_snapshots_per_owner: int = 64,
    max_active_collection_members_per_owner: int = 250_000,
) -> PostgresTargetService:
    return PostgresTargetService(
        sessions=database[1],
        cursor_signing_key=KEY,
        clock=lambda: NOW,
        max_active_collection_snapshots_per_owner=max_active_collection_snapshots_per_owner,
        max_active_collection_members_per_owner=max_active_collection_members_per_owner,
    )


def content(*, normalized: bool = True) -> d.TargetContent:
    identity = build_synthetic_identity()
    return d.TargetContent(
        (
            d.TargetNode(
                "holding",
                None,
                d.TargetNodeKind.HOLDING,
                "Holding",
                0,
                Decimal("0.8"),
                d.TargetHoldingMapping(
                    d.TargetMappingState.RESOLVED,
                    identity.instrument.id,
                    identity.listing.id,
                    identity.listing.id,
                ),
            ),
            d.TargetNode(
                "cash",
                None,
                d.TargetNodeKind.CASH,
                "Cash",
                1,
                Decimal("0.2") if normalized else Decimal("0.2000000000001"),
            ),
        )
    )


async def draft(
    svc: PostgresTargetService,
    user: Principal,
    *,
    normalized: bool = True,
    effective_at: datetime = NOW,
) -> tuple[app.VirtualPortfolioView, app.TargetVersionView]:
    portfolio = await svc.create_virtual_portfolio(
        user,
        app.CreateVirtualPortfolioCommand(
            "Target " + uuid4().hex[:8],
            CurrencyCode("EUR"),
            str(build_synthetic_identity().account.id),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    version = await svc.create_target_version(
        user,
        portfolio.id,
        app.CreateTargetVersionCommand(effective_at, content=content(normalized=normalized)),
        if_match=portfolio.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    return portfolio, version


async def publish(
    svc: PostgresTargetService, user: Principal, version: app.TargetVersionView
) -> app.TargetVersionView:
    validation = await svc.validate_target_version(
        user,
        version.id,
        app.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    assert validation.valid
    return await svc.publish_target_version(
        user,
        version.id,
        app.PublishTargetCommand(validation.id),
        if_match=validation.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )


@pytest.mark.asyncio
async def test_normalize_publish_clone_and_database_immutability(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    portfolio, version = await draft(svc, user, normalized=False)
    invalid = await svc.validate_target_version(
        user,
        version.id,
        app.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    assert not invalid.valid
    normalized = await svc.validate_target_version(
        user,
        version.id,
        app.ValidateTargetCommand(True),
        if_match=invalid.etag,
        idempotency_key="normalize-" + uuid4().hex,
        correlation_id="target-test",
    )
    assert normalized.valid and normalized.result_revision == normalized.input_revision + 1
    assert sum(a.normalized_weight for a in normalized.adjustments) == 1
    published = await svc.publish_target_version(
        user,
        version.id,
        app.PublishTargetCommand(normalized.id),
        if_match=normalized.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    assert published.state is app.TargetVersionState.ACTIVE
    assert published.content_digest == normalized.result_digest
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(TargetNodeModel)
            .where(TargetNodeModel.target_version_id == UUID(version.id))
            .values(weight=Decimal("0.5"))
        )
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(TargetVersionModel)
            .where(TargetVersionModel.id == UUID(version.id))
            .values(effective_at=NOW + timedelta(days=1))
        )
    current = await svc.get_virtual_portfolio(user, portfolio.id)
    clone = await svc.create_target_version(
        user,
        portfolio.id,
        app.CreateTargetVersionCommand(NOW, source_version_id=version.id),
        if_match=current.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    assert clone.content == published.content and clone.id != published.id
    comparison = await svc.compare_target_versions(user, portfolio.id, published.id, clone.id)
    assert comparison.comparison.node_changes == ()
    events = await svc.list_target_version_events(user, version.id, query=app.TargetPageQuery())
    assert {e.kind for e in events.items} >= {
        "draft_created",
        "draft_updated",
        "published",
        "activated",
    }


@pytest.mark.asyncio
async def test_published_nodes_and_versions_reject_database_delete(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user)
    published = await publish(svc, user, version)
    statements = (
        delete(TargetNodeModel).where(TargetNodeModel.target_version_id == UUID(version.id)),
        delete(TargetVersionModel).where(TargetVersionModel.id == UUID(version.id)),
    )
    for statement in statements:
        with pytest.raises(IntegrityError) as denied, target_database[0].begin() as connection:
            connection.execute(statement)
        # The publication guard must reject deletion before a foreign-key failure does.
        assert getattr(denied.value.orig, "sqlstate", None) == "23514"
        retained = await svc.get_target_version(user, version.id)
        assert retained == published
        assert retained.content == published.content
        assert retained.content_digest == published.content_digest


@pytest.mark.asyncio
async def test_command_races_safe_replay_and_revision_preconditions(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    key = uuid4().hex
    cmd = app.CreateVirtualPortfolioCommand("Concurrent " + key, CurrencyCode("EUR"))
    results = await asyncio.gather(
        *(
            svc.create_virtual_portfolio(
                user, cmd, idempotency_key=key, correlation_id="target-test"
            )
            for _ in range(8)
        )
    )
    assert len({item.id for item in results}) == 1
    with pytest.raises(app.TargetServiceError) as conflict:
        await svc.create_virtual_portfolio(
            user, replace(cmd, name="Changed"), idempotency_key=key, correlation_id="target-test"
        )
    assert conflict.value.code is app.TargetServiceErrorCode.IDEMPOTENCY_KEY_REUSED
    original = results[0]
    updated = await svc.update_virtual_portfolio(
        user,
        original.id,
        app.UpdateVirtualPortfolioCommand(name="Updated"),
        if_match=original.etag,
        idempotency_key=key,
        correlation_id="target-test",
    )
    replay = await svc.update_virtual_portfolio(
        user,
        original.id,
        app.UpdateVirtualPortfolioCommand(name="Updated"),
        if_match=None,
        idempotency_key=key,
        correlation_id="target-test",
    )
    assert replay == updated
    with pytest.raises(app.TargetServiceError) as stale:
        await svc.update_virtual_portfolio(
            user,
            original.id,
            app.UpdateVirtualPortfolioCommand(name="Stale"),
            if_match=original.etag,
            idempotency_key=uuid4().hex,
            correlation_id="target-test",
        )
    assert stale.value.code is app.TargetServiceErrorCode.REVISION_MISMATCH


@pytest.mark.asyncio
async def test_owner_scope_database_scope_and_clone_read_permission(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    portfolio, version = await draft(svc, user)
    other = principal(uuid4())
    with target_database[1]() as session, session.begin():
        session.add(OwnerModel(id=UUID(other.owner_id), display_name="Other target owner"))
    with pytest.raises(app.TargetServiceError) as denied:
        await svc.get_target_version(other, version.id)
    assert denied.value.code is app.TargetServiceErrorCode.NOT_FOUND
    with pytest.raises(IntegrityError), target_database[1]() as session, session.begin():
        session.add(
            VirtualPortfolioModel(
                owner_id=UUID(other.owner_id),
                broker_account_id=build_synthetic_identity().account.id,
                name="Cross owner",
                description="",
                reporting_currency="EUR",
                revision=1,
                archived=False,
                updated_at=NOW,
                actor_principal_id=other.principal_id,
            )
        )
    with pytest.raises(IntegrityError), target_database[1]() as session, session.begin():
        session.add(
            TargetNodeModel(
                owner_id=UUID(other.owner_id),
                target_version_id=UUID(version.id),
                key="foreign",
                parent_id=None,
                kind="cash",
                name="Foreign",
                sibling_order=5,
                weight=Decimal(0),
            )
        )
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(BrokerConnectionModel)
            .where(BrokerConnectionModel.id == build_synthetic_identity().connection.id)
            .values(owner_id=UUID(other.owner_id))
        )
    writer = replace(user, scopes=frozenset({Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ}))
    current = await svc.get_virtual_portfolio(user, portfolio.id)
    with pytest.raises(AuthorizationError):
        await svc.create_target_version(
            writer,
            portfolio.id,
            app.CreateTargetVersionCommand(NOW, source_version_id=version.id),
            if_match=current.etag,
            idempotency_key=uuid4().hex,
            correlation_id="target-test",
        )


@pytest.mark.asyncio
async def test_scheduled_activation_archive_has_no_fallback(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    clock = [NOW]
    svc = PostgresTargetService(
        sessions=target_database[1], cursor_signing_key=KEY, clock=lambda: clock[0]
    )
    user = principal()
    portfolio, first = await draft(svc, user)
    first = await publish(svc, user, first)
    current = await svc.get_virtual_portfolio(user, portfolio.id)
    future = await svc.create_target_version(
        user,
        portfolio.id,
        app.CreateTargetVersionCommand(NOW + timedelta(days=1), source_version_id=first.id),
        if_match=current.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    future = await publish(svc, user, future)
    assert future.state is app.TargetVersionState.SCHEDULED
    assert await svc.activate_due_versions() == 0
    clock[0] += timedelta(days=1)
    assert sum(await asyncio.gather(*(svc.activate_due_versions(limit=1) for _ in range(4)))) == 1
    assert await svc.activate_due_versions(limit=1) == 0
    future = await svc.get_target_version(user, future.id)
    await svc.archive_target_version(
        user,
        future.id,
        if_match=future.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    assert (await svc.get_virtual_portfolio(user, portfolio.id)).active_version_id is None
    assert (await svc.get_target_version(user, first.id)).state is app.TargetVersionState.SUPERSEDED


@pytest.mark.asyncio
async def test_hierarchy_cursor_restart_draft_change_and_published_lifecycle(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user)
    first = await svc.list_target_nodes(
        user, version.id, parent_node_id=None, query=app.TargetPageQuery(limit=1)
    )
    assert first.total == 2 and first.next_cursor
    restarted = service(target_database)
    second = await restarted.list_target_nodes(
        user,
        version.id,
        parent_node_id=None,
        query=app.TargetPageQuery(cursor=first.next_cursor, limit=1),
    )
    assert second.total == 2 and second.items[0].id != first.items[0].id
    replaced = await svc.replace_target_draft(
        user,
        version.id,
        app.ReplaceTargetDraftCommand(NOW, content()),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    with pytest.raises(CursorValidationError):
        await svc.list_target_nodes(
            user,
            version.id,
            parent_node_id=None,
            query=app.TargetPageQuery(cursor=first.next_cursor, limit=1),
        )
    published = await publish(svc, user, replaced)
    first = await svc.list_target_nodes(
        user, version.id, parent_node_id=None, query=app.TargetPageQuery(limit=1)
    )
    await svc.archive_target_version(
        user,
        version.id,
        if_match=published.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    second = await restarted.list_target_nodes(
        user,
        version.id,
        parent_node_id=None,
        query=app.TargetPageQuery(cursor=first.next_cursor, limit=1),
    )
    assert second.total == 2


@pytest.mark.asyncio
async def test_first_target_collection_has_atomic_hard_owner_quota(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    user = principal(uuid4())
    with target_database[1]() as session, session.begin():
        session.add(OwnerModel(id=UUID(user.owner_id), display_name="Quota owner"))
    svc = service(target_database)
    for index in range(2):
        await svc.create_virtual_portfolio(
            user,
            app.CreateVirtualPortfolioCommand(f"Quota {index}", CurrencyCode("EUR")),
            idempotency_key=uuid4().hex,
            correlation_id="target-test",
        )
    bounded = service(target_database, max_active_collection_members_per_owner=1)
    with pytest.raises(CollectionSnapshotCapacityError):
        await bounded.list_virtual_portfolios(
            user, query=app.VirtualPortfolioQuery(state=app.VirtualPortfolioStateFilter.ALL)
        )
    with target_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == UUID(user.owner_id))
            )
            == 0
        )
    exact = service(target_database, max_active_collection_members_per_owner=2)
    page = await exact.list_virtual_portfolios(
        user, query=app.VirtualPortfolioQuery(state=app.VirtualPortfolioStateFilter.ALL, limit=1)
    )
    assert page.total == 2 and page.next_cursor
    next_page = await service(target_database).list_virtual_portfolios(
        user,
        query=app.VirtualPortfolioQuery(
            state=app.VirtualPortfolioStateFilter.ALL, cursor=page.next_cursor, limit=1
        ),
    )
    assert next_page.total == 2 and next_page.items[0].id != page.items[0].id


@pytest.mark.asyncio
async def test_validation_adjustments_survive_draft_node_replacement(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user, normalized=False)
    validated = await svc.validate_target_version(
        user,
        version.id,
        app.ValidateTargetCommand(True),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    replacement = d.TargetContent(
        (d.TargetNode("new-cash", None, d.TargetNodeKind.CASH, "Cash only", 0, Decimal(1)),)
    )
    await svc.replace_target_draft(
        user,
        version.id,
        app.ReplaceTargetDraftCommand(NOW, replacement),
        if_match=validated.etag,
        idempotency_key=uuid4().hex,
        correlation_id="target-test",
    )
    with target_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TargetNormalizationAdjustmentModel)
                .where(TargetNormalizationAdjustmentModel.validation_id == UUID(validated.id))
            )
            == 2
        )
        assert session.get(TargetValidationResultModel, UUID(validated.id)) is not None


@pytest.mark.asyncio
async def test_concurrent_publication_has_one_command_and_audit_chain(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user)
    validation = await svc.validate_target_version(
        user,
        version.id,
        app.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="publication-race",
    )
    key = uuid4().hex
    published = await asyncio.gather(
        *(
            svc.publish_target_version(
                user,
                version.id,
                app.PublishTargetCommand(validation.id),
                if_match=validation.etag,
                idempotency_key=key,
                correlation_id="publication-race",
            )
            for _ in range(8)
        )
    )
    assert len({item.revision for item in published}) == 1
    with target_database[1]() as session:
        events = tuple(
            session.scalars(
                select(TargetVersionEventModel)
                .where(TargetVersionEventModel.target_version_id == UUID(version.id))
                .order_by(TargetVersionEventModel.sequence)
            )
        )
        assert [event.kind for event in events] == [
            "draft_created",
            "validated",
            "published",
            "activated",
        ]
        assert events[0].previous_event_id is None
        assert [event.previous_event_id for event in events[1:]] == [
            event.id for event in events[:-1]
        ]
        assert (
            session.scalar(
                select(func.count())
                .select_from(TargetCommandIdentityModel)
                .where(
                    TargetCommandIdentityModel.command_kind == "publish_version",
                    TargetCommandIdentityModel.target_version_id == UUID(version.id),
                )
            )
            == 1
        )
    with pytest.raises(app.TargetServiceError) as stale:
        await svc.publish_target_version(
            user,
            version.id,
            app.PublishTargetCommand(validation.id),
            if_match=validation.etag,
            idempotency_key=uuid4().hex,
            correlation_id="publication-race",
        )
    assert stale.value.code is app.TargetServiceErrorCode.REVISION_MISMATCH


@pytest.mark.asyncio
async def test_template_clone_keeps_source_provenance_and_separate_parent(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, source = await draft(svc, user)
    template = await svc.create_virtual_portfolio(
        user,
        app.CreateVirtualPortfolioCommand("Clone template", CurrencyCode("EUR")),
        idempotency_key=uuid4().hex,
        correlation_id="clone-test",
    )
    clone = await svc.create_target_version(
        user,
        template.id,
        app.CreateTargetVersionCommand(NOW, source_version_id=source.id),
        if_match=template.etag,
        idempotency_key=uuid4().hex,
        correlation_id="clone-test",
    )
    assert clone.content == source.content and clone.source_version_id == source.id
    with target_database[1]() as session:
        row = session.get(TargetVersionModel, UUID(clone.id))
        assert row and row.source_version_id == UUID(source.id) and row.parent_version_id is None
        assert row.schema_version == 1 and row.method_version == d.TARGET_VALIDATION_VERSION
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(TargetVersionModel)
            .where(TargetVersionModel.id == UUID(clone.id))
            .values(parent_version_id=UUID(source.id))
        )


@pytest.mark.asyncio
async def test_invalid_draft_hierarchy_remains_inspectable_and_parent_is_scoped(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user, normalized=False)
    value = content(normalized=False)
    hierarchical = replace(
        value,
        nodes=(
            d.TargetNode("group", None, d.TargetNodeKind.GROUP, "Group", 0, Decimal("0.8")),
            replace(value.nodes[0], parent_key="group", weight=Decimal("0.9")),
            value.nodes[1],
        ),
    )
    version = await svc.replace_target_draft(
        user,
        version.id,
        app.ReplaceTargetDraftCommand(NOW, hierarchical),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="invalid-draft",
    )
    first = await svc.list_target_nodes(
        user, version.id, parent_node_id=None, query=app.TargetPageQuery(limit=100)
    )
    assert [item.node.key for item in first.items] == ["group", "holding", "cash"]
    branch = await svc.list_target_nodes(
        user, version.id, parent_node_id=first.items[0].id, query=app.TargetPageQuery()
    )
    assert [item.node.key for item in branch.items] == ["holding"]
    with pytest.raises(app.TargetServiceError) as missing:
        await svc.list_target_nodes(
            user, version.id, parent_node_id=str(uuid4()), query=app.TargetPageQuery()
        )
    assert missing.value.code is app.TargetServiceErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_constraint_exclusion_roundtrip_and_invalid_relational_input_rolls_back(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user)
    identity = build_synthetic_identity()
    constraints = (
        d.TargetConstraint(
            "reserve",
            d.TargetConstraintKind.CASH_RESERVE,
            amount=Decimal("10.25"),
            currency=CurrencyCode("EUR"),
        ),
        d.TargetConstraint(
            "minimum",
            d.TargetConstraintKind.MINIMUM_FUNDED_AMOUNT,
            node_key="holding",
            amount=Decimal("1"),
            currency=CurrencyCode("EUR"),
        ),
    )
    replacement = replace(
        content(),
        constraints=constraints,
        exclusions=(
            d.TargetExclusion("exclude", listing_id=identity.listing.id, reason="Owner choice"),
        ),
    )
    version = await svc.replace_target_draft(
        user,
        version.id,
        app.ReplaceTargetDraftCommand(NOW, replacement),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="constraints",
    )
    assert set(version.content.constraints) == set(constraints)
    assert version.content.exclusions == replacement.exclusions
    invalid = replace(
        replacement, constraints=(replace(constraints[0], currency=CurrencyCode("USD")),)
    )
    key = uuid4().hex
    with pytest.raises(app.TargetServiceError) as rejected:
        await svc.replace_target_draft(
            user,
            version.id,
            app.ReplaceTargetDraftCommand(NOW, invalid),
            if_match=version.etag,
            idempotency_key=key,
            correlation_id="constraints",
        )
    assert rejected.value.code is app.TargetServiceErrorCode.VALIDATION_FAILED
    assert rejected.value.__cause__ is None and rejected.value.__context__ is None
    unchanged = await svc.get_target_version(user, version.id)
    assert unchanged == version
    with target_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TargetCommandIdentityModel)
                .where(TargetCommandIdentityModel.idempotency_key == key)
            )
            == 0
        )
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(TargetConstraintModel)
            .where(TargetConstraintModel.target_version_id == UUID(version.id))
            .values(enabled=True)
        )
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            text("UPDATE target_constraints SET amount='NaN'::numeric WHERE target_version_id=:id"),
            {"id": UUID(version.id)},
        )
    absent = replace(
        content(),
        nodes=(
            replace(
                content().nodes[0],
                holding=d.TargetHoldingMapping(d.TargetMappingState.RESOLVED, uuid4()),
            ),
            content().nodes[1],
        ),
    )
    with pytest.raises(app.TargetServiceError) as missing:
        await svc.replace_target_draft(
            user,
            version.id,
            app.ReplaceTargetDraftCommand(NOW, absent),
            if_match=version.etag,
            idempotency_key=uuid4().hex,
            correlation_id="constraints",
        )
    assert missing.value.code is app.TargetServiceErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_synthetic_target_seed_repeats_without_changes_and_preserves_owner_edits(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    from trading212_worker.target_seed import seed_target_scenarios

    sessions = target_database[1]
    first = await seed_target_scenarios(sessions, app_environment="test", at=NOW)

    def counts() -> tuple[int, ...]:
        with sessions() as session:
            return tuple(
                int(session.scalar(select(func.count()).select_from(model)) or 0)
                for model in TARGET_MODELS
            )

    original_counts = counts()
    with sessions() as session:
        original_digests = {
            identifier: digest
            for identifier, digest in session.execute(
                select(TargetVersionModel.id, TargetVersionModel.content_digest)
            )
        }
    assert await seed_target_scenarios(sessions, app_environment="test", at=NOW) == first
    assert counts() == original_counts
    with sessions() as session:
        assert {
            identifier: digest
            for identifier, digest in session.execute(
                select(TargetVersionModel.id, TargetVersionModel.content_digest)
            )
        } == original_digests
    svc, user = service(target_database), principal()
    portfolio = await svc.get_virtual_portfolio(user, first["account_portfolio_id"])
    edited = await svc.update_virtual_portfolio(
        user,
        portfolio.id,
        app.UpdateVirtualPortfolioCommand(name="Owner edited seed name"),
        if_match=portfolio.etag,
        idempotency_key=uuid4().hex,
        correlation_id="seed-test",
    )
    edited_counts = counts()
    assert await seed_target_scenarios(sessions, app_environment="local", at=NOW) == first
    assert await svc.get_virtual_portfolio(user, portfolio.id) == edited
    assert counts() == edited_counts
    with pytest.raises(RuntimeError, match="restricted to local/test"):
        await seed_target_scenarios(sessions, app_environment="production", at=NOW)
    assert counts() == edited_counts


@pytest.mark.asyncio
async def test_portfolio_cursor_pins_active_version_and_order_but_discloses_current_metadata(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    label = uuid4().hex
    portfolios = [
        await svc.create_virtual_portfolio(
            user,
            app.CreateVirtualPortfolioCommand(label + suffix, CurrencyCode("EUR")),
            idempotency_key=uuid4().hex,
            correlation_id="frozen-membership",
        )
        for suffix in ("A", "B")
    ]
    selected = portfolios[1]
    version = await svc.create_target_version(
        user,
        selected.id,
        app.CreateTargetVersionCommand(NOW, content=content()),
        if_match=selected.etag,
        idempotency_key=uuid4().hex,
        correlation_id="frozen-membership",
    )
    published = await publish(svc, user, version)
    query = app.VirtualPortfolioQuery(
        search=label, state=app.VirtualPortfolioStateFilter.ALL, limit=1
    )
    first = await svc.list_virtual_portfolios(user, query=query)
    assert first.items[0].id == portfolios[0].id and first.next_cursor
    selected = await svc.get_virtual_portfolio(user, selected.id)
    selected = await svc.update_virtual_portfolio(
        user,
        selected.id,
        app.UpdateVirtualPortfolioCommand(name=label + "0"),
        if_match=selected.etag,
        idempotency_key=uuid4().hex,
        correlation_id="frozen-membership",
    )
    replacement = await svc.create_target_version(
        user,
        selected.id,
        app.CreateTargetVersionCommand(NOW, source_version_id=published.id),
        if_match=selected.etag,
        idempotency_key=uuid4().hex,
        correlation_id="frozen-membership",
    )
    replacement = await publish(svc, user, replacement)
    continuation = replace(query, cursor=first.next_cursor)
    second = await service(target_database).list_virtual_portfolios(user, query=continuation)
    assert second.total == 2 and second.next_cursor is None
    assert second.items[0].id == selected.id
    assert second.items[0].active_version_id == published.id != replacement.id
    assert second.items[0].name == label + "0"
    current = await svc.get_virtual_portfolio(user, selected.id)
    assert second.items[0].revision == current.revision
    assert await svc.list_virtual_portfolios(user, query=continuation) == second


@pytest.mark.asyncio
async def test_concurrent_target_queries_share_one_hard_owner_reservation(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    user = principal(uuid4())
    with target_database[1]() as session, session.begin():
        session.add(OwnerModel(id=UUID(user.owner_id), display_name="Concurrent quota owner"))
    svc = service(
        target_database,
        max_active_collection_snapshots_per_owner=1,
        max_active_collection_members_per_owner=2,
    )
    for index in range(2):
        await svc.create_virtual_portfolio(
            user,
            app.CreateVirtualPortfolioCommand(f"Concurrent {index}", CurrencyCode("EUR")),
            idempotency_key=uuid4().hex,
            correlation_id="quota-race",
        )
    outcomes = await asyncio.gather(
        *(
            svc.list_virtual_portfolios(
                user,
                query=app.VirtualPortfolioQuery(state=app.VirtualPortfolioStateFilter.ALL, limit=1),
            )
            for _ in range(8)
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(outcome, BaseException) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, CollectionSnapshotCapacityError) for outcome in outcomes) == 7
    with target_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CollectionQuerySnapshotModel)
                .where(CollectionQuerySnapshotModel.owner_id == UUID(user.owner_id))
            )
            == 1
        )


@pytest.mark.asyncio
async def test_disjoint_listing_selectors_revalidate_catalog_and_seal_mapping_decisions(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user)
    identity = build_synthetic_identity()
    listing_id, other_instrument = uuid4(), uuid4()
    with target_database[1]() as session, session.begin():
        session.add(
            InstrumentModel(
                id=other_instrument,
                canonical_name="Synthetic other instrument",
                instrument_type="ETF",
            )
        )
        session.add(
            ListingModel(
                id=listing_id,
                instrument_id=identity.instrument.id,
                provider="synthetic",
                environment="synthetic",
                provider_instrument_id=str(listing_id),
                ticker="SYNTH2",
                trading_currency="EUR",
                status="active",
                valid_from=NOW,
            )
        )
    base = content().nodes[0]
    content_value = d.TargetContent(
        (
            replace(base, weight=Decimal("0.5")),
            replace(
                base,
                key="second",
                order=1,
                weight=Decimal("0.5"),
                holding=d.TargetHoldingMapping(
                    d.TargetMappingState.RESOLVED,
                    identity.instrument.id,
                    listing_id,
                    listing_id,
                ),
            ),
        )
    )
    version = await svc.replace_target_draft(
        user,
        version.id,
        app.ReplaceTargetDraftCommand(NOW, content_value),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="selector-test",
    )
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(TargetHoldingModel)
            .where(
                TargetHoldingModel.target_version_id == UUID(version.id),
                TargetHoldingModel.listing_id == listing_id,
            )
            .values(listing_id=None)
        )
    with pytest.raises(IntegrityError), target_database[0].begin() as connection:
        connection.execute(
            update(TargetHoldingModel)
            .where(
                TargetHoldingModel.target_version_id == UUID(version.id),
                TargetHoldingModel.listing_id == listing_id,
            )
            .values(preferred_listing_id=identity.listing.id)
        )
    validation = await svc.validate_target_version(
        user,
        version.id,
        app.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="selector-test",
    )
    assert validation.valid
    assert any(issue.code == "duplicate_economic_exposure" for issue in validation.issues)
    with target_database[0].begin() as connection:
        connection.execute(
            update(ListingModel)
            .where(ListingModel.id == listing_id)
            .values(instrument_id=other_instrument)
        )
    with pytest.raises(app.TargetServiceError) as changed:
        await svc.publish_target_version(
            user,
            version.id,
            app.PublishTargetCommand(validation.id),
            if_match=validation.etag,
            idempotency_key=uuid4().hex,
            correlation_id="selector-test",
        )
    assert changed.value.code is app.TargetServiceErrorCode.TARGET_VALIDATION_FAILED
    with target_database[0].begin() as connection:
        connection.execute(
            update(ListingModel)
            .where(ListingModel.id == listing_id)
            .values(instrument_id=identity.instrument.id)
        )
    published = await svc.publish_target_version(
        user,
        version.id,
        app.PublishTargetCommand(validation.id),
        if_match=validation.etag,
        idempotency_key=uuid4().hex,
        correlation_id="selector-test",
    )
    assert published.content_digest == validation.result_digest
    for model in (TargetHoldingModel, TargetMappingDecisionModel):
        with pytest.raises(IntegrityError), target_database[0].begin() as connection:
            connection.execute(
                update(model)
                .where(model.target_version_id == UUID(version.id))
                .values(created_at=NOW + timedelta(seconds=1))
            )
    with target_database[0].begin() as connection:
        connection.execute(
            update(ListingModel)
            .where(ListingModel.id == listing_id)
            .values(instrument_id=other_instrument)
        )
    assert await svc.get_target_version(user, version.id) == published
    with target_database[0].begin() as connection:
        connection.execute(
            update(ListingModel)
            .where(ListingModel.id == listing_id)
            .values(instrument_id=identity.instrument.id)
        )


@pytest.mark.asyncio
async def test_unresolved_mapping_is_explicit_and_publishable_with_warning(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    _, version = await draft(svc, user)
    value = content()
    unresolved = replace(
        value,
        nodes=(
            replace(
                value.nodes[0],
                holding=d.TargetHoldingMapping(
                    d.TargetMappingState.UNRESOLVED,
                    requested_identifier=d.TargetIdentifier(
                        d.TargetIdentifierKind.PROVIDER_KEY, "synthetic-pending", "synthetic"
                    ),
                    reason="Owner has not resolved the instrument",
                ),
            ),
            value.nodes[1],
        ),
    )
    version = await svc.replace_target_draft(
        user,
        version.id,
        app.ReplaceTargetDraftCommand(NOW, unresolved),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="unresolved-target",
    )
    published = await publish(svc, user, version)
    assert published.latest_validation and published.latest_validation.valid
    assert any(issue.code == "mapping_unresolved" for issue in published.latest_validation.issues)
    assert (
        next(node.holding for node in published.content.nodes if node.key == "holding")
        == unresolved.nodes[0].holding
    )
    with target_database[1]() as session:
        holding = session.scalar(
            select(TargetHoldingModel).where(
                TargetHoldingModel.target_version_id == UUID(version.id)
            )
        )
        assert holding and holding.instrument_id is None and holding.mapping_state == "unresolved"


@pytest.mark.asyncio
async def test_database_failure_rolls_back_and_discards_exception_parameters(
    target_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import traceback

    from sqlalchemy.exc import ProgrammingError

    svc, user = service(target_database), principal()
    canary = "synthetic-target-database-parameter-canary-" + uuid4().hex
    key = uuid4().hex

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise ProgrammingError(
            "SELECT unsafe_target_statement", {"name": canary}, RuntimeError(canary)
        )

    monkeypatch.setattr(svc, "_portfolio_event", fail_audit)
    with pytest.raises(app.TargetServiceError) as unavailable:
        await svc.create_virtual_portfolio(
            user,
            app.CreateVirtualPortfolioCommand(canary, CurrencyCode("EUR")),
            idempotency_key=key,
            correlation_id="failure-canary",
        )
    error = unavailable.value
    assert error.code is app.TargetServiceErrorCode.TARGETS_UNAVAILABLE
    assert error.__cause__ is None and error.__context__ is None
    assert canary not in str(error) + "".join(traceback.format_exception(error)) + caplog.text
    with target_database[1]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(VirtualPortfolioModel)
                .where(VirtualPortfolioModel.name == canary)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TargetCommandIdentityModel)
                .where(TargetCommandIdentityModel.idempotency_key == key)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_published_version_comparison_is_exact_bidirectional_and_restart_stable(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    portfolio, first = await draft(svc, user)
    first = await publish(svc, user, first)
    original_content, original_digest = first.content, first.content_digest
    current_portfolio = await svc.get_virtual_portfolio(user, portfolio.id)
    second = await svc.create_target_version(
        user,
        portfolio.id,
        app.CreateTargetVersionCommand(NOW, source_version_id=first.id),
        if_match=current_portfolio.etag,
        idempotency_key=uuid4().hex,
        correlation_id="published-comparison",
    )
    changed = replace(
        second.content,
        nodes=tuple(
            replace(node, weight=Decimal("0.7") if node.key == "holding" else Decimal("0.3"))
            for node in second.content.nodes
        ),
    )
    second = await svc.replace_target_draft(
        user,
        second.id,
        app.ReplaceTargetDraftCommand(NOW, changed),
        if_match=second.etag,
        idempotency_key=uuid4().hex,
        correlation_id="published-comparison",
    )
    second = await publish(svc, user, second)
    assert first.published_at and second.published_at
    forward = await svc.compare_target_versions(user, portfolio.id, first.id, second.id)
    reverse = await svc.compare_target_versions(user, portfolio.id, second.id, first.id)
    changes = {}
    for change in forward.comparison.node_changes:
        assert change.left and change.right
        assert change.changed_fields == ("weight",)
        changes[change.key] = (change.left.weight, change.right.weight)
    assert changes == {
        "cash": (Decimal("0.2"), Decimal("0.3")),
        "holding": (Decimal("0.8"), Decimal("0.7")),
    }
    for change in reverse.comparison.node_changes:
        assert change.left and change.right
        assert change.changed_fields == ("weight",)
        assert (change.right.weight, change.left.weight) == changes[change.key]
    assert not forward.comparison.constraint_changes
    assert not forward.comparison.exclusion_changes
    assert not forward.comparison.effective_time_changed
    restarted = service(target_database)
    assert (
        await restarted.compare_target_versions(user, portfolio.id, first.id, second.id) == forward
    )
    assert (
        await restarted.compare_target_versions(user, portfolio.id, second.id, first.id) == reverse
    )
    historical = await restarted.get_target_version(user, first.id)
    assert historical.content == original_content and historical.content_digest == original_digest
    assert historical.state is app.TargetVersionState.SUPERSEDED
    assert (
        await restarted.get_target_version(user, second.id)
    ).state is app.TargetVersionState.ACTIVE
    assert (
        await restarted.get_virtual_portfolio(user, portfolio.id)
    ).active_version_id == second.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("publication_delay", "explicit_effective_delay"),
    (
        (timedelta(days=2), timedelta(days=1, hours=12)),
        (timedelta(days=2), timedelta(days=-1)),
        (timedelta(days=1), timedelta(days=1)),
    ),
    ids=("newer-effective", "explicit-backdated", "exact-due-boundary"),
)
async def test_dispatcher_outage_supersedes_overtaken_schedule_without_regressing_active_target(
    target_database: tuple[Engine, sessionmaker[Session]],
    publication_delay: timedelta,
    explicit_effective_delay: timedelta,
) -> None:
    clock = [NOW]
    svc = PostgresTargetService(
        sessions=target_database[1], cursor_signing_key=KEY, clock=lambda: clock[0]
    )
    user = principal()
    portfolio, overdue = await draft(svc, user, effective_at=NOW + timedelta(days=1))
    overdue = await publish(svc, user, overdue)
    assert overdue.state is app.TargetVersionState.SCHEDULED
    original_content, original_digest = overdue.content, overdue.content_digest
    current = await svc.get_virtual_portfolio(user, portfolio.id)
    future = await svc.create_target_version(
        user,
        portfolio.id,
        app.CreateTargetVersionCommand(NOW + timedelta(days=3), source_version_id=overdue.id),
        if_match=current.etag,
        idempotency_key=uuid4().hex,
        correlation_id="dispatcher-outage",
    )
    future = await publish(svc, user, future)
    clock[0] = NOW + publication_delay
    current = await svc.get_virtual_portfolio(user, portfolio.id)
    explicit = await svc.create_target_version(
        user,
        portfolio.id,
        app.CreateTargetVersionCommand(
            NOW + explicit_effective_delay, source_version_id=overdue.id
        ),
        if_match=current.etag,
        idempotency_key=uuid4().hex,
        correlation_id="dispatcher-outage",
    )
    explicit = await publish(svc, user, explicit)
    assert explicit.state is app.TargetVersionState.ACTIVE
    current = await svc.get_virtual_portfolio(user, portfolio.id)
    assert await svc.activate_due_versions(limit=1) == 0
    missed = await svc.get_target_version(user, overdue.id)
    assert missed.state is app.TargetVersionState.SUPERSEDED
    assert missed.content == original_content and missed.content_digest == original_digest
    assert missed.effective_at == overdue.effective_at
    assert missed.revision == overdue.revision + 1
    assert await svc.get_virtual_portfolio(user, portfolio.id) == current
    assert await svc.get_target_version(user, explicit.id) == explicit
    assert await svc.activate_due_versions(limit=1) == 0
    with target_database[1]() as session:
        events = tuple(
            session.scalars(
                select(TargetVersionEventModel)
                .where(TargetVersionEventModel.target_version_id == UUID(overdue.id))
                .order_by(TargetVersionEventModel.sequence)
            )
        )
        assert [event.kind for event in events] == [
            "draft_created",
            "validated",
            "published",
            "superseded",
        ]
        assert events[-1].created_at == clock[0]
        assert events[-1].effective_at == overdue.effective_at
        assert events[-1].actor_principal_id == "system:target-scheduler"
    assert (await svc.get_target_version(user, future.id)).state is app.TargetVersionState.SCHEDULED
    clock[0] = NOW + timedelta(days=3)
    assert await svc.activate_due_versions(limit=1) == 1
    assert (await svc.get_virtual_portfolio(user, portfolio.id)).active_version_id == future.id
    assert (
        await svc.get_target_version(user, explicit.id)
    ).state is app.TargetVersionState.SUPERSEDED
    assert await svc.activate_due_versions(limit=1) == 0


@pytest.mark.asyncio
async def test_atomic_portfolio_target_read_holds_one_revision_across_concurrent_replacement(
    target_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from trading212_application.views import Page

    reader, writer, user = service(target_database), service(target_database), principal()
    portfolio, version = await draft(writer, user)
    metadata_read, release_read = Event(), Event()
    original_page = reader._target_nodes_page

    def paused_page(
        session: Session,
        selected_version: TargetVersionModel,
        selected_portfolio: VirtualPortfolioModel,
        *,
        parent_node_id: str | None,
        query: app.TargetPageQuery,
    ) -> Page[app.TargetHierarchyNodeView]:
        metadata_read.set()
        assert release_read.wait(10), "atomic read was never released"
        return original_page(
            session,
            selected_version,
            selected_portfolio,
            parent_node_id=parent_node_id,
            query=query,
        )

    monkeypatch.setattr(reader, "_target_nodes_page", paused_page)
    read_task = asyncio.create_task(
        reader.get_virtual_portfolio_targets(
            user,
            portfolio.id,
            account_id=portfolio.account_id,
            target_version_id=version.id,
            parent_node_id=None,
            query=app.TargetPageQuery(limit=1),
        )
    )
    write_task = None
    try:
        assert await asyncio.to_thread(metadata_read.wait, 5)
        replacement = d.TargetContent(
            (
                d.TargetNode(
                    "replacement-cash", None, d.TargetNodeKind.CASH, "Replacement", 0, Decimal(1)
                ),
            )
        )
        write_task = asyncio.create_task(
            writer.replace_target_draft(
                user,
                version.id,
                app.ReplaceTargetDraftCommand(NOW, replacement),
                if_match=version.etag,
                idempotency_key=uuid4().hex,
                correlation_id="atomic-read-race",
            )
        )

        def writer_is_waiting() -> bool:
            with target_database[0].connect() as connection:
                return bool(
                    connection.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                            "AND NOT granted AND database=(SELECT oid FROM pg_database "
                            "WHERE datname=current_database()))"
                        )
                    )
                )

        for _ in range(100):
            if await asyncio.to_thread(writer_is_waiting):
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("concurrent mutation did not block on the atomic read lock")
        assert not write_task.done()
    finally:
        release_read.set()
    result = await read_task
    assert write_task is not None
    changed = await write_task
    assert result.version == version
    assert result.nodes.total == 2 and result.nodes.next_cursor
    assert result.nodes.items[0].node in version.content.nodes
    assert changed.content == replacement and changed.revision == version.revision + 1
    with pytest.raises(CursorValidationError):
        await writer.get_virtual_portfolio_targets(
            user,
            portfolio.id,
            account_id=portfolio.account_id,
            target_version_id=version.id,
            parent_node_id=None,
            query=app.TargetPageQuery(limit=1, cursor=result.nodes.next_cursor),
        )
    fresh = await writer.get_virtual_portfolio_targets(
        user,
        portfolio.id,
        account_id=portfolio.account_id,
        target_version_id=version.id,
        parent_node_id=None,
        query=app.TargetPageQuery(limit=1),
    )
    assert fresh.version == changed
    assert fresh.nodes.total == 1 and fresh.nodes.items[0].node == replacement.nodes[0]


@pytest.mark.asyncio
async def test_atomic_portfolio_target_read_enforces_scope_selection_and_empty_state(
    target_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    svc, user = service(target_database), principal()
    portfolio, draft_version = await draft(svc, user)
    empty = await svc.get_virtual_portfolio_targets(
        user,
        portfolio.id,
        account_id=portfolio.account_id,
        target_version_id=None,
        parent_node_id=None,
        query=app.TargetPageQuery(),
    )
    assert empty.version is None and empty.nodes.total == 0 and not empty.nodes.items
    for parent, cursor in ((str(uuid4()), None), (None, "opaque-cursor")):
        with pytest.raises(app.TargetServiceError) as missing:
            await svc.get_virtual_portfolio_targets(
                user,
                portfolio.id,
                account_id=portfolio.account_id,
                target_version_id=None,
                parent_node_id=parent,
                query=app.TargetPageQuery(cursor=cursor),
            )
        assert missing.value.code is app.TargetServiceErrorCode.NOT_FOUND
    published = await publish(svc, user, draft_version)
    selected = await svc.get_virtual_portfolio_targets(
        user,
        portfolio.id,
        account_id=portfolio.account_id,
        target_version_id=None,
        parent_node_id=None,
        query=app.TargetPageQuery(),
    )
    assert selected.version == published and selected.nodes.total == 2
    other_portfolio, other_version = await draft(svc, user)
    assert other_portfolio.id != portfolio.id
    for account, version_id in ((None, published.id), (portfolio.account_id, other_version.id)):
        with pytest.raises(app.TargetServiceError) as wrong_scope:
            await svc.get_virtual_portfolio_targets(
                user,
                portfolio.id,
                account_id=account,
                target_version_id=version_id,
                parent_node_id=None,
                query=app.TargetPageQuery(),
            )
        assert wrong_scope.value.code is app.TargetServiceErrorCode.NOT_FOUND
    for missing_scope in (Scope.PORTFOLIO_READ, Scope.TARGETS_READ):
        with pytest.raises(AuthorizationError):
            await svc.get_virtual_portfolio_targets(
                replace(user, scopes=user.scopes - {missing_scope}),
                portfolio.id,
                account_id=portfolio.account_id,
                target_version_id=published.id,
                parent_node_id=None,
                query=app.TargetPageQuery(),
            )
    template = await svc.create_virtual_portfolio(
        user,
        app.CreateVirtualPortfolioCommand("Atomic template", CurrencyCode("EUR")),
        idempotency_key=uuid4().hex,
        correlation_id="atomic-template",
    )
    with pytest.raises(AuthorizationError):
        await svc.get_virtual_portfolio_targets(
            replace(user, scopes=user.scopes - {Scope.PORTFOLIO_READ}),
            template.id,
            account_id=None,
            target_version_id=None,
            parent_node_id=None,
            query=app.TargetPageQuery(),
        )
