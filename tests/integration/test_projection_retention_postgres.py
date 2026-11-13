"""Actual projection publication, source lineage and resumable physical erasure."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, Table, delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.projection import calculate_projection, calculate_projection_chunk
from trading212_application import projection as app
from trading212_application import sources as source_app
from trading212_application.historical_evidence import HistoricalEvidenceRegistration
from trading212_application.projection_capture import (
    ProjectionDatedSchedule,
    ProjectionInitialSelection,
    ProjectionRunSelection,
)
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import SourceCapability
from trading212_domain import historical as historical_domain
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionSourcePin,
)
from trading212_domain.sources import LicensePermission, PriceBasis, source_snapshot_digest
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence import projection_retention as retention
from trading212_persistence.aggregation_models import AggregateOwnerErasureModel
from trading212_persistence.historical_models import (
    HistoricalDependencyModel,
    HistoricalInputModel,
    HistoricalRetentionEventModel,
)
from trading212_persistence.models import BrokerConnectionModel, PrincipalModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from trading212_persistence.projection_models import (
    ProjectionInputModel,
    ProjectionResultModel,
    ProjectionRunSourceModel,
    ProjectionSourceProofModel,
)
from trading212_persistence.projection_retention_models import (
    ProjectionRetentionEpochModel,
    ProjectionRetentionScanModel,
)
from trading212_persistence.projection_retention_policy import projection_run_restricted
from trading212_persistence.projection_retention_scan import scan_projection_sources
from trading212_persistence.projection_service import PostgresProjectionService
from trading212_persistence.scenario_retention import purge_owner_scenario_payloads
from trading212_persistence.source_models import PriceObservationModel, PriceSnapshotModel
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.test_historical_postgres import historical_case, policy, selection
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_projection_jobs_postgres import admitted, store
from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_sources_postgres import KEY, ingest
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def measured(case: ProjectionJobCase) -> int:
    with case.sessions() as session:
        value = session.scalar(select(func.projection_storage_bytes(case.run.id)))
        assert type(value) is int
        return value


async def published(case: ProjectionJobCase, *, complete: bool) -> None:
    worker = store(case)
    dispatch = await admitted(case, worker)
    claim = await worker.claim_projection_job(dispatch.message, consumer_id="retention-proof")
    assert claim is not None
    captured = await worker.load_projection_job_input(claim)
    chunk = calculate_projection_chunk(captured.inputs, 0, captured.inputs.paths)
    assert await worker.save_projection_job_chunk(claim, chunk)
    if complete:
        assert await worker.complete_projection_job(claim, calculate_projection(captured.inputs))


def drain(case: ProjectionJobCase, *, budget: SourcePurgeBudget | None = None) -> bool:
    with case.sessions() as session, session.begin():
        return retention.expire_projection_payloads(
            session,
            at=case.now,
            owner=UUID(case.principal.owner_id),
            budget=budget or SourcePurgeBudget(),
        )


def empty(case: ProjectionJobCase) -> None:
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        assert root.reserved_bytes == root.retained_bytes == 0
        assert session.scalar(select(func.projection_storage_bytes(root.id))) == 0
        marker = session.scalar(
            select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == root.id)
        )
        assert marker is not None and marker.completed_at is not None
        for model, _ in retention.PROJECTION_PAYLOADS:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(retention._scope(cast(Table, model.__table__), root))
                )
                == 0
            )


async def test_partial_checkpoint_cleanup_fences_and_refunds_exact_actual_bytes(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    await published(case, complete=False)
    with case.sessions() as session:
        expiry = session.get_one(PremiumRunModel, case.run.id).expires_at
    case.now = expiry + timedelta(microseconds=1)
    before = measured(case)
    assert before > 0
    with patch(
        "trading212_domain.projection_serialization.decode_projection_input",
        side_effect=AssertionError("retention decoded financial input"),
    ):
        assert not drain(case, budget=SourcePurgeBudget(rows_inspected=512, rows_removed=6))
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        actual = session.scalar(select(func.projection_storage_bytes(root.id)))
        job = session.get_one(PremiumJobModel, case.run.job_id)
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert isinstance(actual, int) and 0 < actual < before
        assert root.retained_bytes == actual and root.reserved_bytes == 0
        assert capacity.active_jobs == 0 and capacity.retained_bytes == actual
        assert job.state == "expired" and job.lease_token is None
        marker = session.scalar(
            select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == root.id)
        )
        assert marker is not None and marker.completed_at is None
    for _ in range(10):
        if drain(case):
            break
    else:
        pytest.fail("bounded projection purge did not finish")
    empty(case)
    assert drain(case)


async def test_published_result_and_input_proof_require_marker_and_keep_tombstones(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    await published(case, complete=True)
    with case.sessions() as session:
        result = session.scalar(
            select(ProjectionResultModel).where(ProjectionResultModel.run_id == case.run.id)
        )
        assert result is not None
        identity, digest = result.id, result.content_digest
    with pytest.raises(IntegrityError), case.sessions() as session, session.begin():
        session.execute(
            delete(ProjectionInputModel).where(ProjectionInputModel.run_id == case.run.id)
        )
    with pytest.raises(IntegrityError), case.sessions() as session, session.begin():
        root = session.get_one(PremiumRunModel, case.run.id)
        session.add(
            PremiumRetentionModel(
                id=uuid4(),
                owner_id=root.owner_id,
                account_id=root.account_id,
                run_id=root.id,
                reason="owner_erasure",
                created_at=case.now,
                completed_at=case.now,
            )
        )
        session.flush()
    # The operator-owned composition requires terminated synthetic identities.
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        capacity = session.get_one(PremiumCapacityModel, owner)
        job = session.get_one(PremiumJobModel, case.run.job_id)
        before = (
            root.reserved_bytes,
            root.retained_bytes,
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.active_jobs,
            job.state,
            measured(case),
        )
        assert (
            session.scalar(
                select(PrincipalModel.id)
                .where(PrincipalModel.owner_id == owner, PrincipalModel.status == "active")
                .limit(1)
            )
            is not None
        )
        assert (
            session.scalar(
                select(BrokerConnectionModel.id)
                .where(
                    BrokerConnectionModel.owner_id == owner,
                    BrokerConnectionModel.status == "active",
                )
                .limit(1)
            )
            is not None
        )
    with (
        pytest.raises(IntegrityError, match="aggregate owner remains active"),
        case.sessions() as session,
        session.begin(),
    ):
        purge_owner_scenario_payloads(session, owner, at=case.now, budget=SourcePurgeBudget())
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        capacity = session.get_one(PremiumCapacityModel, owner)
        job = session.get_one(PremiumJobModel, case.run.job_id)
        assert (
            root.reserved_bytes,
            root.retained_bytes,
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.active_jobs,
            job.state,
            measured(case),
        ) == before
        assert session.get(AggregateOwnerErasureModel, owner) is None
        assert session.get_one(ProjectionResultModel, identity).content_digest == digest
    with case.sessions() as session, session.begin():
        session.execute(
            update(PrincipalModel).where(PrincipalModel.owner_id == owner).values(status="disabled")
        )
        session.execute(
            update(BrokerConnectionModel)
            .where(BrokerConnectionModel.owner_id == owner)
            .values(status="disabled")
        )
    # Keep the existing complete-erasure requirement and the shared default budget.
    with case.sessions() as session, session.begin():
        assert purge_owner_scenario_payloads(
            session, owner, at=case.now, budget=SourcePurgeBudget()
        )
    empty(case)
    with case.sessions() as session:
        retained = session.get_one(ProjectionResultModel, identity)
        assert retained.content_digest == digest and retained.canonical_result == b""


async def test_busy_owner_does_not_block_or_mutate_projection_cleanup(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    with case.sessions() as session:
        case.now = session.get_one(PremiumRunModel, case.run.id).expires_at + timedelta(seconds=1)
    with case.sessions() as held, held.begin():
        held.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "sources:" + case.principal.owner_id},
        )
        assert not drain(case)
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(PremiumRetentionModel.id).where(
                        PremiumRetentionModel.run_id == case.run.id
                    )
                )
                is None
            )
    assert drain(case)
    empty(case)


@pytest.mark.parametrize("kind", ("price", "historical", "historical_nested", "future_price"))
async def test_original_source_restriction_and_parent_blocker_drain_actual_derived_copies(
    historical_database: tuple[Engine, sessionmaker[Session]],
    kind: str,
) -> None:
    _, sessions = historical_database
    source, account, history = await historical_case(sessions)
    old_cutoff = source.request.source_cutoff_at
    with sessions() as session:
        publication_at = session.scalar(select(func.clock_timestamp()))
        assert isinstance(publication_at, datetime) and publication_at > old_cutoff
    source.now[0] = publication_at
    await source.service.configure_source_provider(
        source.principal,
        SourceProviderRegistration(
            id=source.series.provider_id,
            key="synthetic-source",
            name="Synthetic source",
            adapter_version="synthetic-v1",
            configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.PRICE_HISTORY,),
            supported_price_bases=(PriceBasis.RAW_CLOSE, PriceBasis.TOTAL_RETURN),
        ),
        idempotency_key="retention-total-return-provider",
        correlation_id="projection-retention",
    )
    series = replace(source.series, id=str(uuid4()), basis=PriceBasis.TOTAL_RETURN)
    await source.service.register_source_series(
        source.principal,
        series,
        idempotency_key="retention-total-return-series",
        correlation_id="projection-retention",
    )
    source = replace(
        source,
        series=series,
        request=replace(source.request, series=series, source_cutoff_at=publication_at),
        pages=tuple(
            replace(
                page,
                series=series,
                provenance=replace(page.provenance, first_observed_at=publication_at),
            )
            for page in source.pages
        ),
    )
    financial_observations = tuple(item for page in source.pages for item in page.observations)
    original = await ingest(source, key="retention-original-price")
    assert original.observations == financial_observations and len(original.observations) == 3
    assert original.provenance.first_observed_at == publication_at > old_cutoff
    with sessions() as session:
        original_header = session.get_one(PriceSnapshotModel, UUID(original.id))
        original_created_at = original_header.created_at
        assert original_created_at == publication_at
        assert source.license.retention_days is not None
        assert original_header.expires_at == publication_at + timedelta(
            days=source.license.retention_days
        )
    younger_price_id: UUID | None = None
    younger_created_at: datetime | None = None
    pin = ProjectionSourcePin(
        subject_id=original.id, content_digest=source_snapshot_digest(original)
    )
    historical_id: UUID | None = None
    if kind in ("historical", "historical_nested"):
        registration = policy(source)
        if kind == "historical_nested":
            # The original price is reachable through input -> evidence -> price,
            # never through the historical input's direct price selection.
            registration = replace(registration, price_series_ids=())
            previous = original.id
            for index in range(2):
                source.now[0] += timedelta(microseconds=1)
                evidence = HistoricalEvidenceRegistration(
                    id=str(uuid4()),
                    key=f"retention-nested-{index}",
                    opening=historical_domain.InceptionHistoricalOpening(
                        inception_at=selection(None).window.start_at,
                        source_refs=(previous,),
                        bridge_coverage=historical_domain.HistoricalCoverage(measures=()),
                    ),
                )
                if index == 1:
                    from trading212_application.historical import HistoricalServiceError

                    # The accepted historical contract rejects evidence -> evidence.
                    # Preserve that boundary while testing the legal transitive copy.
                    with pytest.raises(HistoricalServiceError) as rejected:
                        await history.register_historical_evidence(
                            source.principal,
                            account,
                            evidence,
                            idempotency_key=f"projection-nested-{index}",
                            correlation_id="projection-retention",
                        )
                    assert rejected.value.code.value == "VALIDATION_FAILED"
                else:
                    await history.register_historical_evidence(
                        source.principal,
                        account,
                        evidence,
                        idempotency_key=f"projection-nested-{index}",
                        correlation_id="projection-retention",
                    )
                    previous = evidence.id
            # The latest opening has its own later physical witness. The older
            # registered evidence still retains the original price transitively.
            with sessions() as session:
                younger_at = session.scalar(select(func.clock_timestamp()))
                assert isinstance(younger_at, datetime) and younger_at > original_created_at
            source.now[0] = younger_at
            younger_source = replace(
                source,
                request=replace(source.request, source_cutoff_at=younger_at),
                pages=tuple(
                    replace(
                        page,
                        provenance=replace(
                            page.provenance,
                            source_revision="retention-younger-opening-v2",
                            revision_order=2,
                            first_observed_at=younger_at,
                        ),
                    )
                    for page in source.pages
                ),
            )
            younger = await ingest(younger_source, key="retention-younger-opening-price")
            assert younger.id != original.id and younger.observations == original.observations
            younger_price_id = UUID(younger.id)
            with sessions() as session:
                younger_created_at = session.get_one(
                    PriceSnapshotModel, younger_price_id
                ).created_at
                assert (
                    younger_created_at
                    == younger_at
                    > original_created_at + timedelta(microseconds=1)
                )
            await history.register_historical_evidence(
                source.principal,
                account,
                HistoricalEvidenceRegistration(
                    id=str(uuid4()),
                    key="retention-nested-outer-opening",
                    opening=historical_domain.InceptionHistoricalOpening(
                        inception_at=selection(None).window.start_at,
                        source_refs=(younger.id,),
                        bridge_coverage=historical_domain.HistoricalCoverage(measures=()),
                    ),
                ),
                idempotency_key="projection-nested-outer-opening",
                correlation_id="projection-retention",
            )
        await history.register_historical_policy(
            source.principal,
            account,
            registration,
            idempotency_key="projection-retention-policy",
            correlation_id="projection-retention",
        )
        # The historical copy is younger than its immutable price parent. Tightening
        # later must use the original price clock, not this newer historical header.
        with sessions() as session:
            captured_at = session.scalar(select(func.clock_timestamp()))
            assert isinstance(captured_at, datetime)
        assert captured_at > original_created_at + timedelta(microseconds=1)
        source.now[0] = captured_at
        request = selection(registration)
        captured = await history.capture(
            source.principal,
            account,
            request=replace(
                request, window=replace(request.window, source_cutoff_at=source.now[0])
            ),
        )
        historical_id = UUID(captured.id)
        with sessions() as session:
            historical_created_at = session.get_one(HistoricalInputModel, historical_id).created_at
            assert historical_created_at == captured_at
            direct = session.scalar(
                select(HistoricalDependencyModel.id).where(
                    HistoricalDependencyModel.input_id == historical_id,
                    HistoricalDependencyModel.price_snapshot_id == UUID(original.id),
                )
            )
            assert (direct is None) == (kind == "historical_nested")
            if kind == "historical_nested":
                assert younger_price_id is not None
                assert (
                    session.scalar(
                        select(HistoricalDependencyModel.id).where(
                            HistoricalDependencyModel.input_id == historical_id,
                            HistoricalDependencyModel.price_snapshot_id == younger_price_id,
                        )
                    )
                    is not None
                )
                links = session.execute(
                    text(
                        "SELECT id,evidence_id,price_snapshot_id,registered_evidence_id "
                        "FROM projection_history_links(:owner,:input)"
                    ),
                    {"owner": UUID(source.principal.owner_id), "input": historical_id},
                ).all()
                assert len({row.id for row in links}) == len(links)
                assert any(
                    row.evidence_id is not None and row.price_snapshot_id == UUID(original.id)
                    for row in links
                )
                assert any(
                    row.evidence_id is None and row.registered_evidence_id is not None
                    for row in links
                )
        pin = ProjectionSourcePin(subject_id=captured.id, content_digest=captured.input_digest)
    with sessions() as session:
        now = session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        source.now[0] = now
    source.principal = replace(source.principal, subject=source.principal.owner_id)
    grant_scenario_identity(sessions, source.principal, now)
    service = PostgresProjectionService(
        sessions, cursor_signing_key=KEY, clock=lambda: source.now[0]
    )
    currency = CurrencyCode("EUR")
    definition = await service.create_assumption_set(
        source.principal,
        app.CreateAssumptionSet(
            account_id=UUID(account),
            metadata=ProjectionVersionMetadata(
                name="Retained calibration", description="Synthetic original proof"
            ),
            content=ProjectionAssumptions(
                assets=(
                    ProjectionAsset(
                        key="equity",
                        annual_mean_log_return=Decimal(".03"),
                        annual_volatility=Decimal(".1"),
                        weight=Decimal(1),
                    ),
                ),
                correlation=((Decimal(1),),),
                reporting_currency=currency,
                annual_inflation=Decimal(0),
                annual_fee=Decimal(0),
                annual_tax_drag=Decimal(0),
                calibration_pins=(pin,),
            ),
            idempotency_key=str(uuid4()),
            correlation_id="projection-retention",
        ),
    )
    run = await service.create_run(
        source.principal,
        app.CreateProjectionRun(
            selection=ProjectionRunSelection(
                account_id=UUID(account),
                assumption_version_id=definition.current_version_id,
                initial=ProjectionInitialSelection(
                    kind="modeled_value",
                    modeled_value=Money(Decimal(100), currency),
                    modeled_anchor_date=now.date(),
                ),
                schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(0), currency)),
                seed=7,
                months=1,
                paths=1,
                retained_months=(0, 1),
                allocation=(ProjectionAllocation(key="equity", weight=Decimal(1)),),
            ),
            idempotency_key=str(uuid4()),
            correlation_id="projection-retention",
        ),
    )
    owner = UUID(source.principal.owner_id)
    with sessions() as session:
        assert session.scalar(
            select(func.projection_references_source(owner, run.id, "price", UUID(original.id)))
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionSourceProofModel)
                .where(ProjectionSourceProofModel.run_id == run.id)
            )
            == 1
        )
    with (
        pytest.raises(IntegrityError, match="Projection source copies remain"),
        sessions() as session,
        session.begin(),
    ):
        session.execute(
            delete(PriceObservationModel).where(
                PriceObservationModel.snapshot_id == UUID(original.id)
            )
        )
    with sessions() as held, held.begin():
        held.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "sources:" + str(owner)},
        )
        with pytest.raises(DBAPIError) as busy, sessions() as session, session.begin():
            session.execute(
                delete(PriceObservationModel).where(
                    PriceObservationModel.snapshot_id == UUID(original.id)
                )
            )
        assert getattr(busy.value.orig, "sqlstate", None) == "55P03"
    if historical_id is not None:
        with (
            pytest.raises(IntegrityError, match="Projection source copies remain"),
            sessions() as session,
            session.begin(),
        ):
            dependency_id = session.scalar(
                select(HistoricalDependencyModel.id)
                .where(HistoricalDependencyModel.input_id == historical_id)
                .limit(1)
            )
            assert dependency_id is not None
            session.add(
                HistoricalRetentionEventModel(
                    owner_id=owner,
                    input_id=historical_id,
                    dependency_id=dependency_id,
                    removed_at=now,
                    created_at=now,
                    reason="retention_removed",
                )
            )
            session.flush()
    # Build a clean maintenance cache through repeated small, metadata-only steps.
    # The later policy publication must invalidate it before trusting old deadlines.
    progress: list[str] = []
    for _ in range(20):
        with sessions() as session, session.begin():
            root = session.get_one(PremiumRunModel, run.id)
            assert retention._lock_owner(session, owner)
            budget = SourcePurgeBudget(rows_inspected=48)
            outcome = scan_projection_sources(session, root, at=now, budget=budget)
            assert 0 <= budget.rows_inspected <= 48
            progress.append(outcome)
        if outcome == "clean":
            break
    else:
        pytest.fail("bounded original-source scan did not finish")
    with sessions() as session:
        cached_epoch = session.scalar(
            select(ProjectionRetentionScanModel.policy_epoch).where(
                ProjectionRetentionScanModel.run_id == run.id,
                ProjectionRetentionScanModel.purpose == "expiry",
            )
        )
        assert isinstance(cached_epoch, int)
    maintenance_at = original_created_at + timedelta(days=2, microseconds=1)
    assert maintenance_at > now
    with sessions() as session:
        root = session.get_one(PremiumRunModel, run.id)
        assert maintenance_at < root.expires_at
        if historical_id is not None:
            assert maintenance_at < session.get_one(
                HistoricalInputModel, historical_id
            ).created_at + timedelta(days=2)
        if younger_created_at is not None:
            assert maintenance_at < younger_created_at + timedelta(days=2)
    shortened = replace(
        source.license,
        id=str(uuid4()),
        version="original-short-clock",
        effective_at=maintenance_at + timedelta(seconds=30) if kind == "future_price" else now,
        retention_days=2,
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
    )
    await source.service.register_source_license(
        source.principal,
        shortened,
        idempotency_key="projection-original-clock-policy",
        correlation_id="projection-retention",
    )
    # Publication and admission used real PostgreSQL time. Only the trusted
    # maintenance evaluation advances to the original source's two-day boundary.
    now = maintenance_at
    source.now[0] = now
    if kind == "future_price":
        with sessions() as session, session.begin():
            root = session.get_one(PremiumRunModel, run.id)
            assert retention._lock_owner(session, owner)
            assert (
                scan_projection_sources(session, root, at=now, budget=SourcePurgeBudget())
                == "clean"
            )
            sweep = session.scalar(
                select(ProjectionRetentionScanModel).where(
                    ProjectionRetentionScanModel.run_id == run.id
                )
            )
            assert sweep is not None and sweep.next_policy_at == shortened.effective_at
        now = shortened.effective_at
        source.now[0] = now
    with sessions() as session, session.begin():
        current_epoch = session.scalar(
            select(ProjectionRetentionEpochModel.epoch).where(
                ProjectionRetentionEpochModel.owner_id == owner
            )
        )
        assert isinstance(current_epoch, int) and current_epoch > cached_epoch
        assert session.scalar(select(func.projection_original_sources_restricted(run.id, now)))
        if historical_id is not None:
            assert (
                session.scalar(
                    select(projection_run_restricted(now))
                    .select_from(PremiumRunModel)
                    .where(PremiumRunModel.id == run.id)
                )
                is False
            )
        assert retention.expire_projection_payloads(
            session, owner=owner, at=now, budget=SourcePurgeBudget()
        )
        root = session.get_one(PremiumRunModel, run.id)
        assert root.reserved_bytes == root.retained_bytes == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionSourceProofModel)
                .where(ProjectionSourceProofModel.run_id == run.id)
            )
            == 0
        )
        # Permanent provenance remains; physical original data is a different participant.
        assert (
            session.scalar(
                select(ProjectionRunSourceModel.id).where(ProjectionRunSourceModel.run_id == run.id)
            )
            is not None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PriceObservationModel)
                .where(PriceObservationModel.snapshot_id == UUID(original.id))
            )
            == 3
        )
        if historical_id is not None:
            assert session.get_one(HistoricalInputModel, historical_id).canonical_input != b""
