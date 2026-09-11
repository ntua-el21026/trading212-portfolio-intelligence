"""Actual licensed physical dependencies guard every durable alert payload boundary."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from trading212_application import alerts as app
from trading212_domain import alerts as d
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.reports import ReportSourceKind
from trading212_domain.sources import LicensePermission
from trading212_persistence.alert_authorization import authorize_alert_request
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertInputDependencyModel,
    AlertInputSnapshotModel,
    AlertRetentionWorkModel,
)
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.alert_sources import authorize_alert_sources
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.source_store import license_view
from trading212_persistence.xray_catalog_models import ConstituentSnapshotModel
from trading212_security.principals import AuthorizationError, Scope
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_alert_postgres import AlertCase, CaptureControl
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@pytest.fixture
def licensed_alert_case(xray_read_case: XrayReadCase) -> AlertCase:
    base = xray_read_case
    clock = [datetime.now(UTC)]
    with base.sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(base.principal.principal_id),
            scopes=frozenset(Scope),
            now=clock[0] - timedelta(seconds=1),
        )
        physical = session.scalar(
            select(ConstituentSnapshotModel)
            .where(ConstituentSnapshotModel.owner_id == UUID(base.principal.owner_id))
            .order_by(ConstituentSnapshotModel.id)
        )
        assert physical is not None
        license = session.get(ProviderLicenseVersionModel, physical.license_version_id)
        assert license is not None
        reference = d.AlertSourceReference(
            key="source.actual.constituents",
            kind=ReportSourceKind.CONSTITUENT_SNAPSHOT,
            subject_id=physical.id,
            content_digest=physical.content_digest,
            effective_at=physical.effective_at,
            first_observed_at=physical.first_observed_at,
            provider_id=physical.provider_id,
            license_version_id=physical.license_version_id,
            expires_at=physical.expires_at,
        )
        control = CaptureControl(references=(reference,), licenses=(license_view(license),))
    return AlertCase(
        base.engine,
        base.sessions,
        clock,
        control,
        replace(base.principal, scopes=frozenset(Scope)),
        PostgresAlertService(
            base.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: clock[0],
            capture_factory=lambda _s, _a: control,
        ),
        PostgresAlertJobStore(
            base.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: clock[0],
            capture_factory=lambda _s, _a: control,
        ),
        account_override=UUID(XRAY_ACCOUNT_ID),
    )


@pytest.mark.parametrize("permission", ("store", "display", "export"))
def test_actual_current_license_denial_precedes_alert_payload_decode(
    licensed_alert_case: AlertCase, permission: str
) -> None:
    async def run() -> None:
        case = licensed_alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="licensed-alert")
            is AlertExecutionState.COMPLETED
        )
        source = PostgresSourceService(sessions=case.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
        key = str(uuid4())
        denied = replace(
            xray_license(),
            id=key,
            version=key,
            effective_at=datetime.now(UTC),
            store=LicensePermission.DENIED if permission == "store" else LicensePermission.ALLOWED,
            display=LicensePermission.DENIED
            if permission == "display"
            else LicensePermission.ALLOWED,
            export=LicensePermission.DENIED
            if permission == "export"
            else LicensePermission.ALLOWED,
        )
        await source.register_source_license(
            case.principal,
            denied,
            idempotency_key=key,
            correlation_id="alert-source-denied",
        )
        case.clock[0] = datetime.now(UTC)
        selects: list[str] = []

        def observe(
            _c: object, _cursor: object, statement: str, _p: object, _context: object, _many: object
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(case.engine, "before_cursor_execute", observe)
        try:
            if permission == "export":
                with pytest.raises(AuthorizationError), case.sessions() as session, session.begin():
                    authorization = authorize_alert_request(
                        session, case.principal, account_id=case.account_id, now=case.clock[0]
                    )
                    authorize_alert_sources(
                        session,
                        authorization,
                        input_id=message.capture_id,
                        now=case.clock[0],
                        export=True,
                    )
            else:
                detail = await case.service.get_rule(
                    case.principal, rule.id, query=app.AlertRuleDetailQuery()
                )
                assert detail.latest_evaluation is not None
                assert (
                    detail.latest_evaluation.reproducibility
                    is app.AlertReproducibility.SOURCE_RESTRICTED
                )
                assert (
                    detail.latest_evaluation.result is None
                    and detail.latest_evaluation.source_references == ()
                )
        finally:
            event.remove(case.engine, "before_cursor_execute", observe)
        assert not any(
            "alert_input_snapshots.payload" in statement or "alert_evaluations.payload" in statement
            for statement in selects
        )

    asyncio.run(run())


def test_alert_physical_copies_are_removed_before_source_completion_with_one_shared_budget(
    licensed_alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = licensed_alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, message, consumer_id="source-expiry")
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            dependency = session.scalar(
                select(AlertInputDependencyModel).where(
                    AlertInputDependencyModel.input_id == message.capture_id
                )
            )
            assert (
                dependency is not None
                and dependency.kind == "constituent"
                and dependency.expires_at is not None
            )
            at = dependency.expires_at + timedelta(seconds=1)
        for _ in range(128):
            with case.sessions() as session, session.begin():
                budget = SourcePurgeBudget(
                    rows_inspected=64, rows_removed=64, bytes_inspected=8192, bytes_removed=8192
                )
                expire_source_payloads(session, at=at, limit=1, budget=budget)
                pending = session.scalar(
                    select(AlertRetentionWorkModel).where(
                        AlertRetentionWorkModel.input_id == message.capture_id
                    )
                )
                if pending is not None:
                    break
        assert pending is not None
        for _ in range(128):
            with case.sessions() as session, session.begin():
                budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
                expire_source_payloads(session, at=at, limit=1, budget=budget)
                assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
                capture = session.get(AlertInputSnapshotModel, message.capture_id)
                assert capture is not None
                done = capture.purged_at is not None
            if done:
                break
        assert done
        with case.sessions() as session:
            saved = session.get(AlertInputSnapshotModel, message.capture_id)
            work = session.scalar(
                select(AlertRetentionWorkModel).where(
                    AlertRetentionWorkModel.input_id == message.capture_id
                )
            )
            assert saved is not None and saved.payload is None
            assert work is not None and work.reason == "source" and work.completed_at is not None

    asyncio.run(run())


def test_invalid_license_and_physical_projections_never_admit_a_partial_job(
    licensed_alert_case: AlertCase,
) -> None:
    from trading212_persistence.alert_models import AlertEvaluationJobModel

    async def run() -> None:
        case = licensed_alert_case
        original = case.control.references[0]
        license = case.control.licenses[0]
        mutations = (
            (replace(original, provider_id=None), (license,)),
            (replace(original, license_version_id=None), (license,)),
            (original, ()),
            (replace(original, content_digest="0" * 64), (license,)),
        )
        rules = []
        for reference, licenses in mutations:
            case.control.references = (reference,)
            case.control.licenses = licenses
            rule = await case.active()
            rules.append(rule.id)
            if reference.provider_id is None or not licenses:
                with pytest.raises(DomainError) as invalid:
                    await case.store.admit_due_evaluations()
                assert invalid.value.code is ErrorCode.VALIDATION_FAILED
            else:
                result = await case.store.admit_due_evaluations()
                assert result.admitted == 0 and result.deferred
            with case.sessions() as session:
                assert (
                    session.scalar(
                        select(AlertEvaluationJobModel.id)
                        .where(AlertEvaluationJobModel.rule_id.in_(rules))
                        .limit(1)
                    )
                    is None
                )
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(AlertInputSnapshotModel.id)
                    .where(AlertInputSnapshotModel.owner_id == UUID(case.principal.owner_id))
                    .limit(1)
                )
                is None
            )

    asyncio.run(run())
