"""Real owner preferences, immutable cursors, bounded privacy drain and SQL backstops."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_application import owner_layouts as app
from trading212_domain import owner_layouts as d
from trading212_domain.owner_layout_codec import owner_layout_bytes
from trading212_domain.values import CurrencyCode
from trading212_persistence.models import BrokerConnectionModel, PrincipalModel
from trading212_persistence.owner_layout_models import (
    OwnerLayoutCommandModel,
    OwnerLayoutErasureModel,
    OwnerLayoutModel,
    SavedLayoutWidgetModel,
    SavedViewVersionModel,
)
from trading212_persistence.owner_layout_retention import purge_owner_layouts
from trading212_persistence.owner_layout_service import PostgresOwnerLayoutService
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_security.principals import Scope
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def service(case: XrayReadCase) -> PostgresOwnerLayoutService:
    grant_scenario_identity(case.sessions, case.principal, case.now[0])
    return PostgresOwnerLayoutService(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )


def template(name: str = "Daily review", account: UUID | None = None) -> d.OwnerLayoutContent:
    return d.OwnerLayoutContent(
        name=name,
        description="Owner-authored preferences",
        account_id=account,
        widgets=(
            d.OwnerLayoutWidget(id=uuid4(), kind=d.LayoutWidgetKind.PORTFOLIO_SUMMARY),
            d.OwnerLayoutWidget(
                id=uuid4(),
                kind=d.LayoutWidgetKind.SAVED_VIEW,
                selection=d.WorkspaceLayoutSelection(route=d.LayoutRoute.QUALITY),
            ),
        ),
    )


def create(content: d.OwnerLayoutContent) -> app.CreateOwnerLayout:
    return app.CreateOwnerLayout(
        content=content, idempotency_key=str(uuid4()), correlation_id="layout-test"
    )


def edit(value: app.OwnerLayoutView, content: d.OwnerLayoutContent) -> app.UpdateOwnerLayout:
    return app.UpdateOwnerLayout(
        layout_id=value.id,
        expected_revision=value.revision,
        content=content,
        idempotency_key=str(uuid4()),
        correlation_id="layout-test",
    )


def archive(value: app.OwnerLayoutView) -> app.ArchiveOwnerLayout:
    return app.ArchiveOwnerLayout(
        layout_id=value.id,
        expected_revision=value.revision,
        idempotency_key=str(uuid4()),
        correlation_id="layout-test",
    )


@contextmanager
def statements(case: XrayReadCase) -> Iterator[list[str]]:
    recorded: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        recorded.append(statement)

    event.listen(case.engine, "before_cursor_execute", capture)
    try:
        yield recorded
    finally:
        event.remove(case.engine, "before_cursor_execute", capture)


async def test_current_authority_version_receipts_and_equal_time_page_capsule(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store = service(case)
    principal = replace(case.principal, scopes=app.LAYOUT_WRITE_SCOPES)
    originals = [
        await store.create_owner_layout(principal, create(template(f"Original {number}")))
        for number in range(4)
    ]
    with statements(case) as executed:
        first = await store.list_owner_layouts(principal, app.OwnerLayoutPageQuery(limit=1))
    assert len(executed) <= 12
    assert not any("canonical_content" in statement.lower() for statement in executed)
    assert first.total == 4 and first.next_cursor is not None
    # All writes deliberately share one timestamp; versions/archive cannot be inferred from time.
    changed = next(value for value in originals if value.id != first.items[0].id)
    command = edit(changed, replace(changed.content, name="Changed at identical time"))
    updated = await store.update_owner_layout(principal, command)
    assert updated.revision == 2 and updated.version.number == 2
    assert await store.update_owner_layout(principal, command) == updated
    assert (
        await store.get_owner_layout(principal, changed.id, version_id=changed.version.id)
    ).content == changed.content
    assert owner_layout_bytes(changed.content) != owner_layout_bytes(updated.content)
    receipt = await store.archive_owner_layout(principal, archive(updated))
    assert receipt.revision == 3
    collected = list(first.items)
    cursor: str | None = first.next_cursor
    while cursor is not None:
        with statements(case) as page_statements:
            page = await store.list_owner_layouts(
                principal, app.OwnerLayoutPageQuery(limit=1, cursor=cursor)
            )
        assert len(page_statements) <= 12
        collected.extend(page.items)
        cursor = page.next_cursor
    assert {item.id: (item.name, item.state, item.revision) for item in collected} == {
        value.id: (value.content.name, "active", 1) for value in originals
    }
    assert (await store.list_owner_layouts(principal, app.OwnerLayoutPageQuery())).total == 3
    current = await store.list_owner_layouts(
        principal, app.OwnerLayoutPageQuery(include_archived=True)
    )
    assert next(item for item in current.items if item.id == changed.id).state == "archived"
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(OwnerLayoutCommandModel)) == 6
        assert session.scalar(select(func.count()).select_from(SavedViewVersionModel)) == 5


async def test_real_saved_xray_pins_and_revocation_precede_private_decode(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store = service(case)
    saved = await company(case)
    pin = d.RunLayoutSelection(
        family=d.LayoutRunFamily.XRAY,
        run_id=UUID(saved.context.run_id),
        snapshot_id=UUID(case.seed["snapshot_id"]),
        source_cutoff_at=case.request().source_cutoff_at,
        reporting_currency=CurrencyCode("EUR"),
    )
    content = replace(
        template(account=UUID(XRAY_ACCOUNT_ID)),
        widgets=(
            d.OwnerLayoutWidget(id=uuid4(), kind=d.LayoutWidgetKind.SAVED_VIEW, selection=pin),
        ),
    )
    value = await store.create_owner_layout(case.principal, create(content))
    assert (await store.get_owner_layout(case.principal, value.id)).content == content
    assert pin.source_cutoff_at is not None
    for invalid in (
        replace(pin, snapshot_id=uuid4()),
        replace(pin, source_cutoff_at=pin.source_cutoff_at + timedelta(microseconds=1)),
        replace(pin, reporting_currency=CurrencyCode("USD")),
    ):
        bad = replace(content, widgets=(replace(content.widgets[0], selection=invalid),))
        with pytest.raises(app.OwnerLayoutServiceError) as failure:
            await store.create_owner_layout(case.principal, create(bad))
        assert failure.value.code is app.OwnerLayoutErrorCode.ACCESS_DENIED
    with case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == case.principal.issuer,
                PrincipalModel.subject == case.principal.subject,
            )
        )
        assert identity is not None
        session.execute(
            update(PrincipalScopeGrantModel)
            .where(
                PrincipalScopeGrantModel.principal_id == identity.id,
                PrincipalScopeGrantModel.scope == Scope.PORTFOLIO_READ.value,
            )
            .values(revoked_at=case.now[0])
        )
    with (
        statements(case) as denied_sql,
        patch(
            "trading212_persistence.owner_layout_service.decode_layout_version",
            side_effect=AssertionError("private decode before current grant"),
        ),
        pytest.raises(app.OwnerLayoutServiceError) as failure,
    ):
        await store.get_owner_layout(case.principal, value.id)
    assert failure.value.code is app.OwnerLayoutErrorCode.ACCESS_DENIED
    assert not any(
        "SELECT saved_view_versions.canonical_content" in statement for statement in denied_sql
    )
    restricted = await store.list_owner_layouts(case.principal, app.OwnerLayoutPageQuery())
    assert (
        restricted.items[0].availability == "restricted"
        and restricted.items[0].reason == "account_unavailable"
    )
    assert not hasattr(restricted.items[0], "account_id") and not hasattr(
        restricted.items[0], "widgets"
    )
    # Owner-only archive remains usable after a referenced account becomes inaccessible.
    assert (await store.archive_owner_layout(case.principal, archive(value))).state == "archived"
    foreign = replace(case.principal, owner_id=str(uuid4()))
    with pytest.raises(app.OwnerLayoutServiceError) as failure:
        await store.get_owner_layout(foreign, value.id)
    assert failure.value.code is app.OwnerLayoutErrorCode.ACCESS_DENIED


async def test_retained_caps_and_sql_immutability_are_not_archive_cleanup(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store = service(case)
    value = await store.create_owner_layout(case.principal, create(template()))
    for revision in range(2, 129):
        value = await store.update_owner_layout(
            case.principal, edit(value, replace(value.content, name=f"Version {revision}"))
        )
    assert value.version.number == 128 and len(value.versions) == 128
    with pytest.raises(app.OwnerLayoutServiceError) as failure:
        await store.update_owner_layout(
            case.principal, edit(value, replace(value.content, name="Version 129"))
        )
    assert failure.value.code is app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED
    assert (await store.archive_owner_layout(case.principal, archive(value))).revision == 129
    for index in range(31):
        item = await store.create_owner_layout(
            case.principal, create(template(f"Retained {index}"))
        )
        await store.archive_owner_layout(case.principal, archive(item))
    with pytest.raises(app.OwnerLayoutServiceError) as failure:
        await store.create_owner_layout(case.principal, create(template("Thirty-third")))
    assert failure.value.code is app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED
    for sql in (
        "UPDATE saved_view_versions SET name='hidden rewrite' WHERE id=:id",
        "UPDATE saved_view_versions SET canonical_content=convert_to('{}','UTF8') WHERE id=:id",
        "DELETE FROM saved_view_versions WHERE id=:id",
    ):
        with pytest.raises(IntegrityError), case.sessions() as session, session.begin():
            session.execute(text(sql), {"id": value.version.id})
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(OwnerLayoutModel)) == 32
        assert session.scalar(select(func.count()).select_from(SavedViewVersionModel)) == 159
        # Validate a forged normalized row without disabling any guard or writing it.
        assert (
            session.scalar(
                text(
                    "SELECT owner_layout_widget_valid(jsonb_populate_record(w,"
                    "jsonb_build_object('route','https://bad.invalid')),"
                    "NULL) FROM saved_layout_widgets w WHERE kind='saved_view' LIMIT 1"
                )
            )
            is False
        )


async def test_inactive_owner_erasure_drains_small_transactions_and_leaves_only_marker(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store = service(case)
    owner = UUID(case.principal.owner_id)
    value = await store.create_owner_layout(case.principal, create(template("Private owner title")))
    value = await store.update_owner_layout(
        case.principal, edit(value, replace(value.content, name="Private second title"))
    )
    with pytest.raises(IntegrityError), case.sessions() as session, session.begin():
        purge_owner_layouts(session, owner, at=case.now[0], budget=SourcePurgeBudget())
    with case.sessions() as session, session.begin():
        session.execute(
            update(PrincipalModel).where(PrincipalModel.owner_id == owner).values(status="disabled")
        )
        session.execute(
            update(BrokerConnectionModel)
            .where(BrokerConnectionModel.owner_id == owner)
            .values(status="disabled")
        )
    attempts = 0
    complete = False
    while not complete and attempts < 30:
        budget = SourcePurgeBudget(
            rows_inspected=160, rows_removed=2, bytes_removed=32768, bytes_inspected=65536
        )
        with case.sessions() as session, session.begin():
            complete = purge_owner_layouts(session, owner, at=case.now[0], budget=budget)
        assert 0 <= budget.rows_removed <= 2 and 0 <= budget.rows_inspected <= 160
        attempts += 1
    assert complete and attempts > 1
    with case.sessions() as session, session.begin():
        assert purge_owner_layouts(session, owner, at=case.now[0], budget=SourcePurgeBudget())
        marker = session.get(OwnerLayoutErasureModel, owner)
        assert marker is not None and marker.completed_at == case.now[0]
        for model in (
            OwnerLayoutModel,
            SavedViewVersionModel,
            SavedLayoutWidgetModel,
            OwnerLayoutCommandModel,
        ):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.owner_id == owner)
                )
                == 0
            )
    with pytest.raises(app.OwnerLayoutServiceError):
        await store.create_owner_layout(
            case.principal, create(template("Must remain inaccessible"))
        )


async def test_simultaneous_writers_keep_one_revision_and_one_remaining_slot(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store = service(case)
    first = await store.create_owner_layout(case.principal, create(template("Concurrent base")))
    outcomes = await asyncio.gather(
        store.update_owner_layout(
            case.principal, edit(first, replace(first.content, name="Candidate A"))
        ),
        store.update_owner_layout(
            case.principal, edit(first, replace(first.content, name="Candidate B"))
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, app.OwnerLayoutView) for result in outcomes) == 1
    failures = [result for result in outcomes if isinstance(result, app.OwnerLayoutServiceError)]
    assert len(failures) == 1 and failures[0].code is app.OwnerLayoutErrorCode.REVISION_MISMATCH
    for index in range(30):
        await store.create_owner_layout(case.principal, create(template(f"Capacity {index}")))
    outcomes = await asyncio.gather(
        store.create_owner_layout(case.principal, create(template("Last slot A"))),
        store.create_owner_layout(case.principal, create(template("Last slot B"))),
        return_exceptions=True,
    )
    assert sum(isinstance(result, app.OwnerLayoutView) for result in outcomes) == 1
    failures = [result for result in outcomes if isinstance(result, app.OwnerLayoutServiceError)]
    assert len(failures) == 1 and failures[0].code is app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(OwnerLayoutModel)) == 32
