"""Closed definition operations, source-aware rows and stable collection identities."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

import pytest
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import Session
from trading212_application import projection as app
from trading212_application.projection_capture import (
    ProjectionDatedSchedule,
    ProjectionGoalVersionContent,
)
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_application.queries import CursorCodec
from trading212_domain.projection import ProjectionAsset, ProjectionAssumptions
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.collection_snapshots import (
    CollectionSnapshotPage,
    CollectionSnapshotResource,
)
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_models import (
    AssumptionSetModel,
    AssumptionVersionModel,
    GoalModel,
    GoalVersionModel,
)
from trading212_persistence.projection_service_definitions import ProjectionDefinitionService
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_security.principals import AuthorizationError, Principal, Scope

AT = datetime(2026, 8, 31, 12, tzinfo=UTC)
OWNER, ACCOUNT, IDENTITY, AGGREGATE, VERSION = (UUID(int=index) for index in range(100, 105))
PRINCIPAL = Principal(
    str(IDENTITY),
    str(OWNER),
    "synthetic.issuer",
    "projection-reader",
    frozenset(Scope),
    AT - timedelta(minutes=1),
    AT + timedelta(days=1),
)
AUTH = ReportAuthorization(
    principal_id=IDENTITY,
    owner_id=OWNER,
    account_id=ACCOUNT,
    required_scopes=frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
    expires_at=PRINCIPAL.expires_at,
    issuer=PRINCIPAL.issuer,
    subject=PRINCIPAL.subject,
    requesting_principal=PRINCIPAL,
)
pytestmark = pytest.mark.unit


def commands() -> tuple[
    app.CreateAssumptionSet, app.CreateAssumptionVersion, app.CreateGoal, app.CreateGoalVersion
]:
    metadata = ProjectionVersionMetadata(
        name="Synthetic immutable version", description="Exact values"
    )
    assumptions = ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="alpha",
                annual_mean_log_return=Decimal(".03"),
                annual_volatility=Decimal(".1"),
                weight=Decimal(1),
            ),
        ),
        correlation=((Decimal(1),),),
        reporting_currency=CurrencyCode("EUR"),
    )
    goal = ProjectionGoalVersionContent(
        assumption_version_id=VERSION,
        target=Money.parse("123.123456789012345678", "EUR"),
        target_date=date(2027, 8, 31),
        months=12,
        basis="real",
        probability_objective=Decimal(".75"),
        schedule=ProjectionDatedSchedule(base_monthly=Money.parse("5.123456789012345678", "EUR")),
    )
    return (
        app.CreateAssumptionSet(
            account_id=ACCOUNT,
            metadata=metadata,
            content=assumptions,
            idempotency_key="create-assumption-key",
            correlation_id="trace-one",
        ),
        app.CreateAssumptionVersion(
            set_id=AGGREGATE,
            expected_revision=7,
            metadata=metadata,
            content=assumptions,
            idempotency_key="create-assumption-version-key",
            correlation_id="trace-two",
        ),
        app.CreateGoal(
            account_id=ACCOUNT,
            metadata=metadata,
            content=goal,
            idempotency_key="create-goal-key",
            correlation_id="trace-three",
        ),
        app.CreateGoalVersion(
            goal_id=AGGREGATE,
            expected_revision=8,
            metadata=metadata,
            content=goal,
            idempotency_key="create-goal-version-key",
            correlation_id="trace-four",
        ),
    )


def service() -> ProjectionDefinitionService:
    # Operation delegation tests isolate the inherited transaction boundary. Real
    # source/grant database behavior remains in the store and integration tests.
    return object.__new__(ProjectionDefinitionService)


def collection_page() -> CollectionSnapshotPage:
    return CollectionSnapshotPage(
        snapshot_id=UUID(int=300),
        record_ids=(UUID(int=301), UUID(int=302)),
        next_cursor="signed_continuation",
        limit=2,
        exact_total=8,
        expires_at=AT + timedelta(minutes=5),
        source_snapshot_id=None,
    )


@pytest.mark.parametrize(
    "index,method,publisher,write,resource",
    [
        (0, "create_assumption_set", "publish_assumption_set", "assumption", None),
        (
            1,
            "create_assumption_version",
            "publish_assumption_version",
            "assumption",
            AssumptionSetModel,
        ),
        (2, "create_goal", "publish_goal", "goal", None),
        (3, "create_goal_version", "publish_goal_version", "goal", GoalModel),
    ],
)
async def test_publication_preserves_exact_command_identity_and_required_write_family(
    index: int, method: str, publisher: str, write: str, resource: type[Any] | None
) -> None:
    store, session = service(), MagicMock(spec=Session)
    command = commands()[index]
    expected = object()

    async def execute(
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ReportAuthorization], Any],
        **kwargs: Any,
    ) -> Any:
        assert principal is PRINCIPAL
        assert account_id == (ACCOUNT if resource is None else None)
        assert kwargs == (
            {"write": write}
            if resource is None
            else {"write": write, "resource": (resource, AGGREGATE)}
        )
        return operation(session, AUTH)

    with (
        patch.object(store, "_execute", side_effect=execute),
        patch.object(store, publisher, return_value=expected) as publish,
    ):
        assert await getattr(store, method)(PRINCIPAL, command) is expected
    publish.assert_called_once_with(session, AUTH, command)
    assert publish.call_args.args[2] is command


@pytest.mark.parametrize(
    "method",
    ["create_assumption_set", "create_assumption_version", "create_goal", "create_goal_version"],
)
async def test_wrong_command_types_fail_before_transaction_or_idempotent_publication(
    method: str,
) -> None:
    store = service()
    with (
        patch.object(store, "_execute", new_callable=AsyncMock) as execute,
        pytest.raises(app.ProjectionServiceError) as caught,
    ):
        await getattr(store, method)(PRINCIPAL, object())
    assert caught.value.code is app.ProjectionErrorCode.VALIDATION_FAILED
    execute.assert_not_called()


@pytest.mark.parametrize(
    "method,reader,model",
    [
        ("get_assumption_set", "read_assumption_set", AssumptionSetModel),
        ("get_assumption_version", "read_assumption_version", AssumptionVersionModel),
        ("get_goal", "read_goal", GoalModel),
        ("get_goal_version", "read_goal_version", GoalVersionModel),
    ],
)
async def test_gets_resolve_owned_resource_and_use_current_authorized_immutable_reader(
    method: str, reader: str, model: type[Any]
) -> None:
    store, session = service(), MagicMock(spec=Session)
    value = object()

    async def execute(
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ReportAuthorization], Any],
        **kwargs: Any,
    ) -> Any:
        assert account_id is None and kwargs == {"resource": (model, VERSION)}
        return operation(session, AUTH)

    with (
        patch.object(store, "_execute", side_effect=execute),
        patch.object(store, reader, return_value=value) as read,
    ):
        assert await getattr(store, method)(PRINCIPAL, VERSION) is value
    read.assert_called_once_with(session, AUTH, VERSION)


_LISTS = (
    (
        "list_assumption_sets",
        "read_assumption_set",
        None,
        AssumptionSetModel,
        CollectionSnapshotResource.ASSUMPTION_SETS,
        "assumption_sets",
        None,
    ),
    (
        "list_assumption_versions",
        "read_assumption_version",
        "read_assumption_set",
        AssumptionVersionModel,
        CollectionSnapshotResource.ASSUMPTION_VERSIONS,
        "assumption_versions",
        "set_id",
    ),
    ("list_goals", "read_goal", None, GoalModel, CollectionSnapshotResource.GOALS, "goals", None),
    (
        "list_goal_versions",
        "read_goal_version",
        "read_goal",
        GoalVersionModel,
        CollectionSnapshotResource.GOAL_VERSIONS,
        "goal_versions",
        "goal_id",
    ),
)


@pytest.mark.parametrize("method,reader,parent,model,resource,table,parent_key", _LISTS)
async def test_collections_preserve_snapshot_order_total_and_current_authority_for_each_row(
    method: str,
    reader: str,
    parent: str | None,
    model: type[Any],
    resource: CollectionSnapshotResource,
    table: str,
    parent_key: str | None,
) -> None:
    store, session, snapshot = service(), MagicMock(spec=Session), collection_page()
    query = app.ProjectionPageQuery(limit=2, cursor="already_signed")
    events: list[object] = []
    returned = {identifier: object() for identifier in snapshot.record_ids}

    async def execute(
        principal: Principal,
        account: UUID | None,
        operation: Callable[[Session, ReportAuthorization], Any],
        **kwargs: Any,
    ) -> Any:
        assert principal is PRINCIPAL
        expected_model = AssumptionSetModel if parent_key == "set_id" else GoalModel
        assert account == (ACCOUNT if parent is None else None)
        assert kwargs == ({} if parent is None else {"resource": (expected_model, AGGREGATE)})
        return operation(session, AUTH)

    def build_page(
        given_session: Session,
        auth: ReportAuthorization,
        given_resource: CollectionSnapshotResource,
        given_query: app.ProjectionPageQuery,
        statement: Select[tuple[UUID]],
        *filters: object,
    ) -> CollectionSnapshotPage:
        assert given_session is session and auth is AUTH
        assert given_resource is resource and given_query is query
        assert filters == (() if parent is None else (AGGREGATE,))
        sql = str(statement.compile(dialect=PGDialect(), compile_kwargs={"literal_binds": True}))  # type: ignore[no-untyped-call]  # SQLAlchemy dialect constructor.
        assert f"{table}.owner_id = '{OWNER}'" in sql
        assert f"{table}.account_id = '{ACCOUNT}'" in sql
        if parent_key is not None:
            assert events == ["parent-authorized"]
            assert f"{table}.{parent_key} = '{AGGREGATE}'" in sql
            assert f"{table}.sealed IS true" in sql
        sort = "version_number" if parent_key is not None else "created_at"
        assert f"ORDER BY {table}.{sort} DESC, {table}.id DESC" in sql
        events.append("page")
        return snapshot

    def read(given_session: Session, auth: ReportAuthorization, identifier: UUID) -> object:
        assert given_session is session and auth is AUTH
        events.append(identifier)
        return returned[identifier]

    with (
        patch.object(store, "_execute", side_effect=execute),
        patch.object(store, "_page", side_effect=build_page),
        patch.object(store, reader, side_effect=read),
    ):
        if parent is not None:
            with patch.object(
                store, parent, side_effect=lambda *args: events.append("parent-authorized")
            ):
                result = await getattr(store, method)(PRINCIPAL, AGGREGATE, query)
        else:
            result = await getattr(store, method)(PRINCIPAL, ACCOUNT, query)
    assert result.items == tuple(returned[identifier] for identifier in snapshot.record_ids)
    assert (result.next_cursor, result.limit, result.total) == (snapshot.next_cursor, 2, 8)
    assert events[-3:] == ["page", *snapshot.record_ids]


@pytest.mark.parametrize("method,reader,parent,model,resource,table,parent_key", _LISTS)
async def test_restricted_row_fails_entire_collection_instead_of_returning_partial_success(
    method: str,
    reader: str,
    parent: str | None,
    model: type[Any],
    resource: CollectionSnapshotResource,
    table: str,
    parent_key: str | None,
) -> None:
    store, session = service(), MagicMock(spec=Session)

    async def execute(
        principal: Principal,
        account: UUID | None,
        operation: Callable[[Session, ReportAuthorization], Any],
        **kwargs: Any,
    ) -> Any:
        return operation(session, AUTH)

    with (
        patch.object(store, "_execute", side_effect=execute),
        patch.object(store, "_page", return_value=collection_page()),
        patch.object(
            store,
            reader,
            side_effect=[
                object(),
                ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE),
            ],
        ) as read,
        pytest.raises(ProjectionStorageError) as caught,
    ):
        if parent is None:
            await getattr(store, method)(PRINCIPAL, ACCOUNT, app.ProjectionPageQuery(limit=2))
        else:
            with patch.object(store, parent):
                await getattr(store, method)(PRINCIPAL, AGGREGATE, app.ProjectionPageQuery(limit=2))
    assert caught.value.code is app.ProjectionErrorCode.SOURCE_UNAVAILABLE
    assert read.call_args_list == [
        call(session, AUTH, item) for item in collection_page().record_ids
    ]


@pytest.mark.parametrize(
    "method,parent",
    [("list_assumption_versions", "read_assumption_set"), ("list_goal_versions", "read_goal")],
)
async def test_restricted_parent_precedes_version_cursor_resume(method: str, parent: str) -> None:
    store, session = service(), MagicMock(spec=Session)

    async def execute(
        principal: Principal,
        account: UUID | None,
        operation: Callable[[Session, ReportAuthorization], Any],
        **kwargs: Any,
    ) -> Any:
        return operation(session, AUTH)

    with (
        patch.object(store, "_execute", side_effect=execute),
        patch.object(
            store,
            parent,
            side_effect=ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE),
        ),
        patch.object(store, "_page") as pages,
        pytest.raises(ProjectionStorageError),
    ):
        await getattr(store, method)(
            PRINCIPAL, AGGREGATE, app.ProjectionPageQuery(cursor="bad-cursor")
        )
    pages.assert_not_called()


@pytest.mark.parametrize("method", [item[0] for item in _LISTS])
async def test_wrong_page_query_type_never_opens_transaction(method: str) -> None:
    store = service()
    with (
        patch.object(store, "_execute", new_callable=AsyncMock) as execute,
        pytest.raises(app.ProjectionServiceError) as caught,
    ):
        await getattr(store, method)(PRINCIPAL, ACCOUNT, object())
    assert caught.value.code is app.ProjectionErrorCode.VALIDATION_FAILED
    execute.assert_not_called()


def test_real_collection_binding_survives_token_refresh_but_changes_with_actor_or_query_scope() -> (
    None
):
    store = service()
    store._cursors = CursorCodec(b"synthetic-projection-cursor-key" * 2, clock=lambda: AT)
    session = MagicMock(spec=Session)
    statement = select(AssumptionVersionModel.id)
    query = app.ProjectionPageQuery(limit=2)
    with (
        patch.object(store, "_now", return_value=AT),
        patch.object(ReportAuthorization, "check"),
        patch("trading212_persistence.projection_service_base.CollectionSnapshotStore") as factory,
    ):

        def definition(
            auth: ReportAuthorization = AUTH,
            selected: app.ProjectionPageQuery = query,
            aggregate: UUID = AGGREGATE,
        ) -> Any:
            store._page(
                session,
                auth,
                CollectionSnapshotResource.ASSUMPTION_VERSIONS,
                selected,
                statement,
                aggregate,
            )
            return factory.return_value.materialize.call_args.args[0]

        original = definition()
        refreshed = replace(
            AUTH,
            requesting_principal=replace(
                PRINCIPAL, authenticated_at=AT, expires_at=AT + timedelta(days=2)
            ),
            expires_at=AT + timedelta(days=2),
        )
        assert definition(refreshed) == original
        for changed in (
            replace(AUTH, issuer="another.issuer"),
            replace(AUTH, subject="another-subject"),
            replace(AUTH, account_id=UUID(int=999)),
        ):
            assert definition(changed) != original
        assert definition(selected=app.ProjectionPageQuery(limit=3)) != original
        assert definition(aggregate=UUID(int=998)) != original


def test_current_grant_failure_precedes_real_collection_store_and_cursor() -> None:
    store = service()
    store._cursors = CursorCodec(b"synthetic-projection-cursor-key" * 2, clock=lambda: AT)
    with (
        patch.object(store, "_now", return_value=AT),
        patch.object(ReportAuthorization, "check", side_effect=AuthorizationError("denied")),
        patch("trading212_persistence.projection_service_base.CollectionSnapshotStore") as factory,
        pytest.raises(AuthorizationError),
    ):
        store._page(
            cast(Session, MagicMock(spec=Session)),
            AUTH,
            CollectionSnapshotResource.ASSUMPTION_VERSIONS,
            app.ProjectionPageQuery(cursor="untrusted"),
            select(AssumptionVersionModel.id),
            AGGREGATE,
        )
    factory.assert_not_called()
