"""Current premium copy authority and version isolation precede private payload reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from inspect import unwrap
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, func, select
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.risk_history import validate_risk_capacity
from trading212_application import reports as app
from trading212_application import risk as risk_app
from trading212_domain import reports as r
from trading212_domain.values import CurrencyCode
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_models import HistoricalInputModel
from trading212_persistence.models import OwnerModel, PortfolioSnapshotModel, PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    PrincipalScopeGrantModel,
    ReportDefinitionModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from trading212_persistence.report_service import PostgresReportService
from trading212_security.principals import Principal, Scope
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.test_historical_postgres import historical_database as _historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as _seeded_history
from tests.integration.test_premium_report_retention_postgres import report_policy
from tests.integration.test_risk_retention_postgres import published
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case

pytestmark = pytest.mark.integration
historical_database = pytest.fixture(scope="function")(unwrap(_historical_database))
seeded_history = pytest.fixture(scope="function")(unwrap(_seeded_history))


async def prepare(
    case: RunCase, *, target_version_id: str | None = None
) -> tuple[PostgresReportService, r.ReportSelection, risk_app.RiskRunView]:
    with case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == case.principal.issuer,
                PrincipalModel.subject == case.principal.subject,
            )
        )
        assert identity is not None
        principal_id = str(identity.id)
        provision_principal_scopes(
            session, principal_id=identity.id, scopes=frozenset(Scope), now=NOW - timedelta(days=1)
        )
    case.principal = replace(case.principal, principal_id=principal_id, scopes=frozenset(Scope))
    if target_version_id is not None:
        history = HistoricalCaptureStore(
            case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
        )
        original = await history.load(
            case.principal, str(case.command.historical_input_snapshot_id)
        )
        pinned = await history.capture(
            case.principal,
            str(case.command.account_id),
            request=replace(
                original.input.selection,
                target_version_id=target_version_id,
                grouping_policy="explicit_comparison",
            ),
        )
        case.command = replace(
            case.command, historical_input_snapshot_id=UUID(pinned.id), idempotency_key=uuid4().hex
        )
        with case.sessions() as session:
            assert session.scalar(
                select(HistoricalInputModel.target_version_id).where(
                    HistoricalInputModel.id == UUID(pinned.id)
                )
            ) == UUID(target_version_id)
    run = await published(case)
    assert run.result is not None
    now = datetime.now(UTC)
    case.principal = replace(
        case.principal,
        authenticated_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=2),
    )
    service = PostgresReportService(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        contract_version=2,
        risk_preflight=validate_risk_capacity,
    )
    selection = r.ReportSelection(
        account_id=case.command.account_id,
        snapshot_id=case.command.portfolio_snapshot_id,
        reporting_currency=case.command.window.reporting_currency,
        start_date=case.command.window.start_date,
        end_date=case.command.window.end_date,
        source_cutoff_at=case.command.window.source_cutoff_at,
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.RISK,
        ),
        formats=(r.ReportFormat.JSON,),
        risk_run_id=run.id,
    )
    return service, selection, run


def report_counts(case: RunCase) -> tuple[int, ...]:
    with case.sessions() as session:
        return tuple(
            session.execute(select(func.count()).select_from(model)).scalar_one()
            for model in (
                ReportInputSnapshotModel,
                ReportInputChunkModel,
                ReportInputPremiumDependencyModel,
                ReportDefinitionModel,
                ReportJobModel,
                ReportDispatchOutboxModel,
                ApplicationCommandIdentityModel,
            )
        )


@contextmanager
def no_private_reads(case: RunCase) -> Iterator[None]:
    """Reject the payload SELECT itself, in addition to checking decoder call sites."""
    with case.sessions() as session:
        engine = session.get_bind()
    assert isinstance(engine, Engine)
    columns = (
        "historical_input_snapshots.canonical_input",
        "risk_results.canonical_result",
        "report_input_snapshots.canonical_context",
        "report_input_snapshots.canonical_manifest",
        "report_input_chunks.payload",
        "report_manifests.payload",
        "report_artifacts.contents",
    )

    def before_read(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        sql = statement.replace('"', "").lower().lstrip()
        if sql.startswith("select"):
            assert not any(column in sql for column in columns), (
                "Private payload read before authorization"
            )

    event.listen(engine, "before_cursor_execute", before_read)
    try:
        with ExitStack() as stack:
            guards = [
                stack.enter_context(
                    patch(name, side_effect=AssertionError("Private decoder invoked"))
                )
                for name in (
                    "trading212_persistence.historical_capture.historical_input_from_json",
                    "trading212_persistence.risk_storage.risk_result_from_json",
                    "trading212_persistence.report_service.decode_report_manifest",
                    "trading212_application.reports.decode_report_pinned_context",
                )
            ]
            yield
            for guard in guards:
                guard.assert_not_called()
    finally:
        event.remove(engine, "before_cursor_execute", before_read)


def scope_grant(case: RunCase, scope: Scope, *, revoked: bool) -> None:
    with case.sessions() as session, session.begin():
        grant = session.get_one(
            PrincipalScopeGrantModel, (UUID(case.principal.principal_id), scope.value)
        )
        grant.revoked_at = datetime.now(UTC) - timedelta(seconds=1) if revoked else None


async def test_current_report_and_transitive_scope_revocation_precede_private_reads(
    run_case: RunCase,
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    case = run_case
    service, selection, run = await prepare(
        case, target_version_id=seeded_history[1]["annual_target_version_id"]
    )
    command = app.GenerateReportCommand(selection=selection, idempotency_key=uuid4().hex)
    queued = await service.generate_report(case.principal, command)
    assert queued.state is r.ReportJobState.QUEUED and queued.context is not None
    expected = report_counts(case)
    for restriction in ("report", Scope.ACTIVITY_READ, Scope.TARGETS_READ):
        if restriction == "report":
            report_policy(case, run, "denied")
        else:
            assert isinstance(restriction, Scope)
            scope_grant(case, restriction, revoked=True)
        with no_private_reads(case):
            for operation in (
                lambda: service.generate_report(
                    case.principal, replace(command, idempotency_key=uuid4().hex)
                ),
                lambda: service.generate_report(case.principal, command),
                lambda: service.get_report_status(
                    case.principal, selection.account_id, queued.job_id
                ),
                lambda: service.get_report_manifest(
                    case.principal, selection.account_id, queued.job_id
                ),
            ):
                with pytest.raises(app.ReportServiceError) as failure:
                    await operation()
                assert failure.value.code is app.ReportServiceErrorCode.ACCESS_DENIED, restriction
                assert report_counts(case) == expected
        if restriction == "report":
            report_policy(case, run, "allowed")
        else:
            assert isinstance(restriction, Scope)
            scope_grant(case, restriction, revoked=False)
    assert await service.generate_report(case.principal, command) == queued


def foreign_principal(case: RunCase) -> Principal:
    now = datetime.now(UTC)
    owner, identifier = uuid4(), uuid4()
    issuer, subject = "synthetic-premium-privacy", uuid4().hex
    with case.sessions() as session, session.begin():
        session.add(OwnerModel(id=owner, display_name="Synthetic foreign report owner"))
        session.flush()
        session.add(
            PrincipalModel(
                id=identifier,
                owner_id=owner,
                issuer=issuer,
                subject=subject,
                status="active",
                last_authenticated_at=now,
            )
        )
        session.flush()
        provision_principal_scopes(
            session, principal_id=identifier, scopes=frozenset(Scope), now=now - timedelta(days=1)
        )
    return Principal(
        principal_id=str(identifier),
        owner_id=str(owner),
        issuer=issuer,
        subject=subject,
        scopes=frozenset(Scope),
        authenticated_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=2),
    )


async def test_selected_risk_scope_and_pins_reject_without_durable_report_copies(
    run_case: RunCase,
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    case = run_case
    service, selection, _run = await prepare(case)
    other_account = UUID(seeded_history[1]["point_in_time_account_id"])
    with case.sessions() as session:
        other_snapshot = session.scalar(
            select(PortfolioSnapshotModel.id)
            .where(PortfolioSnapshotModel.broker_account_id == other_account)
            .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id)
            .limit(1)
        )
    assert other_snapshot is not None
    foreign = foreign_principal(case)
    expected = report_counts(case)
    mismatches = (
        ("foreign owner", foreign, selection, app.ReportServiceErrorCode.ACCESS_DENIED),
        (
            "other owned account",
            case.principal,
            replace(selection, account_id=other_account, snapshot_id=other_snapshot),
            app.ReportServiceErrorCode.NOT_FOUND,
        ),
        (
            "foreign snapshot",
            case.principal,
            replace(selection, snapshot_id=other_snapshot),
            app.ReportServiceErrorCode.NOT_FOUND,
        ),
        (
            "window start",
            case.principal,
            replace(selection, start_date=selection.start_date + timedelta(days=1)),
            app.ReportServiceErrorCode.VALIDATION_FAILED,
        ),
        (
            "window end",
            case.principal,
            replace(selection, end_date=selection.end_date - timedelta(days=1)),
            app.ReportServiceErrorCode.VALIDATION_FAILED,
        ),
        (
            "source cutoff",
            case.principal,
            replace(selection, source_cutoff_at=selection.source_cutoff_at + timedelta(seconds=1)),
            app.ReportServiceErrorCode.VALIDATION_FAILED,
        ),
        (
            "reporting currency",
            case.principal,
            replace(selection, reporting_currency=CurrencyCode("USD")),
            app.ReportServiceErrorCode.VALIDATION_FAILED,
        ),
        (
            "unknown run",
            case.principal,
            replace(selection, risk_run_id=uuid4()),
            app.ReportServiceErrorCode.NOT_FOUND,
        ),
    )
    with no_private_reads(case):
        for label, principal, invalid, code in mismatches:
            with pytest.raises(app.ReportServiceError) as failure:
                await service.generate_report(
                    principal,
                    app.GenerateReportCommand(selection=invalid, idempotency_key=uuid4().hex),
                )
            assert failure.value.code is code, label
            assert report_counts(case) == expected, label


async def test_v1_rejects_real_v2_identity_before_manifest_grant_content_or_replay(
    run_case: RunCase,
) -> None:
    case = run_case
    v2, selection, _run = await prepare(case)
    command = app.GenerateReportCommand(selection=selection, idempotency_key=uuid4().hex)
    queued = await v2.generate_report(case.principal, command)
    assert queued.context is not None and queued.context.profile_version == "report_sections_v2"
    v1 = PostgresReportService(case.sessions, cursor_signing_key=CURSOR_KEY)
    # No artifact is needed: collection version must reject before the artifact lookup.
    artifact_id = uuid4()
    expected = report_counts(case)
    with (
        no_private_reads(case),
        patch(
            "trading212_persistence.report_downloads.create_grant",
            side_effect=AssertionError("Grant handler entered"),
        ) as grant,
        patch(
            "trading212_persistence.report_downloads.download_artifact",
            side_effect=AssertionError("Content handler entered"),
        ) as content,
    ):
        for operation in (
            lambda: v1.get_report_status(case.principal, selection.account_id, queued.job_id),
            lambda: v1.get_report_manifest(case.principal, selection.account_id, queued.job_id),
            lambda: v1.create_report_download_grant(
                case.principal, selection.account_id, queued.job_id, artifact_id
            ),
            lambda: v1.download_report_artifact(
                case.principal,
                selection.account_id,
                queued.job_id,
                artifact_id,
                grant_token="synthetic-invalid-grant",
            ),
        ):
            with pytest.raises(app.ReportServiceError) as failure:
                await operation()
            assert failure.value.code is app.ReportServiceErrorCode.NOT_FOUND
        with pytest.raises(app.ReportServiceError) as failure:
            await v1.generate_report(case.principal, command)
        assert failure.value.code is app.ReportServiceErrorCode.VALIDATION_FAILED
        grant.assert_not_called()
        content.assert_not_called()
    assert report_counts(case) == expected
    assert await v2.generate_report(case.principal, command) == queued
