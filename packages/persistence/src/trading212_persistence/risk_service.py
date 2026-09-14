"""Transactional risk run admission and canonical reads; PostgreSQL is authoritative."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import risk as app
from trading212_application.risk_jobs import RiskExecutionInput
from trading212_application.views import Page
from trading212_domain.errors import DomainError
from trading212_domain.historical_serialization import historical_canonical_bytes
from trading212_domain.risk_result import RiskCalculation
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotResource
from .historical_base import digest
from .premium_models import (
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization
from .risk_definitions import risk_error
from .risk_inputs import RiskInputStore, RiskPreflight
from .risk_models import RiskResultModel, RiskRunAssetModel, RiskRunModel
from .risk_storage import RiskIntegrityError, verify_risk_result

MAX_RISK_RUN_BYTES = 33554432
MAX_OWNER_PREMIUM_BYTES = 268435456


def public_risk_result(value: RiskCalculation, content_digest: str) -> app.RiskResultView:
    context = value.history.canonical_performance_context
    view = app.RiskResultView(
        definition=value.definition,
        historical_context=replace(
            context, sources=context.sources[:64], warnings=context.warnings[:64]
        ),
        omitted_sources=max(0, len(context.sources) - 64),
        omitted_warnings=max(0, len(context.warnings) - 64),
        observed=value.observed,
        maximum_drawdown=value.history.maximum_drawdown,
        matrix=value.matrix,
        historical_tail=value.historical_tail,
        parametric_tail=value.parametric_tail,
        modeled=value.modeled,
        concentration=value.concentration,
        xray_result_digest=value.xray_result_digest,
        modeled_valuation_at=value.modeled_valuation_at,
        annualization_factor=value.annualization_factor,
        covariance_degrees_of_freedom=value.covariance_degrees_of_freedom,
        method_version=value.method_version,
        schema_version=value.schema_version,
        numerical_profile=value.numerical_profile,
        content_digest=content_digest,
    )
    if len(historical_canonical_bytes(view)) > 2097152:
        raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
    return view


def verify_risk_execution(value: RiskCalculation, inputs: RiskExecutionInput) -> None:
    if (
        value.definition != inputs.definition
        or tuple(x.key for x in value.history.assets)
        != tuple(x.instrument_id for x in inputs.assets)
        or value.xray_result_digest != (None if inputs.xray is None else inputs.xray.content_digest)
    ):
        raise RiskIntegrityError()


class PostgresRiskService(RiskInputStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        preflight: RiskPreflight,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(sessions, cursor_signing_key=cursor_signing_key, clock=clock)
        self._preflight = preflight

    def _run_rows(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> tuple[PremiumRunModel, RiskRunModel, PremiumJobModel]:
        root = self._owned(session, auth, PremiumRunModel, identifier)
        run = self._owned(session, auth, RiskRunModel, identifier)
        job = session.scalar(
            select(PremiumJobModel).where(
                PremiumJobModel.run_id == identifier,
                PremiumJobModel.owner_id == auth.owner_id,
                PremiumJobModel.account_id == auth.account_id,
            )
        )
        if root.kind != "risk" or not run.sealed or job is None:
            raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
        return root, run, job

    def _view(
        self,
        root: PremiumRunModel,
        run: RiskRunModel,
        job: PremiumJobModel,
        result: app.RiskResultView | None = None,
        *,
        retained_expired: bool = False,
    ) -> app.RiskRunView:
        availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"] = (
            "pending"
        )
        if retained_expired or job.state == "expired" or root.expires_at <= self._now():
            availability = "expired"
            result = None
        elif result is not None:
            availability = "available"
        elif job.state == "succeeded":
            availability = "not_loaded"
        elif job.state in ("failed", "expired", "cancelled"):
            availability = "unavailable"
        return app.RiskRunView(
            id=run.id,
            account_id=run.account_id,
            definition_version_id=run.definition_version_id,
            portfolio_snapshot_id=run.portfolio_snapshot_id,
            historical_input_snapshot_id=run.historical_input_id,
            xray_run_id=run.xray_run_id,
            job_id=job.id,
            state=app.PremiumJobState(job.state),
            failure_code=job.failure_code,
            created_at=root.created_at,
            expires_at=root.expires_at,
            completed_at=job.completed_at,
            input_digest=root.input_digest,
            result=result,
            result_availability=availability,
        )

    def _current_inputs(
        self, session: Session, auth: ReportAuthorization, root: PremiumRunModel, run: RiskRunModel
    ) -> RiskExecutionInput:
        if root.expires_at <= self._now() or session.scalar(
            select(PremiumRetentionModel.id)
            .where(
                PremiumRetentionModel.owner_id == auth.owner_id,
                PremiumRetentionModel.run_id == root.id,
            )
            .limit(1)
        ):
            raise risk_error(app.RiskErrorCode.RUN_EXPIRED)
        inputs = self._load_inputs(
            session,
            auth,
            self._retained_command(session, run),
            self._preflight,
            retained_at=root.created_at,
        )
        if root.input_digest != inputs.input_digest:
            raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
        return inputs

    def _read_run(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> app.RiskRunView:
        root, run, job = self._run_rows(session, auth, identifier)
        if root.expires_at <= self._now():
            return self._view(root, run, job)
        inputs = self._current_inputs(session, auth, root, run)
        result = None
        if job.state == "succeeded":
            row = session.scalar(
                select(RiskResultModel).where(
                    RiskResultModel.run_id == run.id,
                    RiskResultModel.owner_id == auth.owner_id,
                    RiskResultModel.account_id == auth.account_id,
                )
            )
            if row is None:
                raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
            try:
                value = verify_risk_result(session, run, row)
                verify_risk_execution(value, inputs)
            except (RiskIntegrityError, DomainError):
                raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE) from None
            result = public_risk_result(value, row.content_digest)
        return self._view(root, run, job, result)

    async def create_run(self, principal: Principal, command: app.CreateRiskRun) -> app.RiskRunView:
        def operation(session: Session, auth: ReportAuthorization) -> app.RiskRunView:
            # Revalidate material references even for idempotent admission replay.
            license_ids: set[UUID] = set()
            inputs = self._load_inputs(
                session, auth, command, self._preflight, license_ids=license_ids
            )
            prior = self._prior(
                session, auth, "risk.run.create.v1", command.idempotency_key, inputs.input_digest
            )
            if prior is not None:
                return self._read_run(session, auth, cast(UUID, prior.premium_resource_id))
            capacity = self._capacity(session, auth)
            if (
                capacity.active_jobs >= 2
                or capacity.reserved_bytes + capacity.retained_bytes + MAX_RISK_RUN_BYTES
                > MAX_OWNER_PREMIUM_BYTES
            ):
                raise risk_error(app.RiskErrorCode.RATE_LIMITED)
            capacity.active_jobs += 1
            capacity.reserved_bytes += MAX_RISK_RUN_BYTES
            capacity.updated_at = self._now()
            identifier = uuid4()
            identity = self._command(
                session,
                auth,
                "risk.run.create.v1",
                command.idempotency_key,
                inputs.input_digest,
                identifier,
                command.correlation_id,
            )
            root = PremiumRunModel(
                id=identifier,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                kind="risk",
                command_id=identity.id,
                actor_principal_id=auth.principal_id,
                input_digest=inputs.input_digest,
                expires_at=inputs.expires_at,
                method_version="1.0.0",
                schema_version="1.0.0",
                numerical_profile="premium_decimal96_q18_v1",
                reserved_bytes=MAX_RISK_RUN_BYTES,
                retained_bytes=0,
                created_at=self._now(),
            )
            session.add(root)
            session.flush()
            from trading212_domain.historical_serialization import historical_input_digest

            run = RiskRunModel(
                id=identifier,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                definition_version_id=command.definition_version_id,
                historical_input_id=command.historical_input_snapshot_id,
                historical_input_digest=historical_input_digest(inputs.historical),
                portfolio_snapshot_id=command.portfolio_snapshot_id,
                benchmark_version_id=command.benchmark_version_id,
                xray_run_id=command.xray_run_id,
                window_start_at=command.window.start_at,
                window_end_at=command.window.end_at,
                source_cutoff_at=command.window.source_cutoff_at,
                reporting_currency=command.window.reporting_currency.value,
                sealed=False,
                created_at=self._now(),
            )
            session.add(run)
            session.flush()
            for ordinal, source in enumerate(command.assets):
                session.add(
                    RiskRunAssetModel(
                        id=uuid4(),
                        owner_id=auth.owner_id,
                        account_id=auth.account_id,
                        run_id=run.id,
                        ordinal=ordinal,
                        instrument_id=UUID(source.instrument_id),
                        source_series_id=UUID(source.series_id),
                        created_at=self._now(),
                    )
                )
            session.flush()
            from .premium_models import PremiumRunLicenseModel
            from .source_models import ProviderLicenseVersionModel

            licenses = session.execute(
                select(ProviderLicenseVersionModel.id, ProviderLicenseVersionModel.provider_id)
                .where(
                    ProviderLicenseVersionModel.owner_id == auth.owner_id,
                    ProviderLicenseVersionModel.id.in_(license_ids),
                )
                .order_by(ProviderLicenseVersionModel.id)
            ).all()
            if len(licenses) != len(license_ids):
                raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
            for start in range(0, len(licenses), 500):
                session.add_all(
                    [
                        PremiumRunLicenseModel(
                            id=uuid4(),
                            owner_id=auth.owner_id,
                            account_id=auth.account_id,
                            run_id=run.id,
                            provider_id=license.provider_id,
                            license_version_id=license.id,
                            created_at=self._now(),
                        )
                        for license in licenses[start : start + 500]
                    ]
                )
                session.flush()
            run.sealed = True
            job = PremiumJobModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                run_id=run.id,
                state="queued",
                consumer_attempts=0,
                created_at=self._now(),
            )
            session.add(job)
            session.flush()
            session.add(
                PremiumOutboxModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    job_id=job.id,
                    task_name="risk.calculate.v1",
                    state="pending",
                    publication_attempts=0,
                    available_at=self._now(),
                    created_at=self._now(),
                )
            )
            session.flush()
            return self._view(root, run, job)

        return await self._execute(principal, command.account_id, operation, write=True)

    async def get_run(self, principal: Principal, run_id: UUID) -> app.RiskRunView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self._read_run(session, auth, run_id),
            resource=(RiskRunModel, run_id),
        )

    async def get_matrix(self, principal: Principal, run_id: UUID) -> app.RiskMatrixView:
        view = await self.get_run(principal, run_id)
        if view.result is None:
            raise risk_error(
                app.RiskErrorCode.RUN_EXPIRED
                if view.result_availability == "expired"
                else app.RiskErrorCode.RISK_UNAVAILABLE
            )
        result = view.result
        return app.RiskMatrixView(
            run_id=view.id,
            account_id=view.account_id,
            definition_version_id=view.definition_version_id,
            definition=result.definition,
            historical_context=result.historical_context,
            omitted_sources=result.omitted_sources,
            omitted_warnings=result.omitted_warnings,
            content_digest=result.content_digest,
            numerical_profile=result.numerical_profile,
            matrix=result.matrix,
        )

    async def list_runs(
        self, principal: Principal, account_id: UUID, query: app.RiskPageQuery
    ) -> Page[app.RiskRunView]:
        def operation(session: Session, auth: ReportAuthorization) -> Page[app.RiskRunView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.RISK_RUNS,
                query,
                select(PremiumRunModel.id)
                .where(
                    PremiumRunModel.owner_id == auth.owner_id,
                    PremiumRunModel.account_id == auth.account_id,
                    PremiumRunModel.kind == "risk",
                )
                .order_by(PremiumRunModel.created_at.desc(), PremiumRunModel.id.desc()),
            )
            records = session.execute(
                select(
                    PremiumRunModel,
                    RiskRunModel,
                    PremiumJobModel,
                    select(PremiumRetentionModel.id)
                    .where(
                        PremiumRetentionModel.owner_id == PremiumRunModel.owner_id,
                        PremiumRetentionModel.run_id == PremiumRunModel.id,
                    )
                    .exists(),
                )
                .join(RiskRunModel, RiskRunModel.id == PremiumRunModel.id)
                .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
                .where(
                    PremiumRunModel.owner_id == auth.owner_id,
                    PremiumRunModel.account_id == auth.account_id,
                    PremiumRunModel.id.in_(page.record_ids),
                )
            ).all()
            rows = {
                root.id: self._view(root, run, job, retained_expired=expired)
                for root, run, job, expired in records
            }
            if len(rows) != len(page.record_ids):
                raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
            return Page(
                tuple(rows[x] for x in page.record_ids),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._execute(principal, account_id, operation)

    async def cancel_run(self, principal: Principal, command: app.CancelRiskRun) -> app.RiskRunView:
        def operation(session: Session, auth: ReportAuthorization) -> app.RiskRunView:
            root, run, job = self._run_rows(session, auth, command.run_id)
            identity = digest((auth.account_id, command.run_id, "cancel"))
            prior = self._prior(
                session, auth, "risk.run.cancel.v1", command.idempotency_key, identity
            )
            if prior is not None:
                return self._view(root, run, job)
            if job.state not in ("queued", "running"):
                raise risk_error(app.RiskErrorCode.INVALID_STATE_TRANSITION)
            self._command(
                session,
                auth,
                "risk.run.cancel.v1",
                command.idempotency_key,
                identity,
                root.id,
                command.correlation_id,
                cancelled=True,
            )
            self._finish_job(session, root, job, "cancelled", None)
            return self._view(root, run, job)

        return await self._execute(
            principal, None, operation, write=True, resource=(RiskRunModel, command.run_id)
        )

    def _finish_job(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        state: str,
        failure_code: str | None,
        *,
        retained_bytes: int = 0,
    ) -> None:
        from .premium_attempts import premium_attempt

        premium_attempt(
            session,
            job,
            kind="consumer",
            event=state,
            number=job.consumer_attempts,
            token=job.lease_token,
            at=self._now(),
            failure=failure_code,
        )
        capacity = self._capacity_for_owner(session, root.owner_id)
        capacity.active_jobs -= 1
        capacity.reserved_bytes -= root.reserved_bytes
        capacity.retained_bytes += retained_bytes
        capacity.updated_at = self._now()
        root.reserved_bytes = 0
        root.retained_bytes = retained_bytes
        job.state = state
        job.failure_code = failure_code
        job.completed_at = self._now()
        job.lease_token = job.lease_expires_at = job.heartbeat_at = job.deadline_at = (
            job.consumer_id
        ) = None
        outbox = session.scalar(
            select(PremiumOutboxModel).where(
                PremiumOutboxModel.job_id == job.id, PremiumOutboxModel.owner_id == root.owner_id
            )
        )
        if outbox is None:
            raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
        outbox.state = "completed" if state in ("succeeded", "cancelled") else "dead_letter"
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        session.flush()
