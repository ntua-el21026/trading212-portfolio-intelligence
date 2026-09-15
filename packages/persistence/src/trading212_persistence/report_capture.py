"""One transaction captures fixed canonical report inputs before durable dispatch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker
from trading212_application.reports import ReportCaptureSink
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_schema import report_tables
from trading212_domain.report_v3 import (
    ReportCaptureContract,
    ReportSelectionContract,
    ReportSelectionV3,
    selected_risk_run_id,
    selected_scenario_run_id,
)
from trading212_domain.sources import SourceUse

from .report_authorization import ReportAuthorization
from .report_builder import ReportBuilder
from .report_capture_alerts import capture_alerts
from .report_capture_company import prepare_company_copy
from .report_capture_planning import capture_planning
from .report_capture_portfolio import capture_portfolio, selected_snapshot
from .report_capture_quality import capture_quality, capture_quality_tables
from .risk_inputs import RiskPreflight


class PostgresReportCapture:
    def __init__(
        self,
        session: Session,
        authorization: ReportAuthorization,
        *,
        source_use: r.ReportSourceUse,
        risk_preflight: RiskPreflight | None = None,
        sessions: sessionmaker[Session],
        clock: Callable[[], datetime],
        cursor_signing_key: bytes,
    ) -> None:
        self._session, self._authorization, self._source_use = session, authorization, source_use
        self._sessions, self._clock, self._cursor_key = sessions, clock, cursor_signing_key
        self._risk_preflight = risk_preflight

    def capture_report(
        self,
        selection: r.ReportSelection | ReportSelectionV3,
        *,
        sink: ReportCaptureSink,
    ) -> ReportCaptureContract:
        if self._source_use is not r.ReportSourceUse.REPORT:
            fail_validation("The report source-use contract does not match.", field="source_use")
        return self._capture(selection, sink=sink)

    def capture_export(
        self,
        selection: r.ExportSelection,
        *,
        sink: ReportCaptureSink,
    ) -> r.ReportCaptureSummary:
        if self._source_use is not r.ReportSourceUse.EXPORT:
            fail_validation(
                "The export dataset or source-use contract is unavailable.", field="dataset"
            )
        result = self._capture(selection, sink=sink)
        if not isinstance(result, r.ReportCaptureSummary):
            fail_validation("The export document profile differs.", field="profile_version")
        return result

    def _capture(
        self,
        selection: ReportSelectionContract,
        *,
        sink: ReportCaptureSink,
    ) -> ReportCaptureContract:
        from .report_capture_historical import capture_historical
        from .report_capture_xray import capture_xray

        if selection.account_id != self._authorization.account_id:
            fail_validation("Report account binding does not match.", field="account_id")
        snapshot = selected_snapshot(
            self._session, self._authorization, selection, now=self._clock()
        )
        builder = ReportBuilder(
            selection,
            owner_id=self._authorization.owner_id,
            valuation_at=snapshot.valuation_at,
            sink=sink,
        )
        capture_portfolio(builder, self._session, snapshot)
        capture_quality(builder, self._session, snapshot)
        company = prepare_company_copy(
            builder,
            self._session,
            self._authorization,
            sessions=self._sessions,
            clock=self._clock,
            cursor_signing_key=self._cursor_key,
            source_use=SourceUse(self._source_use.value),
        )
        capture_planning(
            builder,
            self._session,
            self._authorization,
            sessions=self._sessions,
            clock=self._clock,
            cursor_signing_key=self._cursor_key,
            company=company,
        )
        capture_historical(
            builder,
            self._session,
            self._authorization,
            sessions=self._sessions,
            clock=self._clock,
            cursor_signing_key=self._cursor_key,
            source_use=SourceUse(self._source_use.value),
        )
        if company is None:
            capture_xray(
                builder,
                self._session,
                self._authorization,
                sessions=self._sessions,
                clock=self._clock,
                cursor_signing_key=self._cursor_key,
                source_use=SourceUse(self._source_use.value),
            )
        if selected_risk_run_id(selection) is not None:
            from .report_capture_risk_store import capture_risk

            builder.premium_binding = capture_risk(
                builder,
                self._session,
                self._authorization,
                sessions=self._sessions,
                clock=self._clock,
                cursor_signing_key=self._cursor_key,
                preflight=self._risk_preflight,
            )
        if selected_scenario_run_id(selection) is not None:
            from .report_capture_scenario_store import capture_scenario

            builder.premium_binding = capture_scenario(
                builder,
                self._session,
                self._authorization,
                sessions=self._sessions,
                clock=self._clock,
                cursor_signing_key=self._cursor_key,
            )
        capture_alerts(builder, self._session, self._authorization, clock=self._clock)
        capture_quality_tables(builder)
        builder.complete_proof_tables()
        if set(builder.descriptors) != set(report_tables(selection)) | builder.proof_table_keys:
            fail_validation("The report is missing a required canonical table.", field="tables")
        self._authorization.check(self._session, now=self._clock())
        return builder.finish()
