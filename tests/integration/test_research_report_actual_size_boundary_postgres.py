"""Actual profile-four reports qualify the fixed document and separate proof bounds.

The old event-only geometry exhausted its real 2-MiB proof/manifest allowance
before the document limit. Its source and failed executions remain in private
evidence. Projections supply genuine retained point/asset rows with a small
immutable proof through normal definition, admission and worker services.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from trading212_application import projection as projection_app
from trading212_application import report_jobs
from trading212_application import reports as report_app
from trading212_application.projection_capture import ProjectionDatedSchedule
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
)
from trading212_domain.projection_result import ProjectionPoint
from trading212_domain.report_manifest import decode_report_chunk
from trading212_domain.report_manifest_v4 import decode_report_manifest_v4
from trading212_domain.report_projection_schema import PROJECTION_POINT_MONEY
from trading212_domain.report_schema import table_schema
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumRunModel,
)
from trading212_persistence.projection_models import ProjectionInputModel, ProjectionResultModel
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_base import report_owner_lock, selection_scopes
from trading212_persistence.report_capture import PostgresReportCapture
from trading212_persistence.report_input_store import ReportInputSink
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ReportArtifactModel,
    ReportDefinitionModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputLicenseModel,
    ReportInputPinModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from trading212_worker.projection_tasks import ProjectionExecutionState, execute_projection_message
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.phase3_operational_fixture import evidence
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.projection_report_runtime import (
    SavedProjection,
    no_resampling,
    report_selection,
    report_service,
    saved_projection,
)
from tests.integration.test_projection_jobs_postgres import admitted, store
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.unit.domain.test_report_encoding_stream_parity import (
    _original_primitive,
    _original_stream,
)

pytestmark = pytest.mark.integration

_STATE_MODELS = (
    ReportDefinitionModel,
    ReportInputSnapshotModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputPremiumDependencyModel,
    ReportInputPinModel,
    ReportInputLicenseModel,
    ReportJobModel,
    ReportDispatchOutboxModel,
    ReportArtifactModel,
    ApplicationCommandIdentityModel,
)
_INITIAL = Decimal("100")
_ASSETS = 10
_WEIGHT = Decimal("0.1")


def _state(case: ProjectionJobCase) -> tuple[dict[str, int], tuple[int, int, int]]:
    with case.sessions() as session:
        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
            for model in _STATE_MODELS
        }
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        return counts, (capacity.active_jobs, capacity.reserved_bytes, capacity.retained_bytes)


async def _definition(case: ProjectionJobCase) -> UUID:
    await case.service.cancel_run(
        case.principal,
        projection_app.CancelProjectionRun(
            run_id=case.run.id,
            idempotency_key=str(uuid4()),
            correlation_id="actual-document-cancel-unused-fixture",
        ),
    )
    assumptions = ProjectionAssumptions(
        assets=tuple(
            ProjectionAsset(
                key=f"document-asset-{index:02d}",
                annual_mean_log_return=Decimal(0),
                annual_volatility=Decimal(0),
                weight=_WEIGHT,
            )
            for index in range(_ASSETS)
        ),
        correlation=tuple(
            tuple(Decimal(int(left == right)) for right in range(_ASSETS))
            for left in range(_ASSETS)
        ),
        reporting_currency=CurrencyCode("EUR"),
        annual_inflation=Decimal(0),
        annual_fee=Decimal(0),
        annual_tax_drag=Decimal(0),
    )
    definition = await case.service.create_assumption_set(
        case.principal,
        projection_app.CreateAssumptionSet(
            account_id=case.command.selection.account_id,
            metadata=ProjectionVersionMetadata(
                name="Synthetic actual document boundary",
                description=(
                    "Exact stationary EUR 100 model with ten equal assets; no provider inputs."
                ),
            ),
            content=assumptions,
            idempotency_key=str(uuid4()),
            correlation_id="actual-document-boundary-definition",
        ),
    )
    return definition.current_version_id


async def _saved(
    case: ProjectionJobCase, definition: UUID, *, paths: int, points: int, months: int
) -> tuple[ProjectionJobCase, SavedProjection]:
    assert 2 <= points <= 121 and points - 1 <= months <= 500
    assert _ASSETS * paths * months <= 1_000_000
    case.now = datetime.now(UTC)
    original = case.command.selection
    currency = CurrencyCode("EUR")
    command = replace(
        case.command,
        selection=replace(
            original,
            assumption_version_id=definition,
            initial=replace(original.initial, modeled_value=Money(_INITIAL, currency)),
            allocation=tuple(
                ProjectionAllocation(key=f"document-asset-{index:02d}", weight=_WEIGHT)
                for index in range(_ASSETS)
            ),
            schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(0), currency)),
            months=months,
            paths=paths,
            retained_months=(*range(points - 1), months),
        ),
        idempotency_key=str(uuid4()),
        correlation_id="actual-document-boundary-projection",
    )
    queued = await case.service.create_run(case.principal, command)
    actual = replace(case, command=command, run=queued)
    # Financial inputs retain their explicit original instant. Operational
    # heartbeats and PostgreSQL's real lease guards use the production UTC clock.
    worker = store(actual, clock=lambda: datetime.now(UTC))
    dispatch = await admitted(actual, worker)
    assert await worker.acknowledge_projection_dispatch(dispatch)
    worker_started = perf_counter()
    outcome: ProjectionExecutionState | None = None
    try:
        outcome = await execute_projection_message(
            worker, dispatch.message, consumer_id="actual-document-projection-source"
        )
    finally:
        # Select only safe operational columns, never a lease token or payload.
        with actual.sessions() as session:
            job = session.execute(
                select(
                    PremiumJobModel.state,
                    PremiumJobModel.failure_code,
                    PremiumJobModel.consumer_attempts,
                    PremiumJobModel.heartbeat_at,
                    PremiumJobModel.lease_expires_at,
                    PremiumJobModel.deadline_at,
                ).where(PremiumJobModel.id == actual.run.job_id)
            ).one()
        evidence(
            "actual-document-projection-source-worker",
            {
                "paths": paths,
                "points": points,
                "months": months,
                "assets": _ASSETS,
                "elapsed_seconds": perf_counter() - worker_started,
                "execution_outcome": None if outcome is None else outcome.value,
                "job_state": job[0],
                "failure_code": job[1],
                "consumer_attempts": job[2],
                "heartbeat_at": None if job[3] is None else job[3].isoformat(),
                "lease_expires_at": None if job[4] is None else job[4].isoformat(),
                "deadline_at": None if job[5] is None else job[5].isoformat(),
                "operational_clock": "production_realtime_utc",
                "financial_input_clock_unchanged": True,
                "private_payloads_or_tokens_retained": False,
            },
        )
    assert outcome is ProjectionExecutionState.SUCCEEDED
    saved = saved_projection(actual)
    assert len(saved.value.variants) == 1
    for variant in saved.value.variants:
        assert len(variant.paths) == paths and len(variant.distributions) == points
        for path in variant.paths:
            assert len(path.points) == points
            for point in path.points:
                assert point.nominal == point.real == _INITIAL
                assert all(asset.value == Decimal("10") for asset in point.assets)
                assert sum((asset.value for asset in point.assets), Decimal(0)) == _INITIAL
                assert all(
                    getattr(point, name) == Decimal(0)
                    for name in PROJECTION_POINT_MONEY
                    if name not in {"nominal", "real"}
                )
    return actual, saved


def _source_unchanged(case: ProjectionJobCase, saved: SavedProjection) -> None:
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        source_input = session.get_one(ProjectionInputModel, saved.input_id)
        source_result = session.get_one(ProjectionResultModel, saved.result_id)
        assert root.input_digest == saved.capture_digest
        assert source_input.canonical_capture == saved.capture_bytes
        assert source_input.canonical_input == saved.input_bytes
        assert source_result.canonical_result == saved.result_bytes
        assert sha256(source_result.canonical_result).hexdigest() == saved.result_digest


def _measure_retained(
    case: ProjectionJobCase, saved: SavedProjection, input_id: UUID, session: Session
) -> dict[str, object]:
    """Stream actual PostgreSQL chunks; retain only byte counts and exact proofs."""
    tables: dict[str, dict[str, int]] = {}
    point_groups: dict[int, int] = {}
    calendar_rows: dict[int, int] = {}
    chunks = chunk_bytes = maximum_chunk = 0
    captured = session.get_one(ReportInputSnapshotModel, input_id)
    assert captured.owner_id == UUID(case.principal.owner_id)
    assert captured.account_id == case.command.selection.account_id
    assert captured.canonical_manifest and captured.sealed_at is not None
    manifest = decode_report_manifest_v4(captured.canonical_manifest)
    assert manifest.document.premium_binding.run_id == case.run.id
    digests = {descriptor.table: sha256() for descriptor in manifest.document.tables}
    for table, digest in digests.items():
        schema = _original_stream(
            _original_primitive(table_schema(table)), r.MAX_REPORT_MANIFEST_BYTES
        )
        digest.update(len(schema).to_bytes(8, "big"))
        digest.update(schema)
    month_indices = {month: index for index, month in enumerate(saved.value.inputs.retained_months)}
    source_points: dict[tuple[str, int, int], ProjectionPoint] = {
        (variant.variant, path.index, index): point
        for variant in saved.value.variants
        for path in variant.paths
        for index, point in enumerate(path.points)
    }
    seen_points: set[tuple[str, int, int]] = set()
    seen_assets: set[tuple[str, int, int, int]] = set()
    for stored in session.scalars(
        select(ReportInputChunkModel)
        .where(ReportInputChunkModel.input_id == input_id)
        .order_by(ReportInputChunkModel.table_key, ReportInputChunkModel.ordinal)
        .execution_options(yield_per=1)
    ):
        assert stored.payload
        assert len(stored.payload) == stored.byte_length <= r.MAX_REPORT_CHUNK_BYTES
        assert sha256(stored.payload).hexdigest() == stored.content_digest
        maximum_chunk = max(maximum_chunk, len(stored.payload))
        chunk = decode_report_chunk(stored.payload)
        stats = tables.setdefault(chunk.table.value, {"rows": 0, "row_bytes": 0, "chunk_bytes": 0})
        stats["chunk_bytes"] += len(stored.payload)
        columns = tuple(column.key for column in table_schema(chunk.table).columns)
        for row in chunk.rows:
            encoded = _original_stream(_original_primitive(row), r.MAX_REPORT_CHUNK_BYTES)
            digests[chunk.table].update(len(encoded).to_bytes(8, "big"))
            digests[chunk.table].update(encoded)
            stats["rows"] += 1
            stats["row_bytes"] += len(encoded)
            cells = dict(zip(columns, row.cells, strict=True))
            if chunk.table is r.ReportTableKey.PROJECTION_POINTS_V1:
                variant, path_index, point_index = (
                    cells["variant"].value,
                    cells["path_index"].value,
                    cells["point_index"].value,
                )
                assert isinstance(variant, str)
                assert isinstance(path_index, int) and isinstance(point_index, int)
                point_key = (variant, path_index, point_index)
                assert point_key not in seen_points
                seen_points.add(point_key)
                original = source_points[point_key]
                for name in PROJECTION_POINT_MONEY:
                    cell = cells[name]
                    assert cell.value == getattr(original, name)
                    assert cell.currency == CurrencyCode("EUR")
                    assert cell.state is r.CellState.AVAILABLE
                assert cells["month"].value == original.month
                month = original.month
                point_groups[month] = point_groups.get(month, 0) + len(encoded)
            elif chunk.table is r.ReportTableKey.PROJECTION_POINT_ASSETS_V1:
                variant, path_index, point_index, asset_index = (
                    cells["variant"].value,
                    cells["path_index"].value,
                    cells["point_index"].value,
                    cells["asset_index"].value,
                )
                assert isinstance(variant, str)
                assert isinstance(path_index, int) and isinstance(point_index, int)
                assert isinstance(asset_index, int)
                asset_key = (variant, path_index, point_index, asset_index)
                assert asset_key not in seen_assets
                seen_assets.add(asset_key)
                original_asset = source_points[(variant, path_index, point_index)].assets[
                    asset_index
                ]
                assert cells["key"].value == original_asset.key
                assert cells["value"].value == original_asset.value
                assert cells["value"].value == Decimal("10")
                assert cells["value"].currency == CurrencyCode("EUR")
                point_index = cells["point_index"].value
                assert isinstance(point_index, int)
                month = saved.value.inputs.retained_months[point_index]
                point_groups[month] = point_groups.get(month, 0) + len(encoded)
            elif chunk.table in {
                r.ReportTableKey.PROJECTION_DISTRIBUTIONS_V1,
                r.ReportTableKey.PROJECTION_QUANTILES_V1,
            }:
                cell_month = cells["month"].value
                assert isinstance(cell_month, int) and cell_month in month_indices
                point_groups[cell_month] = point_groups.get(cell_month, 0) + len(encoded)
            elif chunk.table is r.ReportTableKey.PROJECTION_CALENDAR_V1:
                cell_month = cells["month"].value
                assert isinstance(cell_month, int)
                calendar_rows[cell_month] = len(encoded)
        chunks += 1
        chunk_bytes += len(stored.payload)
    assert captured.chunk_count == chunks
    assert captured.canonical_byte_length == chunk_bytes + len(captured.canonical_manifest)
    assert captured.canonical_byte_length <= r.MAX_REPORT_DOCUMENT_BYTES
    for descriptor in manifest.document.tables:
        assert descriptor.row_count == tables.get(descriptor.table.value, {}).get("rows", 0)
        assert descriptor.content_digest == digests[descriptor.table].hexdigest()
    assert seen_points == set(source_points)
    assert len(seen_assets) == len(source_points) * _ASSETS
    assert len(point_groups) == len(saved.value.inputs.retained_months)
    assert len(calendar_rows) == saved.value.inputs.months + 1
    return {
        "document_bytes": captured.canonical_byte_length,
        "manifest_bytes": len(captured.canonical_manifest),
        "chunks": chunks,
        "maximum_chunk_bytes": maximum_chunk,
        "complete_row_bytes": sum(stats["row_bytes"] for stats in tables.values()),
        "tables": tables,
        "point_group_row_bytes": point_groups,
        "calendar_row_bytes": calendar_rows,
        "source_result_bytes": len(saved.result_bytes),
        "source_input_bytes": len(saved.capture_bytes) + len(saved.input_bytes),
        "source_result_sha256": saved.result_digest,
    }


def _capture_measurement(case: ProjectionJobCase, saved: SavedProjection) -> dict[str, object]:
    before = _state(case)
    selected = replace(report_selection(case), formats=(r.ReportFormat.JSON,))
    try:
        with case.sessions() as session:
            try:
                auth = authorize_report_request(
                    session,
                    case.principal,
                    account_id=selected.account_id,
                    required_scopes=selection_scopes(selected),
                    now=case.now,
                )
                report_owner_lock(session, auth.owner_id)
                sink = ReportInputSink(
                    session,
                    auth,
                    selection=selected,
                    expires_at=case.now + timedelta(days=1),
                    clock=lambda: case.now,
                )
                capture = PostgresReportCapture(
                    session,
                    auth,
                    source_use=r.ReportSourceUse.REPORT,
                    sessions=case.sessions,
                    clock=lambda: case.now,
                    cursor_signing_key=XRAY_CURSOR_KEY,
                ).capture_report(selected, sink=sink)
                auth.check(session, now=case.now)
                sink.finish(capture)
                measurement = _measure_retained(case, saved, sink.row.id, session)
            finally:
                session.rollback()
    finally:
        assert _state(case) == before
        _source_unchanged(case, saved)
    return measurement


async def test_actual_projection_report_fixture_calibration(
    projection_job_case: ProjectionJobCase,
) -> None:
    """One genuine legal capture supplies byte costs, not boundary acceptance."""
    case, started = projection_job_case, perf_counter()
    measurement: dict[str, object] = {}
    phase, failure = "normal_projection_definition", None
    try:
        assert r.MAX_REPORT_DOCUMENT_BYTES == 33_554_432
        assert r.MAX_REPORT_MANIFEST_BYTES == 2_097_152
        definition = await _definition(case)
        phase = "normal_projection_worker"
        actual, saved = await _saved(case, definition, paths=8, points=32, months=120)
        phase = "actual_complete_profile4_capture"
        measurement = _capture_measurement(actual, saved)
        phase = "calibration_complete_boundary_pending"
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        evidence(
            "actual-projection-document-calibration",
            {
                "phase": phase,
                "failure_type": failure,
                "elapsed_seconds": perf_counter() - started,
                "paths": 8,
                "assets": _ASSETS,
                "retained_instants": 32,
                "months": 120,
                "work_units": 8 * _ASSETS * 120,
                "measurement": measurement,
                "near_32_mib_qualification_claimed": False,
                "private_payloads_retained": False,
            },
        )


async def test_actual_near_32_mib_report_admission_and_oversized_rollback(
    projection_job_case: ProjectionJobCase,
) -> None:
    """Qualify one measured source geometry and one genuine extra retained instant.

    Calibration ea0d275e14994f1e85b6283b73fe03ea measured exact row costs and
    chunk packing. Those costs predict 33,508,878 bytes for 42 paths and 112
    retained instants: 45,554 bytes below the unchanged document cap. Actual
    admissions and byte checks decide this test; the prediction is not evidence.
    """
    case, started = projection_job_case, perf_counter()
    measurement: dict[str, object] = {}
    phase, failure = "normal_source_publication", None
    rejected_field: str | None = None
    try:
        assert r.MAX_REPORT_DOCUMENT_BYTES == 33_554_432
        assert r.MAX_REPORT_CHUNK_BYTES == 1_048_576
        assert r.MAX_REPORT_MANIFEST_BYTES == 2_097_152
        assert r.MAX_REPORT_ARTIFACT_BYTES == 10_485_760
        definition = await _definition(case)
        legal, legal_source = await _saved(case, definition, paths=42, points=112, months=120)
        oversized, oversized_source = await _saved(
            case, definition, paths=42, points=113, months=120
        )
        # An extra actual retained month never changes the common financial
        # points. Both source runs came from ordinary admission and workers.
        for first, second in zip(
            legal_source.value.variants[0].paths,
            oversized_source.value.variants[0].paths,
            strict=True,
        ):
            later = {point.month: point for point in second.points}
            assert all(point == later[point.month] for point in first.points)
        service = report_service(legal)
        selected = replace(report_selection(legal), formats=(r.ReportFormat.JSON,))
        command = report_app.GenerateReportCommand(
            selection=selected,
            ttl_days=1,
            idempotency_key="actual-projection-document-boundary-legal-v1",
        )
        phase = "genuine_near_boundary_service_admission"
        with no_resampling():
            pending = await service.generate_report(legal.principal, command)
        assert pending.state is r.ReportJobState.QUEUED
        with legal.sessions() as session:
            auth = authorize_report_request(
                session,
                legal.principal,
                account_id=selected.account_id,
                required_scopes=selection_scopes(selected),
                now=legal.now,
            )
            auth.check(session, now=legal.now)
            job = session.get_one(ReportJobModel, pending.job_id)
            measurement = _measure_retained(legal, legal_source, job.input_id, session)
            task = report_jobs.ReportTaskMessage(
                job_id=job.id,
                owner_id=job.owner_id,
                account_id=job.account_id,
                capture_id=job.input_id,
                input_digest=job.input_digest,
            )
        actual_bytes = measurement["document_bytes"]
        assert isinstance(actual_bytes, int)
        distance = r.MAX_REPORT_DOCUMENT_BYTES - actual_bytes
        measurement["distance_from_32_mib"] = distance
        assert 0 <= distance < 128 * 1024
        complete_rows = measurement["complete_row_bytes"]
        assert isinstance(complete_rows, int) and complete_rows > r.MAX_REPORT_ARTIFACT_BYTES
        before = _state(legal)
        repeated = await service.generate_report(legal.principal, command)
        assert repeated.job_id == pending.job_id and _state(legal) == before
        phase = "actual_oversized_service_admission_rollback"
        oversized_service = report_service(oversized)
        with no_resampling(), pytest.raises(report_app.ReportServiceError) as rejected:
            await oversized_service.generate_report(
                oversized.principal,
                report_app.GenerateReportCommand(
                    selection=replace(report_selection(oversized), formats=(r.ReportFormat.JSON,)),
                    ttl_days=1,
                    idempotency_key="actual-projection-document-boundary-oversized-v1",
                ),
            )
        assert rejected.value.code is report_app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
        # The service deliberately sanitizes its public error. Python retains
        # the original cause privately even for `raise ... from None`, allowing
        # the exact unchanged document guard to be distinguished from all other
        # row, source, proof, manifest, capacity and renderer limits.
        cause = rejected.value.__context__
        assert isinstance(cause, DomainError)
        assert cause.code is ErrorCode.INPUT_BOUND_EXCEEDED
        rejected_field = cause.field
        assert rejected_field == "document_bytes"
        assert _state(oversized) == before
        _source_unchanged(legal, legal_source)
        _source_unchanged(oversized, oversized_source)
        phase = "foreign_manifest_denial_before_private_payload"

        def no_private_payload(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: bool,
        ) -> None:
            sql = statement.lower().lstrip()
            if sql.startswith(("select", "with")):
                assert not any(
                    column in sql
                    for column in (
                        "canonical_manifest",
                        "canonical_context",
                        "report_input_chunks.payload",
                    )
                ), "A foreign manifest read selected private report bytes."

        event.listen(legal.engine, "before_cursor_execute", no_private_payload)
        try:
            with pytest.raises(report_app.ReportServiceError) as denied:
                await service.get_report_manifest(
                    replace(legal.principal, owner_id="ffffffff-ffff-4fff-8fff-ffffffffffff"),
                    selected.account_id,
                    pending.job_id,
                )
            assert denied.value.code in {
                report_app.ReportServiceErrorCode.ACCESS_DENIED,
                report_app.ReportServiceErrorCode.NOT_FOUND,
            }
        finally:
            event.remove(legal.engine, "before_cursor_execute", no_private_payload)
        assert _state(legal) == before
        phase = "bounded_json_worker_failure_without_artifact_publication"
        result = await execute_report_message(
            PostgresReportJobStore(legal.sessions),
            task,
            consumer_id="actual-projection-document-boundary",
        )
        terminal = await service.get_report_status(
            legal.principal, selected.account_id, pending.job_id
        )
        assert result is ReportExecutionState.FAILED
        assert terminal.state is r.ReportJobState.FAILED
        assert terminal.failure_code is r.ReportFailureCode.LIMIT_EXCEEDED
        assert terminal.artifacts == ()
        with legal.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.job_id == pending.job_id)
                )
                == 0
            )
        _source_unchanged(legal, legal_source)
        _source_unchanged(oversized, oversized_source)
        phase = "complete_local_document_boundary_observation"
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        evidence(
            "actual-projection-document-boundary",
            {
                "phase": phase,
                "failure_type": failure,
                "elapsed_seconds": perf_counter() - started,
                "legal_geometry": {"paths": 42, "assets": 10, "points": 112, "months": 120},
                "oversized_geometry": {"paths": 42, "assets": 10, "points": 113, "months": 120},
                "per_source_work_units": 50_400,
                "calibration_based_prediction_bytes": 33_508_878,
                "measurement": measurement,
                "oversized_denial_field": rejected_field,
                "document_limit_bytes": r.MAX_REPORT_DOCUMENT_BYTES,
                "manifest_limit_bytes": r.MAX_REPORT_MANIFEST_BYTES,
                "artifact_limit_bytes": r.MAX_REPORT_ARTIFACT_BYTES,
                "private_payloads_retained": False,
                "artifact_guard_first_cause_claimed": False,
                "formal_acceptance_claimed": False,
            },
        )
