"""Real immutable normalized modeled inputs through the production retained loader."""

from unittest.mock import patch

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_domain.projection import ProjectionSourcePin
from trading212_domain.sources import BenchmarkSnapshot, PriceSnapshot, SourceUse
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_input_store import ProjectionInputStore
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import AuthorizationError, Scope

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_migrations import database_engine as database_engine
from tests.integration.test_projection_definitions_postgres import ProjectionDefinitionCase
from tests.integration.test_projection_definitions_postgres import (
    projection_definition_case as projection_definition_case,
)
from tests.integration.test_projection_storage_postgres import queued_projection

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_modeled_input_reads_exact_existing_rows_without_resampling(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    original = queued_projection(c)
    store = ProjectionInputStore(
        sessionmaker(c.session.get_bind()),
        cursor_signing_key=b"projection-source-postgres-key32",
        clock=lambda: c.now,
    )
    with (
        patch(
            "trading212_analytics.projection.calculate_projection",
            side_effect=AssertionError("retained read resampled"),
        ),
        patch(
            "trading212_analytics.projection.calculate_projection_chunk",
            side_effect=AssertionError("retained read resampled"),
        ),
    ):
        loaded = store.read_retained_input(c.session, c.auth, original.run.id)
    assert loaded.plan == original.plan
    assert loaded.input_digest == original.root.input_digest
    assert loaded.sources.sources == () and loaded.sources.license_version_ids == ()
    assert loaded.stored.capture_bytes == len(loaded.stored.canonical_capture)
    assert loaded.stored.input_bytes == len(loaded.stored.canonical_input)


def test_revoked_grant_denies_before_private_or_normalized_financial_reads(
    projection_definition_case: ProjectionDefinitionCase, database_engine: Engine
) -> None:
    c = projection_definition_case
    original = queued_projection(c)
    grant = c.session.get(
        PrincipalScopeGrantModel, (c.auth.principal_id, Scope.ANALYTICS_READ.value)
    )
    assert grant is not None
    grant.revoked_at = c.now
    c.session.flush()
    store = ProjectionInputStore(
        sessionmaker(database_engine),
        cursor_signing_key=b"projection-source-postgres-key32",
        clock=lambda: c.now,
    )
    statements = []

    def observe(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        many: bool,
    ) -> None:
        statements.append(statement)

    event.listen(database_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(AuthorizationError):
            store.read_retained_input(c.session, c.auth, original.run.id)
    finally:
        event.remove(database_engine, "before_cursor_execute", observe)
    assert not any(
        name in sql
        for sql in statements
        for name in (
            "canonical_capture",
            "canonical_input",
            "initial_value",
            "projection_assumption_assets",
            "projection_correlation_cells",
        )
    )


def test_definition_uuid_is_not_calibration_source_authority(
    projection_definition_case: ProjectionDefinitionCase, database_engine: Engine
) -> None:
    c = projection_definition_case
    saved = c.store.publish_assumption_set(c.session, c.auth, c.assumption())
    version = c.store.read_assumption_version(c.session, c.auth, saved.current_version_id)
    store = ProjectionInputStore(
        sessionmaker(database_engine),
        cursor_signing_key=b"projection-source-postgres-key32",
        clock=lambda: c.now,
    )
    with pytest.raises(ProjectionStorageError) as error:
        store.sources.resolve_calibration(
            c.session,
            c.auth,
            (
                ProjectionSourcePin(
                    subject_id=str(version.id), content_digest=version.content_digest
                ),
            ),
            use=SourceUse.STORE,
            now=c.now,
        )
    assert error.value.code is app.ProjectionErrorCode.SOURCE_UNAVAILABLE


@pytest.mark.parametrize("kind", ["price", "benchmark", "historical"])
async def test_real_calibration_copies_original_full_proof_and_clocks(
    historical_database: tuple[Engine, sessionmaker[Session]], kind: str
) -> None:
    import json
    from dataclasses import replace
    from datetime import timedelta
    from uuid import UUID, uuid4

    from sqlalchemy import select
    from trading212_application import sources as source_app
    from trading212_application.source_ingestion import SourceProviderRegistration
    from trading212_application.source_providers import (
        BenchmarkSeriesPage,
        BenchmarkSeriesRequest,
        SourceCapability,
    )
    from trading212_domain.sources import (
        BenchmarkObservation,
        PriceBasis,
        SourceSeriesKind,
        source_snapshot_digest,
    )
    from trading212_persistence.models import PrincipalModel
    from trading212_persistence.projection_source_store import ProjectionSourceStore
    from trading212_persistence.report_authorization import ReportAuthorization

    from tests.integration.test_historical_postgres import historical_case, selection
    from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
    from tests.integration.test_sources_postgres import ingest

    engine, sessions = historical_database
    case, account, history = await historical_case(sessions)
    case.principal = replace(
        case.principal, subject=case.principal.owner_id, principal_id=str(uuid4())
    )
    grant_scenario_identity(sessions, case.principal, case.now[0])
    with sessions() as session:
        principal = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == case.principal.issuer,
                PrincipalModel.subject == case.principal.subject,
            )
        )
        assert principal is not None
        auth = ReportAuthorization(
            principal_id=principal.id,
            owner_id=UUID(case.principal.owner_id),
            account_id=UUID(account),
            required_scopes=frozenset((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ)),
            expires_at=case.now[0] + timedelta(days=30),
            issuer=principal.issuer,
            subject=principal.subject,
        )
    source_store = ProjectionSourceStore(
        sessions, cursor_signing_key=b"projection-source-postgres-key32", clock=lambda: case.now[0]
    )
    if kind == "historical":
        saved = await history.capture(case.principal, account, request=selection(None))
        pin = ProjectionSourcePin(subject_id=saved.id, content_digest=saved.input_digest)
    else:
        raw = await ingest(case, key="raw-price")
        # Real raw-close history is explicitly unsupported before its observations are read.
        with sessions() as session, pytest.raises(ProjectionStorageError):
            source_store.resolve_calibration(
                session,
                auth,
                (
                    ProjectionSourcePin(
                        subject_id=raw.id, content_digest=source_snapshot_digest(raw)
                    ),
                ),
                use=SourceUse.STORE,
                now=case.now[0],
            )
        await case.service.configure_source_provider(
            case.principal,
            SourceProviderRegistration(
                id=case.series.provider_id,
                key="synthetic-source",
                name="Synthetic source",
                adapter_version="synthetic-v1",
                configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
                synthetic=True,
                capabilities=(SourceCapability.PRICE_HISTORY, SourceCapability.BENCHMARK_SERIES),
                supported_price_bases=(PriceBasis.RAW_CLOSE, PriceBasis.TOTAL_RETURN),
            ),
            idempotency_key="projection-total-return-provider",
            correlation_id="projection-source-test",
        )
        series = replace(case.series, id=str(uuid4()), basis=PriceBasis.TOTAL_RETURN)
        if kind == "benchmark":
            series = replace(
                series,
                kind=SourceSeriesKind.BENCHMARK_LEVEL,
                provider_key="synthetic-benchmark",
                mapping_id=None,
                instrument_id=None,
                listing_id=None,
            )
        await case.service.register_source_series(
            case.principal,
            series,
            idempotency_key="projection-total-return-series",
            correlation_id="projection-source-test",
        )
        if kind == "price":
            selected = replace(
                case,
                series=series,
                request=replace(case.request, series=series),
                pages=tuple(replace(page, series=series) for page in case.pages),
            )
            saved_source: PriceSnapshot | BenchmarkSnapshot = await ingest(
                selected, key="projection-price"
            )
        else:
            request = BenchmarkSeriesRequest(
                series=series, period=case.request.period, source_cutoff_at=case.now[0]
            )
            pages = tuple(
                BenchmarkSeriesPage(
                    series=series,
                    provenance=page.provenance,
                    period=page.period,
                    coverage=page.coverage,
                    observations=tuple(
                        BenchmarkObservation(
                            session_date=o.session_date,
                            effective_at=o.effective_at,
                            level=o.value,
                            state=o.state,
                        )
                        for o in page.observations
                    ),
                    continuation=page.continuation,
                )
                for page in case.pages
            )
            saved_source = await case.service.ingest_benchmark_series(
                case.principal,
                request,
                pages,
                idempotency_key="projection-benchmark",
                correlation_id="projection-source-test",
            )
        pin = ProjectionSourcePin(
            subject_id=saved_source.id, content_digest=source_snapshot_digest(saved_source)
        )
    with sessions() as session:
        copied = source_store.capture(session, auth, (pin,), retained_at=case.now[0])
        assert len(copied.sources) == 1
        original = copied.sources[0]
        proof = json.loads(original.canonical_proof)
        assert original.header.subject_id == UUID(pin.subject_id)
        assert original.header.content_digest == pin.content_digest
        assert proof["source_kind"] == (
            "historical_input" if kind == "historical" else kind + "_total_return"
        )
        if kind == "historical":
            from trading212_domain.historical_serialization import historical_input_from_json

            assert historical_input_from_json(proof["canonical_input"]) == saved.input
            assert original.header.license_version_ids == ()
        else:
            assert len(proof["original_observations"]) == len(saved_source.observations) == 3
            assert proof["snapshot"]["series"]["basis"] == "total_return"
            assert len(proof["calendar_sessions"]) == 3
            assert proof["licenses"][0]["id"] == case.license.id
            assert original.header.license_version_ids == (UUID(case.license.id),)
            # Advance the copy clock without changing any canonical original evidence.
            case.now[0] += timedelta(days=2)
            again = source_store.capture(session, auth, (pin,), retained_at=case.now[0])
            assert again.sources[0].canonical_proof == original.canonical_proof
            assert again.expires_at == copied.expires_at
    if kind != "historical":
        shortened = replace(
            case.license,
            id=str(uuid4()),
            version="projection-short-retention",
            effective_at=case.now[0],
            retention_days=1,
        )
        await case.service.register_source_license(
            case.principal,
            shortened,
            idempotency_key="projection-short-license",
            correlation_id="projection-source-test",
        )
        statements = []

        def observe(
            connection: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            many: bool,
        ) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", observe)
        try:
            with sessions() as session, pytest.raises(ProjectionStorageError):
                source_store.capture(session, auth, (pin,), retained_at=case.now[0])
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert not any(
            "price_observations.value" in sql
            or "benchmark_observations.level" in sql
            or "canonical_input" in sql
            for sql in statements
        )


def test_production_capture_persists_fixed_input_and_all_normalized_rows(
    projection_definition_case: ProjectionDefinitionCase, database_engine: Engine
) -> None:
    from datetime import timedelta
    from hashlib import sha256
    from uuid import uuid4

    from sqlalchemy import func, select, text
    from trading212_persistence.premium_models import (
        PremiumAuditModel,
        PremiumJobModel,
        PremiumOutboxModel,
        PremiumRunModel,
    )
    from trading212_persistence.projection_models import (
        ProjectionCalendarBoundaryModel,
        ProjectionInputModel,
    )
    from trading212_persistence.report_models import ApplicationCommandIdentityModel

    from tests.integration.test_projection_definitions_postgres import finish

    c = projection_definition_case
    previous = queued_projection(c)
    store = ProjectionInputStore(
        sessionmaker(database_engine),
        cursor_signing_key=b"projection-source-postgres-key32",
        clock=lambda: c.now,
    )
    captured = store.capture(c.session, c.auth, previous.plan.selection)
    store.reserve_run_capacity(c.session, c.auth)
    identifier, command_id = uuid4(), uuid4()
    common = {"owner_id": c.auth.owner_id, "account_id": c.auth.account_id, "created_at": c.now}
    command = ApplicationCommandIdentityModel(
        id=command_id,
        **common,
        command="projection.run.create.v1",
        idempotency_key=str(uuid4()),
        command_digest=sha256(captured.stored.canonical_capture).hexdigest(),
        premium_resource_id=identifier,
        premium_actor_id=c.auth.principal_id,
        premium_correlation_id="projection-capture-test",
        report_job_id=None,
        export_job_id=None,
    )
    c.session.add(command)
    c.session.flush()
    c.session.add(PremiumAuditModel(id=uuid4(), **common, command_id=command_id, kind="created"))
    root = PremiumRunModel(
        id=identifier,
        **common,
        kind="projection",
        command_id=command_id,
        actor_principal_id=c.auth.principal_id,
        input_digest=captured.input_digest,
        expires_at=min(captured.expires_at, c.now + timedelta(days=1)),
        method_version="1.0.0",
        schema_version="1.0.0",
        numerical_profile="premium_decimal96_q18_v1",
        reserved_bytes=33554432,
        retained_bytes=0,
    )
    c.session.add(root)
    c.session.flush()
    actual = store.persist_capture(c.session, c.auth, root, captured)
    job = PremiumJobModel(id=uuid4(), **common, run_id=root.id, state="queued", consumer_attempts=0)
    c.session.add(job)
    c.session.flush()
    c.session.add(
        PremiumOutboxModel(
            id=uuid4(),
            **common,
            job_id=job.id,
            task_name="projections.calculate.v1",
            state="pending",
            publication_attempts=0,
            available_at=c.now,
        )
    )
    finish(c.session)
    assert actual.sealed and actual.capture_digest == captured.input_digest
    assert actual.numerical_input_digest == captured.plan.numerical_input_digest
    assert (
        c.session.scalar(
            select(func.count())
            .select_from(ProjectionCalendarBoundaryModel)
            .where(ProjectionCalendarBoundaryModel.run_id == root.id)
        )
        == captured.plan.selection.months + 1
    )
    assert (
        c.session.scalar(
            select(func.count())
            .select_from(ProjectionInputModel)
            .where(ProjectionInputModel.run_id == root.id)
        )
        == 1
    )
    measured = c.session.scalar(text("SELECT projection_storage_bytes(:run)"), {"run": root.id})
    assert isinstance(measured, int)
    # The active reservation covers actual bytes; only a terminal job converts the charge.
    assert root.retained_bytes == 0
    assert 0 < measured <= root.reserved_bytes == 33554432
    assert store.read_retained_input(c.session, c.auth, root.id).stored == captured.stored
