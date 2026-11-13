"""Persisted X-ray provenance, raw SQL seal guards, and bounded exact-source expiry."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_application import xray as app
from trading212_domain import xray as d
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import decode_xray_input
from trading212_persistence.models import (
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
    SnapshotPositionModel,
)
from trading212_persistence.phase2_retention_models import XrayPhysicalStateModel
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.source_models import SourceExpiryEventModel, SourceRetentionWorkModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads
from trading212_persistence.xray_capture import capture_xray
from trading212_persistence.xray_catalog_models import (
    ClassificationSnapshotModel,
    ConstituentHoldingModel,
    ConstituentSnapshotModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    XrayEvidenceFields,
)
from trading212_persistence.xray_enrichment_retention import expire_enrichment_payloads
from trading212_persistence.xray_lifecycle_models import (
    EnrichmentExpiryEventModel,
    EnrichmentRetentionWorkModel,
)
from trading212_persistence.xray_publication import publish_xray
from trading212_persistence.xray_run_models import (
    XrayCollectionBindingModel,
    XrayExposureModel,
    XrayInputDependencyModel,
    XrayInputSnapshotModel,
    XrayRetentionEventModel,
    XrayRunModel,
)
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID

from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def test_capture_preserves_real_broker_wallet_quote_and_saved_root_identity(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    result = asyncio.run(company(case))
    with case.sessions() as session:
        capture = session.get(XrayInputSnapshotModel, UUID(result.context.input_snapshot_id))
        assert capture is not None and capture.sealed_at is not None
        value = decode_xray_input(capture.canonical_input)
        assert len(value.broker_fx) == 1
        quote = value.broker_fx[0]
        root = next(item for item in value.positions if item.root.key == quote.root_key)
        assert root.original_value.value is not None and root.reporting_value.value is not None
        assert root.original_value.value.amount == Decimal("62.50")
        assert root.original_value.value.currency.value == "USD"
        assert root.reporting_value.value.amount == Decimal("50")
        assert quote.rate == Decimal("0.8") and quote.quote_currency.value == "EUR"
        assert (
            session.scalar(
                select(SnapshotPositionModel.id).where(
                    SnapshotPositionModel.id == root.root.position_id,
                    SnapshotPositionModel.snapshot_id == value.snapshot_id,
                )
            )
            == root.root.position_id
        )
        refs = {item.id: item for item in value.source_dependencies}
        assert refs[quote.source_reference_id].kind is d.XrayDependencyKind.BROKER_FX
        assert refs[quote.source_reference_id].license_version_id is None
        stored = session.scalar(
            select(XrayInputDependencyModel).where(
                XrayInputDependencyModel.input_id == capture.id,
                XrayInputDependencyModel.reference_id == quote.source_reference_id,
            )
        )
        assert stored is not None and stored.broker_source_record_id == quote.source_record_id
        assert stored.fx_snapshot_id is None


def test_saved_requested_currency_without_fx_remains_unavailable_with_broker_proof(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    query = app.EffectiveExposureQuery(
        request=replace(
            case.request(), currency=app.ExplicitCurrency(reporting_currency=CurrencyCode("GBP"))
        )
    )
    response = asyncio.run(
        case.service.get_effective_exposure(case.principal, XRAY_ACCOUNT_ID, query=query)
    )
    assert isinstance(response, app.ExposuresView)
    assert response.summary.total.value is None
    with case.sessions() as session:
        capture = session.get(XrayInputSnapshotModel, UUID(response.context.input_snapshot_id))
        assert capture is not None
        value = decode_xray_input(capture.canonical_input)
        assert value.broker_fx[0].quote_currency.value == "EUR"
        attempt = next(
            item for item in value.licensed_fx if item.consumer_key == value.broker_fx[0].root_key
        )
        assert (
            attempt.input_value.value is not None
            and attempt.input_value.value.amount == Decimal("50")
        )
        assert attempt.output_currency.value == "GBP" and attempt.legs == ()
        assert any(row.reporting_value.reason is d.XrayReason.MISSING_FX for row in value.positions)


@pytest.mark.parametrize(
    "table,column",
    [
        ("xray_input_snapshots", "canonical_input"),
        ("xray_runs", "canonical_summary"),
        ("xray_exposures", "canonical_payload"),
        ("xray_input_dependencies", "canonical_reference"),
    ],
)
def test_raw_sql_cannot_clear_unexpired_sealed_payload(
    xray_read_case: XrayReadCase, table: str, column: str
) -> None:
    case = xray_read_case
    asyncio.run(company(case))
    with pytest.raises(IntegrityError), case.engine.begin() as connection:
        # Both identifiers are closed parametrized test cases, never request SQL.
        connection.execute(text(f"UPDATE {table} SET {column}='\\x'::bytea"))  # noqa: S608 -- closed test cases above


def test_raw_sql_cannot_append_late_constituent_to_sealed_source(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    with case.sessions() as session:
        original = session.scalar(select(ConstituentHoldingModel).limit(1))
        assert original is not None
        owner, snapshot = original.owner_id, original.snapshot_id
    with pytest.raises(IntegrityError), case.sessions() as session, session.begin():
        session.add(
            ConstituentHoldingModel(
                owner_id=owner,
                snapshot_id=snapshot,
                ordinal=99999,
                source_key="late-source-row",
                state="unresolved",
                currency="EUR",
                weight=Decimal("0"),
            )
        )
        session.flush()


def test_raw_sql_retention_cannot_authorize_an_unexpired_dependency(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    result = asyncio.run(company(case))
    with case.sessions() as session:
        dependency = session.scalar(
            select(XrayInputDependencyModel)
            .where(
                XrayInputDependencyModel.input_id == UUID(result.context.input_snapshot_id),
                XrayInputDependencyModel.constituent_snapshot_id.is_not(None),
            )
            .limit(1)
        )
        assert dependency is not None
        owner, capture, identifier = dependency.owner_id, dependency.input_id, dependency.id
    with pytest.raises(IntegrityError), case.sessions() as session, session.begin():
        session.add(
            XrayRetentionEventModel(
                owner_id=owner,
                input_id=capture,
                dependency_id=identifier,
                expired_at=case.now[0],
                created_at=case.now[0],
            )
        )
        session.flush()


def test_source_expiry_resumes_bounded_copies_and_denies_pending_replay(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    result = asyncio.run(company(case))
    input_id = UUID(result.context.input_snapshot_id)
    with case.sessions() as session:
        constituent_ids = tuple(
            session.scalars(
                select(XrayInputDependencyModel.constituent_snapshot_id)
                .where(
                    XrayInputDependencyModel.input_id == input_id,
                    XrayInputDependencyModel.constituent_snapshot_id.is_not(None),
                )
                .distinct()
            )
        )
        assert constituent_ids
        expiry = session.scalar(
            select(func.min(ConstituentSnapshotModel.expires_at)).where(
                ConstituentSnapshotModel.id.in_(constituent_ids)
            )
        )
        assert expiry is not None
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        input_bytes, input_digest = retained_capture.canonical_input, retained_capture.input_digest
        state = session.get_one(XrayPhysicalStateModel, input_id)
        physical_before = (state.input_pending, state.payload_rows)
    case.now[0] = expiry + timedelta(seconds=1)
    with case.sessions() as session, session.begin():
        budget = SourcePurgeBudget(
            rows_inspected=8, rows_removed=8, bytes_inspected=8192, bytes_removed=8192
        )
        completed = expire_source_payloads(session, at=case.now[0], limit=1, budget=budget)
        assert completed == 0
        assert 0 <= budget.rows_inspected < 8 and 0 <= budget.rows_removed <= 8
        # A full marker/guard/epoch reservation cannot fit eight inspections.
        assert session.scalar(select(SourceRetentionWorkModel.id).limit(1)) is None
        state = session.get_one(XrayPhysicalStateModel, input_id)
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        assert (state.input_pending, state.payload_rows) == physical_before
        assert (retained_capture.canonical_input, retained_capture.input_digest) == (
            input_bytes,
            input_digest,
        )
    with case.sessions() as session, session.begin():
        budget = SourcePurgeBudget(
            rows_inspected=128, rows_removed=8, bytes_inspected=8192, bytes_removed=8192
        )
        assert expire_source_payloads(session, at=case.now[0], limit=1, budget=budget) == 0
        assert 0 <= budget.rows_inspected < 128
        # This turn starts behind the other source families after the eight-row
        # probe. Its remaining allowance cannot reserve the constituent marker.
        assert session.scalar(select(SourceRetentionWorkModel.id).limit(1)) is None
        state = session.get_one(XrayPhysicalStateModel, input_id)
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        assert (state.input_pending, state.payload_rows) == physical_before
        assert (retained_capture.canonical_input, retained_capture.input_digest) == (
            input_bytes,
            input_digest,
        )
        assert session.scalar(select(SourceExpiryEventModel.id).limit(1)) is None
    # The next declared invocations keep the same small allowance. One complete
    # five-family rotation gives the relevant constituent an earlier turn.
    for _ in range(5):
        with case.sessions() as session, session.begin():
            budget = SourcePurgeBudget(
                rows_inspected=128, rows_removed=8, bytes_inspected=8192, bytes_removed=8192
            )
            assert expire_source_payloads(session, at=case.now[0], limit=1, budget=budget) == 0
            assert 0 <= budget.rows_inspected <= 128 and 0 <= budget.rows_removed <= 8
            assert 0 <= budget.bytes_inspected <= 8192 and 0 <= budget.bytes_removed <= 8192
            pending = session.scalar(
                select(SourceRetentionWorkModel.id)
                .where(
                    SourceRetentionWorkModel.owner_id == UUID(case.principal.owner_id),
                    SourceRetentionWorkModel.constituent_snapshot_id.in_(constituent_ids),
                    SourceRetentionWorkModel.phase != "complete",
                )
                .limit(1)
            )
            assert session.scalar(select(SourceExpiryEventModel.id).limit(1)) is None
        if pending is not None:
            break
    else:
        pytest.fail("a bounded source-family rotation did not create relevant pending work")
    owner = UUID(case.principal.owner_id)
    run_id = UUID(result.context.run_id)
    with case.sessions() as session:
        assert (
            session.scalar(
                select(XrayRetentionEventModel.id).where(
                    XrayRetentionEventModel.owner_id == owner,
                    XrayRetentionEventModel.input_id == input_id,
                )
            )
            is None
        )
        collections = session.execute(
            select(CollectionQuerySnapshotModel.id, CollectionQuerySnapshotModel.expires_at)
            .join(
                XrayCollectionBindingModel,
                XrayCollectionBindingModel.collection_id == CollectionQuerySnapshotModel.id,
            )
            .where(
                XrayCollectionBindingModel.owner_id == owner,
                XrayCollectionBindingModel.run_id == run_id,
            )
        ).all()
        database_now = session.scalar(select(func.current_timestamp()))
        assert database_now is not None and collections
        assert all(row.expires_at > database_now for row in collections)
        collection_ids = tuple(row.id for row in collections)
        member_count = session.scalar(
            select(func.count(CollectionQuerySnapshotMemberModel.record_id)).where(
                CollectionQuerySnapshotMemberModel.snapshot_id.in_(collection_ids)
            )
        )
        state = session.get_one(XrayPhysicalStateModel, input_id)
        before_rejected_cleanup = (state.input_pending, state.payload_rows)
    # Source work alone does not authorize collection deletion. The controlled
    # maintenance clock is ahead of these real-clock TTLs, so the SQL guard rejects
    # cleanup until normal source expiry publishes the capture's own event.
    with pytest.raises(app.XrayServiceError) as premature:
        asyncio.run(
            case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=case.request(run_id=result.context.run_id)
                ),
            )
        )
    assert premature.value.code is app.XrayServiceErrorCode.VALIDATION_FAILED
    with case.sessions() as session:
        state = session.get_one(XrayPhysicalStateModel, input_id)
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        assert (state.input_pending, state.payload_rows) == before_rejected_cleanup
        assert (retained_capture.canonical_input, retained_capture.input_digest) == (
            input_bytes,
            input_digest,
        )
        assert (
            session.scalar(
                select(func.count(CollectionQuerySnapshotMemberModel.record_id)).where(
                    CollectionQuerySnapshotMemberModel.snapshot_id.in_(collection_ids)
                )
            )
            == member_count
        )
        assert session.scalar(
            select(func.count(XrayCollectionBindingModel.id)).where(
                XrayCollectionBindingModel.owner_id == owner,
                XrayCollectionBindingModel.collection_id.in_(collection_ids),
            )
        ) == len(collection_ids)
    # At most five additional full-budget invocations establish the derivative
    # marker; the original 128-invocation copy-drain prefix follows unchanged.
    for _ in range(5):
        with case.sessions() as session, session.begin():
            budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            assert expire_source_payloads(session, at=case.now[0], limit=1, budget=budget) == 0
            assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
            assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
            assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024
            parent_event = session.scalar(
                select(XrayRetentionEventModel.id).where(
                    XrayRetentionEventModel.owner_id == owner,
                    XrayRetentionEventModel.input_id == input_id,
                )
            )
            state = session.get_one(XrayPhysicalStateModel, input_id)
            assert state.input_pending and state.payload_rows > 0
        if parent_event is not None:
            break
    else:
        pytest.fail("bounded source expiry did not publish the retained capture event")
    with pytest.raises(app.XrayServiceError) as denied:
        asyncio.run(
            case.service.get_effective_exposure(
                case.principal,
                XRAY_ACCOUNT_ID,
                query=app.EffectiveExposureQuery(
                    request=case.request(run_id=result.context.run_id)
                ),
            )
        )
    assert denied.value.code is app.XrayServiceErrorCode.ACCESS_DENIED
    with case.sessions() as session:
        state = session.get_one(XrayPhysicalStateModel, input_id)
        before_copy_rows = state.payload_rows
        assert state.input_pending and before_copy_rows > 0
    completed = 0
    for _ in range(128):
        with case.sessions() as session, session.begin():
            budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            completed += expire_source_payloads(session, at=case.now[0], limit=1, budget=budget)
            assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
            assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
            assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024
            if completed:
                break
    # Preserve the original prefix as a physical partial-progress boundary.
    # Event establishment above is separate from these copy-drain invocations.
    with case.sessions() as session:
        state = session.get_one(XrayPhysicalStateModel, input_id)
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        assert state.input_pending and 0 < state.payload_rows < before_copy_rows
        assert (retained_capture.canonical_input, retained_capture.input_digest) == (
            input_bytes,
            input_digest,
        )
        assert completed == 0
        assert session.scalar(select(SourceExpiryEventModel.id).limit(1)) is None
    for _ in range(128):
        with case.sessions() as session, session.begin():
            budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            completed += expire_source_payloads(session, at=case.now[0], limit=1, budget=budget)
            assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
            assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
            assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024
        if completed:
            break
    else:
        pytest.fail("source copies did not drain within 256 bounded copy-drain invocations")
    assert completed == 1
    with case.sessions() as session:
        capture = session.get(XrayInputSnapshotModel, input_id)
        assert capture is not None and capture.canonical_input == b""
        assert capture.input_digest == input_digest
        run = session.scalar(select(XrayRunModel).where(XrayRunModel.input_id == input_id))
        assert run is not None and run.canonical_summary == b""
        stored = session.get(AnalyticsRunModel, run.analytics_run_id)
        assert (
            stored is not None and stored.canonical_input == b"" and stored.canonical_result == b""
        )
        assert session.scalar(select(SourceExpiryEventModel.id).limit(1)) is not None
        assert (
            session.scalar(
                select(func.count(XrayExposureModel.id)).where(
                    XrayExposureModel.run_id == run.id, XrayExposureModel.bucket_key.is_not(None)
                )
            )
            == 0
        )


def test_run_account_binding_rejects_missing_account_before_decoding(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    result = asyncio.run(company(case))
    with pytest.raises(app.XrayServiceError) as rejected:
        asyncio.run(
            case.service.get_effective_exposure(
                case.principal,
                str(uuid4()),
                query=app.EffectiveExposureQuery(request=case.request(result.context.run_id)),
            )
        )
    assert rejected.value.code is app.XrayServiceErrorCode.NOT_FOUND


def test_input_publication_cannot_commit_without_final_seal(xray_read_case: XrayReadCase) -> None:
    case = xray_read_case
    result = asyncio.run(company(case))
    with case.sessions() as session:
        source = session.get(XrayInputSnapshotModel, UUID(result.context.input_snapshot_id))
        assert source is not None
        fields = {column.name: getattr(source, column.name) for column in source.__table__.columns}
    fields.update(id=uuid4(), input_digest=uuid4().hex * 2, sealed_at=None)
    with (
        pytest.raises(IntegrityError, match="X-ray publication is incomplete"),
        case.sessions() as session,
        session.begin(),
    ):
        session.add(XrayInputSnapshotModel(**fields))
        session.flush()  # Incomplete publication is allowed only inside this transaction.


def test_run_publication_cannot_commit_without_final_seal(xray_read_case: XrayReadCase) -> None:
    case = xray_read_case

    def omit_run_seal(session: Session, flush_context: object, instances: object) -> None:
        # Simulate an interrupted publisher that completes the parent and all
        # projections but omits only the run's final seal assignment.
        for row in session.dirty:
            if isinstance(row, XrayRunModel):
                row.sealed_at = None

    with (
        pytest.raises(IntegrityError, match="X-ray publication is incomplete"),
        case.sessions() as session,
        session.begin(),
    ):
        event.listen(session, "before_flush", omit_run_seal)
        captured = capture_xray(
            case.service,
            session,
            UUID(case.principal.owner_id),
            UUID(XRAY_ACCOUNT_ID),
            case.request(),
        )
        run = publish_xray(case.service, session, captured)
        session.flush()
        parent = session.get(XrayInputSnapshotModel, run.input_id)
        assert parent is not None and parent.sealed_at is not None
        assert run.sealed_at is None


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("xray_policy_versions", "canonical_policy", "'\\x'::bytea"),
        ("xray_taxonomies", "version", "'rewritten'"),
        ("xray_command_identities", "request_digest", "repeat('0',64)"),
    ],
)
def test_registration_cannot_be_rewritten(
    xray_read_case: XrayReadCase, table: str, column: str, value: str
) -> None:
    with (
        pytest.raises(IntegrityError, match="X-ray registration is immutable"),
        xray_read_case.engine.begin() as connection,
    ):
        connection.execute(text(f"UPDATE {table} SET {column}={value}"))  # noqa: S608 -- closed test cases above


@pytest.mark.parametrize(
    "model,reference",
    [
        (EntityEvidenceVersionModel, "entity_evidence_version_id"),
        (ClassificationSnapshotModel, "classification_snapshot_id"),
        (FundDefinitionModel, "fund_definition_id"),
        (FundSourceMappingModel, "fund_mapping_id"),
    ],
)
def test_enrichment_expiry_cannot_claim_completion_while_licensed_payload_remains(
    xray_read_case: XrayReadCase, model: type, reference: str
) -> None:
    case = xray_read_case
    with case.sessions() as session:
        source = session.scalar(select(model).limit(1))
        assert source is not None
        owner, identifier, digest, at = (
            source.owner_id,
            source.id,
            source.content_digest,
            source.expires_at + timedelta(seconds=1),
        )
    with (
        pytest.raises(IntegrityError, match="Enrichment licensed payloads remain pending"),
        case.sessions() as session,
        session.begin(),
    ):
        work = EnrichmentRetentionWorkModel(
            owner_id=owner,
            **{reference: identifier},
            started_at=at,
            created_at=at,
            content_digest=digest,
            phase="copies",
            removed_row_count=0,
        )
        session.add(work)
        session.flush()
        work.phase = "payloads"
        session.flush()
        session.add(
            EnrichmentExpiryEventModel(
                owner_id=owner,
                **{reference: identifier},
                expired_at=at,
                created_at=at,
                content_digest=digest,
                removed_row_count=0,
            )
        )
        session.flush()


def test_all_enrichment_families_resume_and_remove_licensed_payloads(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    result = asyncio.run(company(case))
    input_id = UUID(result.context.input_snapshot_id)
    families: tuple[type[XrayEvidenceFields], ...] = (
        EntityEvidenceVersionModel,
        ClassificationSnapshotModel,
        FundDefinitionModel,
        FundSourceMappingModel,
    )
    with case.sessions() as session:
        state = session.get_one(XrayPhysicalStateModel, input_id)
        initial_payload_rows = state.payload_rows
        assert state.input_pending and initial_payload_rows > 0
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        input_bytes, input_digest = retained_capture.canonical_input, retained_capture.input_digest
        count = sum(session.scalar(select(func.count(model.id))) or 0 for model in families)
        expiries = tuple(session.scalar(select(func.max(model.expires_at))) for model in families)
        assert all(value is not None for value in expiries)
        expiry = max(value for value in expiries if value is not None)
    assert expiry is not None and count > 0
    at = expiry + timedelta(seconds=1)

    def advance() -> int:
        with case.sessions() as session, session.begin():
            budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
            removed = expire_enrichment_payloads(session, at=at, limit=1, budget=budget)
            assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
            assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
            assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024
            assert 0 <= budget.captures <= 100 and 0 <= budget.runs <= 100
            return removed

    completed = 0
    for _ in range(128):
        completed += advance()
    # The original prefix is a real partial cleanup: copied rows decrease while
    # the capture remains pending. Its permanent input identity stays unchanged.
    with case.sessions() as session:
        state = session.get_one(XrayPhysicalStateModel, input_id)
        assert state.input_pending and 0 < state.payload_rows < initial_payload_rows
        retained_capture = session.get_one(XrayInputSnapshotModel, input_id)
        assert (retained_capture.canonical_input, retained_capture.input_digest) == (
            input_bytes,
            input_digest,
        )
        assert completed < count
        assert session.scalar(select(func.count(EnrichmentExpiryEventModel.id))) == completed
    for _ in range(128):
        completed += advance()
        if completed == count:
            break
    else:
        pytest.fail("enrichment cleanup did not complete within 256 bounded invocations")
    assert completed == count
    with case.sessions() as session:
        assert session.scalar(select(func.count(EnrichmentExpiryEventModel.id))) == count
        capture = session.get(XrayInputSnapshotModel, input_id)
        assert capture is not None and capture.canonical_input == b""
        assert capture.input_digest == input_digest
        for model, columns in (
            (EntityEvidenceVersionModel, ("confidence",)),
            (ClassificationSnapshotModel, ("confidence",)),
            (FundDefinitionModel, ("fund_type", "evidence_key", "confidence")),
            (FundSourceMappingModel, ("provider_fund_key", "evidence_key", "confidence")),
        ):
            for row in session.scalars(select(model)):
                assert all(getattr(row, column) is None for column in columns)
