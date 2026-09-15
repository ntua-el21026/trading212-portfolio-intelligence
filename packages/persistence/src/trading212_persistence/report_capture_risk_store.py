"""Capture one explicitly selected retained risk run in the report transaction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_application import risk as risk_app
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_domain import reports as r
from trading212_domain.report_v3 import (
    ReportHistoricalInputBinding,
    ReportRiskRunBinding,
    ReportSelectionV3,
    ReportXrayRunBinding,
    selected_risk_run_id,
)
from trading212_domain.sources import SourceUse
from trading212_domain.xray_codec import decode_xray_input

from .historical_service import PostgresHistoricalService
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_risk import RiskReportMetadata, project_risk
from .report_capture_risk_sources import capture_risk_history_sources, capture_risk_xray_sources
from .report_premium_sources import authorize_risk_report_metadata
from .risk_inputs import RiskPreflight
from .risk_models import RiskVersionModel
from .risk_service import PostgresRiskService, verify_risk_execution
from .risk_storage import RiskIntegrityError, verify_risk_result
from .xray_service import PostgresXrayService


def capture_risk(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
    preflight: RiskPreflight | None,
) -> ReportRiskRunBinding | None:
    selection = builder.selection
    selected_run = selected_risk_run_id(selection)
    if selected_run is None:
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    if preflight is None:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    root, run, job, row = authorize_risk_report_metadata(
        session, authorization, selected_run, now=clock()
    )
    # Reject a mismatched request from normalized headers before any private decode.
    if (
        run.portfolio_snapshot_id != selection.snapshot_id
        or run.reporting_currency != selection.reporting_currency.value
        or run.source_cutoff_at != selection.source_cutoff_at
        or run.window_start_at != datetime.combine(selection.start_date, time.min, tzinfo=UTC)
        or run.window_end_at
        != datetime.combine(selection.end_date + timedelta(days=1), time.min, tzinfo=UTC)
        or job.completed_at is None
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    service = PostgresRiskService(
        sessions, clock=clock, cursor_signing_key=cursor_signing_key, preflight=preflight
    )
    version = session.scalar(
        select(RiskVersionModel).where(
            RiskVersionModel.owner_id == authorization.owner_id,
            RiskVersionModel.account_id == authorization.account_id,
            RiskVersionModel.id == run.definition_version_id,
        )
    )
    if version is None:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    try:
        execution = service._load_inputs(
            session,
            authorization,
            service._retained_command(session, run),
            preflight,
            retained_at=root.created_at,
            required_copy_use=SourceUse.REPORT,
        )
        if execution.input_digest != root.input_digest:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        value = verify_risk_result(session, run, row)
        verify_risk_execution(value, execution)
        xray_input = None
        xray_handle = None
        xray_service = PostgresXrayService(
            sessions=sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
            required_copy_use=SourceUse.REPORT,
        )
        if run.xray_run_id is not None:
            principal = authorization.as_principal(now=clock())
            xray_handle = xray_service._authorize_xray_run(
                session, principal, authorization.account_id, run.xray_run_id
            )
            _, capture, _ = xray_service._authorized_rows(
                session, principal, authorization.account_id, run.xray_run_id
            )
            xray_input = decode_xray_input(capture.canonical_input)
        contexts = project_risk(
            builder,
            value,
            execution,
            RiskReportMetadata(
                run_id=root.id,
                result_id=row.id,
                result_digest=row.content_digest,
                definition_id=version.definition_id,
                definition_version_id=version.id,
                definition_version_number=version.version_number,
                definition_digest=version.content_digest,
                portfolio_snapshot_id=run.portfolio_snapshot_id,
                historical_input_snapshot_id=run.historical_input_id,
                benchmark_version_id=run.benchmark_version_id,
                xray_run_id=run.xray_run_id,
                xray_input_id=None if xray_handle is None else xray_handle.input_id,
                xray_input_digest=None if execution.xray is None else execution.xray.input_digest,
                created_at=root.created_at,
                completed_at=job.completed_at,
                expires_at=root.expires_at,
            ),
        )
        historical_service = PostgresHistoricalService(
            sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
            required_copy_use=SourceUse.REPORT,
        )
        capture_risk_history_sources(
            builder, contexts, value, execution, historical_service, session
        )
        if xray_input is not None and xray_handle is not None and execution.xray is not None:
            capture_risk_xray_sources(
                builder,
                contexts,
                xray_input,
                execution.xray,
                xray_service,
                session,
                run_id=xray_handle.run_id,
                input_id=xray_handle.input_id,
            )
        authorize_risk_report_metadata(session, authorization, root.id, now=clock())
        if isinstance(selection, ReportSelectionV3):
            snapshots = tuple(
                pin
                for pin in builder.bindings
                if pin.family is r.ReportFamily.SNAPSHOT
                and pin.role is r.ReportInputRole.SNAPSHOT
                and pin.subject_id == selection.snapshot_id
            )
            if len(snapshots) != 1:
                raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
            return ReportRiskRunBinding(
                run_id=root.id,
                result_id=row.id,
                input_digest=root.input_digest,
                result_digest=row.content_digest,
                owner_id=authorization.owner_id,
                account_id=authorization.account_id,
                snapshot_id=selection.snapshot_id,
                snapshot_digest=snapshots[0].content_digest,
                reporting_currency=selection.reporting_currency,
                source_cutoff_at=selection.source_cutoff_at,
                valuation_at=builder.valuation_at,
                created_at=root.created_at,
                completed_at=job.completed_at,
                expires_at=root.expires_at,
                definition_id=version.definition_id,
                definition_version_id=version.id,
                definition_digest=version.content_digest,
                start_date=selection.start_date,
                end_date=selection.end_date,
                historical=ReportHistoricalInputBinding(
                    input_snapshot_id=run.historical_input_id,
                    input_digest=value.history.historical_input_digest,
                ),
                xray=ReportXrayRunBinding(
                    run_id=xray_handle.run_id,
                    input_id=xray_handle.input_id,
                    input_digest=execution.xray.input_digest,
                    result_digest=execution.xray.content_digest,
                )
                if xray_handle is not None and execution.xray is not None
                else None,
                benchmark_version_id=run.benchmark_version_id,
            )
        return None
    except RiskIntegrityError:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE) from None
    except risk_app.RiskServiceError as error:
        code = (
            app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
            if error.code is risk_app.RiskErrorCode.INPUT_BOUND_EXCEEDED
            else app.ReportServiceErrorCode.ACCESS_DENIED
            if error.code
            in (risk_app.RiskErrorCode.ACCESS_DENIED, risk_app.RiskErrorCode.SOURCE_UNAVAILABLE)
            else app.ReportServiceErrorCode.ARTIFACT_EXPIRED
            if error.code is risk_app.RiskErrorCode.RUN_EXPIRED
            else app.ReportServiceErrorCode.REPORT_UNAVAILABLE
        )
        raise report_error(code) from None
    except xray_app.XrayServiceError:
        raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED) from None
    except source_app.SourceServiceError:
        # A source may expire between input verification and the final copy traversal.
        raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED) from None
