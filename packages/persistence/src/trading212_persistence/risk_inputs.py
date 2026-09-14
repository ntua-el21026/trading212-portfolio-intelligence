"""Authorized source-bound risk loading before decode, replay or durable publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session
from trading212_application import historical as historical_app
from trading212_application import risk as app
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_application.risk_jobs import (
    RiskExecutionInput,
    RiskJobInputError,
    risk_execution_bytes,
)
from trading212_domain.historical import HistoricalInput
from trading212_domain.risk import RiskDefinitionContent
from trading212_domain.risk_history import RiskAssetSource
from trading212_domain.sources import SourceLicense, SourceUse
from trading212_security.principals import Scope

from .historical_base import digest
from .historical_capture import HistoricalCaptureStore
from .historical_models import HistoricalInputModel
from .models import PortfolioSnapshotModel
from .report_authorization import ReportAuthorization
from .risk_definitions import RiskDefinitionStore, risk_error
from .risk_models import RiskRunModel, RiskVersionModel
from .source_models import SourceSnapshotFields
from .source_service import PostgresSourceService
from .xray_run_models import XrayInputDependencyModel
from .xray_run_store import _SOURCE_TARGETS, XrayRunStore

RiskPreflight = Callable[[HistoricalInput, RiskDefinitionContent, tuple[RiskAssetSource, ...]], int]


class RiskCopySources(PostgresSourceService):
    retention_deadline: datetime | None = None
    copy_created_at: datetime | None = None
    license_ids: set[UUID] | None = None

    def _permit(
        self, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> SourceLicense:
        license = super()._permit(session, owner, license_id, use)
        if self.license_ids is not None:
            self.license_ids.add(license_id)
            if len(self.license_ids) > 8192:
                raise risk_error(app.RiskErrorCode.INPUT_BOUND_EXCEEDED)
        super()._permit(session, owner, license_id, SourceUse.STORE)
        current = self._current_license(session, owner, UUID(license.provider_id))
        if current is None or current.retention_days is None or license.retention_days is None:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        deadline = (self.copy_created_at or self._now()) + timedelta(
            days=min(30, license.retention_days, current.retention_days)
        )
        if deadline <= self._now():
            raise risk_error(app.RiskErrorCode.RUN_EXPIRED)
        self.retention_deadline = min(self.retention_deadline or deadline, deadline)
        return license

    def _snapshot_permit(
        self, session: Session, row: SourceSnapshotFields, use: SourceUse = SourceUse.DISPLAY
    ) -> SourceLicense:
        license = super()._snapshot_permit(session, row, use)
        self.retention_deadline = min(self.retention_deadline or row.expires_at, row.expires_at)
        return license


class RiskCopyXray(XrayRunStore):
    copy_sources: RiskCopySources

    def _permit(
        self, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> SourceLicense:
        # Existing X-ray authorization invokes this before any source-reference decode.
        return self.copy_sources._permit(session, owner, license_id, use)


class RiskInputStore(RiskDefinitionStore):
    def _load_inputs(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: app.CreateRiskRun,
        preflight: RiskPreflight,
        *,
        retained_at: datetime | None = None,
        license_ids: set[UUID] | None = None,
    ) -> RiskExecutionInput:
        try:
            return self._load_authorized_inputs(
                session, auth, command, preflight, retained_at=retained_at, license_ids=license_ids
            )
        except RiskJobInputError:
            raise risk_error(app.RiskErrorCode.INPUT_BOUND_EXCEEDED) from None
        except (
            historical_app.HistoricalServiceError,
            source_app.SourceServiceError,
            xray_app.XrayServiceError,
        ):
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE) from None

    def _load_authorized_inputs(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: app.CreateRiskRun,
        preflight: RiskPreflight,
        *,
        retained_at: datetime | None = None,
        license_ids: set[UUID] | None = None,
    ) -> RiskExecutionInput:
        auth.check(session, now=self._now())
        version = self._owned(session, auth, RiskVersionModel, command.definition_version_id)
        definition = self._version_view(session, version).content
        # Select metadata first. The original historical ORM row includes a private byte payload.
        header = session.execute(
            select(
                HistoricalInputModel.id,
                HistoricalInputModel.target_version_id,
                HistoricalInputModel.benchmark_version_id,
                HistoricalInputModel.sealed,
            ).where(
                HistoricalInputModel.id == command.historical_input_snapshot_id,
                HistoricalInputModel.owner_id == auth.owner_id,
                HistoricalInputModel.broker_account_id == auth.account_id,
            )
        ).first()
        if header is None or not header.sealed:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        if header.target_version_id is not None:
            auth = replace(auth, required_scopes=auth.required_scopes | {Scope.TARGETS_READ})
            auth.check(session, now=self._now())
        sources = RiskCopySources(
            sessions=self._sessions, cursor_signing_key=self._cursor_key, clock=self._clock
        )
        sources.copy_created_at = retained_at or self._now()
        sources.license_ids = license_ids
        history_store = HistoricalCaptureStore(
            self._sessions, cursor_signing_key=self._cursor_key, clock=self._clock
        )
        history_store._sources = sources
        history_store._reauthorize(session, auth.owner_id, auth.account_id, input_id=header.id)
        row = session.scalar(
            select(HistoricalInputModel).where(
                HistoricalInputModel.id == header.id, HistoricalInputModel.owner_id == auth.owner_id
            )
        )
        if row is None:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        # Both permission traversals fail closed; the first precedes loading private bytes.
        capture = history_store._capture_view(session, auth.owner_id, row)
        historical = capture.input
        if (
            historical.selection.window != command.window
            or header.benchmark_version_id != command.benchmark_version_id
        ):
            raise risk_error(app.RiskErrorCode.CONFLICT)
        snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.id == command.portfolio_snapshot_id,
                PortfolioSnapshotModel.broker_account_id == auth.account_id,
            )
        )
        if snapshot is None or snapshot.valuation_at > command.window.source_cutoff_at:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        xray = None
        if command.xray_run_id is not None:
            store = RiskCopyXray(
                sessions=self._sessions, cursor_signing_key=self._cursor_key, clock=self._clock
            )
            store.copy_sources = sources
            handle = store._authorize_xray_run(
                session, auth.as_principal(now=self._now()), auth.account_id, command.xray_run_id
            )
            xray = store._load_xray_result(
                session, auth.as_principal(now=self._now()), auth.account_id, handle
            )
            if (
                xray.snapshot_id != snapshot.id
                or xray.reporting_currency != command.window.reporting_currency
                or xray.source_cutoff_at.value != command.window.source_cutoff_at
                or xray.valuation_at.value < command.window.end_at
            ):
                raise risk_error(app.RiskErrorCode.CONFLICT)
            dependencies = XrayInputDependencyModel
            expiries = session.scalars(
                union_all(
                    *(
                        select(func.min(model.expires_at))
                        .join(dependencies, getattr(dependencies, name) == model.id)
                        .where(
                            dependencies.input_id == handle.input_id,
                            dependencies.owner_id == auth.owner_id,
                            model.owner_id == auth.owner_id,
                        )
                        for name, model in _SOURCE_TARGETS.items()
                    )
                )
            ).all()
            for expiry in expiries:
                if expiry is not None:
                    sources.retention_deadline = min(sources.retention_deadline or expiry, expiry)
        preflight(historical, definition, command.assets)
        expiry = sources.retention_deadline or self._now() + timedelta(days=30)
        if expiry <= self._now():
            raise risk_error(app.RiskErrorCode.RUN_EXPIRED)
        input_digest = digest(
            (
                auth.account_id,
                version.id,
                version.content_digest,
                snapshot.id,
                capture.id,
                capture.input_digest,
                command.window,
                command.benchmark_version_id,
                command.assets,
                command.xray_run_id,
                None if xray is None else xray.content_digest,
                "1.0.0",
                "premium_decimal96_q18_v1",
            )
        )
        execution = RiskExecutionInput(
            historical=historical,
            definition=definition,
            assets=command.assets,
            xray=xray,
            input_digest=input_digest,
            expires_at=expiry,
        )
        risk_execution_bytes(execution)
        return execution

    def _retained_command(self, session: Session, run: RiskRunModel) -> app.CreateRiskRun:
        from .risk_models import RiskRunAssetModel

        # No canonical decode here. Dates and knowledge policy belong to the sealed capture.
        row = session.execute(
            select(
                HistoricalInputModel.period_start,
                HistoricalInputModel.period_end,
                HistoricalInputModel.source_cutoff_at,
                HistoricalInputModel.reporting_currency,
                HistoricalInputModel.knowledge_policy,
            ).where(
                HistoricalInputModel.id == run.historical_input_id,
                HistoricalInputModel.owner_id == run.owner_id,
                HistoricalInputModel.broker_account_id == run.account_id,
            )
        ).one_or_none()
        if row is None:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        from trading212_domain.historical import HistoricalWindow, KnowledgePolicy
        from trading212_domain.values import CurrencyCode

        assets = tuple(
            RiskAssetSource(
                instrument_id=str(asset.instrument_id), series_id=str(asset.source_series_id)
            )
            for asset in session.scalars(
                select(RiskRunAssetModel)
                .where(
                    RiskRunAssetModel.run_id == run.id,
                    RiskRunAssetModel.owner_id == run.owner_id,
                    RiskRunAssetModel.account_id == run.account_id,
                )
                .order_by(RiskRunAssetModel.ordinal)
                .limit(33)
            )
        )
        return app.CreateRiskRun(
            account_id=run.account_id,
            definition_version_id=run.definition_version_id,
            portfolio_snapshot_id=run.portfolio_snapshot_id,
            historical_input_snapshot_id=run.historical_input_id,
            benchmark_version_id=run.benchmark_version_id,
            xray_run_id=run.xray_run_id,
            assets=assets,
            window=HistoricalWindow(
                start_date=row.period_start,
                end_date=row.period_end,
                source_cutoff_at=row.source_cutoff_at,
                reporting_currency=CurrencyCode(row.reporting_currency),
                knowledge_policy=KnowledgePolicy(row.knowledge_policy),
            ),
            idempotency_key="retained-risk-request",
            correlation_id="retained-risk-request",
        )
