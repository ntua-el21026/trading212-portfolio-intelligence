"""Native publication proof, atomic rejection and deterministic authorized replay."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection, ExceptionContext
from sqlalchemy.orm import Mapper, undefer
from trading212_application import aggregation as app
from trading212_application.aggregation_views import AggregateComponentPage
from trading212_domain.aggregation import AggregateActivityWindow, AggregateView
from trading212_domain.serialization import canonical_json
from trading212_persistence import aggregation_models as m
from trading212_persistence.aggregation_service import PostgresAggregateService
from trading212_persistence.models import (
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from trading212_persistence.premium_models import PremiumCapacityModel
from trading212_persistence.report_models import ApplicationCommandIdentityModel
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_aggregation_postgres import command, prepared
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def test_native_publication_preserves_original_provenance_and_replays_after_restart(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    case.now[0] = datetime.now(UTC)
    store, selected = await prepared(case)
    request = command(selected)
    run = await store.create_run(case.principal, request)
    with case.sessions() as session:
        pins = {
            (row.account_id, row.snapshot_id)
            for row in session.scalars(
                select(m.AggregateSnapshotModel).where(
                    m.AggregateSnapshotModel.run_id == run.run_id
                )
            )
        }
        components = tuple(
            session.scalars(
                select(m.AggregateComponentModel)
                .options(undefer("*"))
                .where(m.AggregateComponentModel.run_id == run.run_id)
            )
        )
        assert len(pins) == 2 and len(components) == 4
        memberships = set(
            session.scalars(
                select(m.AggregateSourceModel.source_record_id).where(
                    m.AggregateSourceModel.run_id == run.run_id,
                    m.AggregateSourceModel.source_kind == "broker_record",
                )
            )
        )
        for component in components:
            assert (component.account_id, component.snapshot_id) in pins
            native = json.loads(component.payload)["native"]
            original = (
                session.get(SnapshotPositionModel, component.position_id)
                if component.kind == "position"
                else session.get(SnapshotCashModel, component.cash_id)
            )
            assert original is not None
            source_ids = {UUID(value) for value in native["source_record_ids"]}
            assert source_ids == {UUID(value) for value in original.provenance["source_record_ids"]}
            assert source_ids <= memberships
            assert set(
                session.scalars(
                    select(SourceRecordModel.broker_account_id).where(
                        SourceRecordModel.id.in_(source_ids)
                    )
                )
            ) == {component.account_id}
    query = app.AggregateRunQuery(view=AggregateView.COMPONENTS)
    first = await store.get_run(case.principal, run.run_id, query)
    case.engine.dispose()
    restarted = PostgresAggregateService(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    assert await restarted.create_run(case.principal, request) == run
    assert await restarted.get_run(case.principal, run.run_id, query) == first
    assert isinstance(first.page, AggregateComponentPage)
    assert first.page.context.total.value == Decimal("496862.54")
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(m.AggregateRunModel)) == 1


def _publication_state(case: XrayReadCase, selection_id: UUID) -> tuple[object, ...]:
    with case.sessions() as session:
        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in m.AGGREGATION_MODELS
        }
        capacity = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert capacity is not None
        selected = session.get(m.AggregateSelectionModel, selection_id)
        assert selected is not None
        commands = session.scalar(
            select(func.count())
            .select_from(ApplicationCommandIdentityModel)
            .where(ApplicationCommandIdentityModel.command == "aggregate.run.create.v1")
        )
        return (
            counts,
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.active_jobs,
            capacity.definition_versions,
            selected.revision,
            commands,
        )


@pytest.mark.parametrize("forgery", ("provenance", "account", "snapshot", "native_value"))
async def test_forged_native_proof_rolls_back_every_copy_and_allows_exact_retry(
    xray_read_case: XrayReadCase,
    forgery: str,
) -> None:
    case = xray_read_case
    case.now[0] = datetime.now(UTC)
    store, selected = await prepared(case)
    request = command(selected)
    before = _publication_state(case, selected.selection_id)
    errors: list[tuple[str | None, str | None]] = []

    def corrupt(
        _mapper: Mapper[m.AggregateComponentModel],
        _connection: Connection,
        target: m.AggregateComponentModel,
    ) -> None:
        # Inject a false persisted proof after the real capture/calculation validators;
        # retain a valid payload digest so the native SQL guard must reject it.
        other = next(x for x in selected.content.members if x.account_id != target.account_id)
        body = json.loads(target.payload)
        native = body["native"]
        if forgery == "provenance":
            native["source_record_ids"] = []
        elif forgery == "account":
            native["account_id"] = str(other.account_id)
            target.account_id = other.account_id
        elif forgery == "snapshot":
            native["portfolio_snapshot_id"] = str(other.portfolio_snapshot_id)
            target.snapshot_id = other.portfolio_snapshot_id
        else:
            native["native_value"] = "1"
            target.native_value = Decimal("1")
        target.payload = canonical_json(body).encode()
        target.content_digest = sha256(
            b"t212pi.aggregation.record.v1\0" + target.payload
        ).hexdigest()

    def record_error(context: ExceptionContext) -> None:
        error = context.original_exception
        errors.append(
            (
                getattr(error, "sqlstate", None),
                getattr(getattr(error, "diag", None), "message_primary", None),
            )
        )

    event.listen(m.AggregateComponentModel, "before_insert", corrupt)
    event.listen(case.engine, "handle_error", record_error)
    try:
        with pytest.raises(app.AggregateServiceError) as denied:
            await store.create_run(case.principal, request)
        assert denied.value.code is app.AggregateErrorCode.CONFLICT
    finally:
        event.remove(m.AggregateComponentModel, "before_insert", corrupt)
        event.remove(case.engine, "handle_error", record_error)
    assert errors == [("23514", "aggregate native component proof differs")]
    assert _publication_state(case, selected.selection_id) == before
    run = await store.create_run(case.principal, request)
    assert await store.create_run(case.principal, request) == run
    foreign_owner = replace(case.principal, owner_id=str(UUID(int=1)))
    with pytest.raises(app.AggregateServiceError) as foreign:
        await store.get_run(foreign_owner, run.run_id, app.AggregateRunQuery())
    assert foreign.value.code is app.AggregateErrorCode.NOT_FOUND


async def test_tagged_original_transfer_proof_rejects_substituted_time_principal_fx_and_fee(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    store, selected = await prepared(case, transfer_mode="cross")
    before = _publication_state(case, selected.selection_id)
    errors: list[tuple[str | None, str | None]] = []

    def record_error(context: ExceptionContext) -> None:
        error = context.original_exception
        errors.append(
            (
                getattr(error, "sqlstate", None),
                getattr(getattr(error, "diag", None), "message_primary", None),
            )
        )

    for field in ("occurred_at", "principal", "fx_rate", "fee_amount"):
        errors.clear()
        request = replace(
            command(selected),
            activity_window=AggregateActivityWindow(
                start_at=case.now[0] - timedelta(days=1), end_at=case.now[0]
            ),
        )

        def corrupt(
            _mapper: Mapper[m.AggregateActivityEvidenceModel],
            _connection: Connection,
            target: m.AggregateActivityEvidenceModel,
            *,
            changed_field: str = field,
        ) -> None:
            body = json.loads(target.payload)
            if body["transfer"] is None:
                return
            if changed_field == "occurred_at":
                body[changed_field] = "1970-01-01T00:00:00Z"
            else:
                body["transfer"][changed_field] = "999"
            target.payload = canonical_json(body).encode()
            target.content_digest = sha256(
                b"t212pi.aggregation.record.v1\0" + target.payload
            ).hexdigest()

        event.listen(m.AggregateActivityEvidenceModel, "before_insert", corrupt)
        event.listen(case.engine, "handle_error", record_error)
        try:
            with pytest.raises(app.AggregateServiceError) as denied:
                await store.create_run(case.principal, request)
            assert denied.value.code is app.AggregateErrorCode.CONFLICT
        finally:
            event.remove(m.AggregateActivityEvidenceModel, "before_insert", corrupt)
            event.remove(case.engine, "handle_error", record_error)
        assert errors == [("23514", "aggregate native transfer witness was substituted")]
        assert _publication_state(case, selected.selection_id) == before
