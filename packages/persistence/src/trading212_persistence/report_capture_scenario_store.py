"""Selected scenario report capture with current copy rights before any private decode."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as historical_app
from trading212_application import reports as app
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_v3 import (
    ReportScenarioRunBinding,
    ReportScenarioRunSelection,
    ReportSelectionV3,
)
from trading212_domain.sources import SourceUse

from .historical_service import PostgresHistoricalService
from .premium_models import (
    PremiumJobModel,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_scenario import (
    ScenarioReportMetadata,
    project_scenario,
    scenario_report_binding,
    scenario_report_context,
)
from .report_capture_scenario_sources import (
    capture_scenario_history_sources,
    capture_scenario_sensitivity_sources,
    capture_scenario_xray_sources,
)
from .scenario_models import ScenarioResultModel, ScenarioRunModel, ScenarioVersionModel
from .scenario_result_store import ScenarioResultStore
from .scenario_source_store import ScenarioCopySources
from .scenario_store_types import ScenarioStorageError, ScenarioStorageErrorCode
from .xray_service import PostgresXrayService


class ScenarioReportStore(ScenarioResultStore):
    """Nested retained-result rechecks retain the report-copy permission and 256-license cap."""

    def copy_authority(
        self, *, retained_at: datetime | None = None, required_copy_use: SourceUse | None = None
    ) -> ScenarioCopySources:
        return super().copy_authority(retained_at=retained_at, required_copy_use=SourceUse.REPORT)


def authorize_scenario_report_metadata(
    session: Session, auth: ReportAuthorization, run_id: UUID, *, now: datetime
) -> tuple[PremiumRunModel, ScenarioRunModel, PremiumJobModel, ScenarioResultModel]:
    """Only permanent owned metadata; excludes deferred input/result/coefficient payloads."""
    auth.check(session, now=now)
    root = session.scalar(
        select(PremiumRunModel).where(
            PremiumRunModel.id == run_id,
            PremiumRunModel.owner_id == auth.owner_id,
            PremiumRunModel.account_id == auth.account_id,
        )
    )
    if root is None or root.kind != "scenario":
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    run = session.scalar(
        select(ScenarioRunModel).where(
            ScenarioRunModel.id == run_id,
            ScenarioRunModel.owner_id == auth.owner_id,
            ScenarioRunModel.account_id == auth.account_id,
        )
    )
    job = session.scalar(
        select(PremiumJobModel).where(
            PremiumJobModel.run_id == run_id,
            PremiumJobModel.owner_id == auth.owner_id,
            PremiumJobModel.account_id == auth.account_id,
        )
    )
    result = session.scalar(
        select(ScenarioResultModel).where(
            ScenarioResultModel.run_id == run_id,
            ScenarioResultModel.owner_id == auth.owner_id,
            ScenarioResultModel.account_id == auth.account_id,
        )
    )
    if root.expires_at <= now or session.scalar(
        select(PremiumRetentionModel.id).where(PremiumRetentionModel.run_id == run_id)
    ):
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    if (
        run is None
        or job is None
        or result is None
        or not run.sealed
        or not result.sealed
        or job.state != "succeeded"
        or job.completed_at is None
    ):
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    return root, run, job, result


def capture_scenario(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
) -> ReportScenarioRunBinding:
    """Caller holds shared owner locks and seals the typed premium dependency atomically."""
    from trading212_analytics.scenario_replay import resolve_scenario_replay

    selection = builder.selection
    if not isinstance(selection, ReportSelectionV3) or not isinstance(
        selection.premium_run, ReportScenarioRunSelection
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    root, run, job, row = authorize_scenario_report_metadata(
        session, authorization, selection.premium_run.run_id, now=clock()
    )
    if (
        run.portfolio_snapshot_id != selection.snapshot_id
        or run.reporting_currency != selection.reporting_currency.value
        or run.source_cutoff_at != selection.source_cutoff_at
        or (
            run.historical_input_id is not None
            and (
                run.replay_start_date != selection.start_date
                or run.replay_end_date != selection.end_date
            )
        )
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    identifiers = tuple(
        session.scalars(
            select(PremiumRunLicenseModel.license_version_id)
            .where(
                PremiumRunLicenseModel.run_id == root.id,
                PremiumRunLicenseModel.owner_id == authorization.owner_id,
                PremiumRunLicenseModel.account_id == authorization.account_id,
            )
            .order_by(PremiumRunLicenseModel.license_version_id)
            .limit(257)
        )
    )
    if len(identifiers) > 256:
        raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
    store = ScenarioReportStore(
        sessions,
        cursor_signing_key=cursor_signing_key,
        clock=clock,
        replay_resolver=resolve_scenario_replay,
    )
    try:
        # The subclass carries REPORT through every transitive current/pinned source
        # check and repeated retained read, before any deferred private payload SELECT.
        execution = store.read_retained_input(
            session, authorization, root.id, required_copy_use=SourceUse.REPORT
        )
        value = store.read_result(session, authorization, root, execution)
        version = session.scalar(
            select(ScenarioVersionModel).where(
                ScenarioVersionModel.id == run.definition_version_id,
                ScenarioVersionModel.owner_id == authorization.owner_id,
                ScenarioVersionModel.account_id == authorization.account_id,
            )
        )
        if (
            version is None
            or version.content_digest != value.pins.scenario_version_digest
            or job.completed_at is None
        ):
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        metadata = ScenarioReportMetadata(
            run_id=root.id,
            result_id=row.id,
            result_digest=row.content_digest,
            scenario_version_number=version.version_number,
            created_at=root.created_at,
            completed_at=job.completed_at,
            expires_at=root.expires_at,
        )
        context = scenario_report_context(value, metadata)
        builder.add_context(context)
        sources = store.copy_authority(retained_at=root.created_at)
        for identifier in identifiers:
            sources._permit(session, authorization.owner_id, identifier, SourceUse.REPORT)
        capture_scenario_sensitivity_sources(builder, context, execution, session, sources)
        xray = PostgresXrayService(
            sessions=sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
            required_copy_use=SourceUse.REPORT,
        )
        capture_scenario_xray_sources(builder, context, execution, xray, session)
        project_scenario(builder, value, execution, metadata)
        history = PostgresHistoricalService(
            sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
            required_copy_use=SourceUse.REPORT,
        )
        capture_scenario_history_sources(builder, context, value, execution, history, session)
        # All newly shortened original/current lifetimes must still permit the final copy.
        store._finish_result_authority(session, authorization, root)
        authorize_scenario_report_metadata(session, authorization, root.id, now=clock())
        builder.limit_copy_expiry(min(root.expires_at, sources.copy_deadline))
        return scenario_report_binding(value, execution, metadata)
    except ScenarioStorageError as error:
        mapping = {
            ScenarioStorageErrorCode.INPUT_BOUND_EXCEEDED: (
                app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
            ),
            ScenarioStorageErrorCode.ACCESS_DENIED: app.ReportServiceErrorCode.ACCESS_DENIED,
            ScenarioStorageErrorCode.SOURCE_UNAVAILABLE: app.ReportServiceErrorCode.ACCESS_DENIED,
            ScenarioStorageErrorCode.RUN_EXPIRED: app.ReportServiceErrorCode.ARTIFACT_EXPIRED,
            ScenarioStorageErrorCode.NOT_FOUND: app.ReportServiceErrorCode.NOT_FOUND,
        }
        raise report_error(
            mapping.get(error.code, app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        ) from None
    except DomainError as error:
        code = (
            app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
            if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
            else app.ReportServiceErrorCode.REPORT_UNAVAILABLE
        )
        raise report_error(code) from None
    except (
        source_app.SourceServiceError,
        xray_app.XrayServiceError,
        historical_app.HistoricalServiceError,
    ):
        raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED) from None
