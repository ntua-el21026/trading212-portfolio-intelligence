"""Atomic scenario admission, saved financial pages and operational lifecycle views."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_analytics.scenario_comparison import compare_scenario_results
from trading212_application import scenario as app
from trading212_application.risk import PremiumJobState
from trading212_application.scenario_projection import (
    RetainedScenarioResult,
    project_scenario_comparison_page,
    project_scenario_page,
)
from trading212_application.scenario_views import (
    ScenarioComparisonPage,
    ScenarioResultPage,
    ScenarioRunView,
)
from trading212_application.views import Page
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.serialization import canonical_json
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotResource
from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization
from .scenario_models import ScenarioResultModel, ScenarioRunModel
from .scenario_retention_policy import scenario_run_restricted
from .scenario_run_capture import _conditional_auth
from .scenario_service_base import scenario_error
from .scenario_service_definitions import ScenarioDefinitionService
from .scenario_store_types import (
    ScenarioCaptureSelection,
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)

MAX_SCENARIO_RUN_BYTES = 33554432


def scenario_run_command_digest(command: app.CreateScenarioRun) -> str:
    """Material requested identities only; tracing and retry keys do not alter semantics."""
    return sha256(
        b"t212pi.command.scenario.run.create.v1\0"
        + canonical_json(
            (
                command.account_id,
                command.scenario_version_id,
                command.portfolio_snapshot_id,
                command.xray_run_id,
                command.reporting_currency,
                command.source_cutoff_at,
                command.replay,
            )
        ).encode()
    ).hexdigest()


class PostgresScenarioService(ScenarioDefinitionService):
    def _run_rows(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> tuple[PremiumRunModel, ScenarioRunModel, PremiumJobModel]:
        root = self._owned(session, auth, PremiumRunModel, identifier)
        if root.kind != "scenario":
            raise scenario_error(app.ScenarioErrorCode.NOT_FOUND)
        run = self._owned(session, auth, ScenarioRunModel, identifier)
        job = session.scalar(
            select(PremiumJobModel).where(
                PremiumJobModel.run_id == identifier,
                PremiumJobModel.owner_id == auth.owner_id,
                PremiumJobModel.account_id == auth.account_id,
            )
        )
        if not run.sealed or job is None:
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        return root, run, job

    def _restricted(self, session: Session, root: PremiumRunModel) -> bool:
        restricted = session.scalar(
            select(PremiumRunModel.id).where(
                PremiumRunModel.id == root.id,
                PremiumRunModel.owner_id == root.owner_id,
                (scenario_run_restricted(self._now()))
                | select(PremiumRetentionModel.id)
                .where(
                    PremiumRetentionModel.owner_id == root.owner_id,
                    PremiumRetentionModel.run_id == root.id,
                )
                .exists(),
            )
        )
        return restricted is not None

    def _view(
        self,
        root: PremiumRunModel,
        run: ScenarioRunModel,
        job: PremiumJobModel,
        result: ScenarioResultPage | None = None,
        *,
        retained_expired: bool = False,
    ) -> ScenarioRunView:
        availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"] = (
            "pending"
        )
        if retained_expired or root.expires_at <= self._now() or job.state == "expired":
            availability, result = "expired", None
        elif result is not None:
            availability = "available"
        elif job.state == "succeeded":
            availability = "not_loaded"
        elif job.state in ("failed", "cancelled"):
            availability = "unavailable"
        return ScenarioRunView(
            id=root.id,
            account_id=root.account_id,
            scenario_version_id=run.definition_version_id,
            portfolio_snapshot_id=run.portfolio_snapshot_id,
            xray_run_id=run.xray_run_id,
            job_id=job.id,
            state=PremiumJobState(job.state),
            failure_code=job.failure_code,
            created_at=root.created_at,
            expires_at=root.expires_at,
            completed_at=job.completed_at,
            input_digest=root.input_digest,
            result=result,
            result_availability=availability,
        )

    def _current_inputs(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        run: ScenarioRunModel,
    ) -> ScenarioExecutionInput:
        if (
            run.id != root.id
            or root.kind != "scenario"
            or (run.owner_id, run.account_id) != (auth.owner_id, auth.account_id)
            or (root.owner_id, root.account_id) != (auth.owner_id, auth.account_id)
            or root.expires_at <= self._now()
        ):
            raise ScenarioStorageError(ScenarioStorageErrorCode.RUN_EXPIRED)
        auth = _conditional_auth(self, session, auth, run.historical_input_id)
        return self.read_retained_input(session, auth, root.id)

    async def create_run(
        self, principal: Principal, command: app.CreateScenarioRun
    ) -> ScenarioRunView:
        if type(command) is not app.CreateScenarioRun:
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ScenarioRunView:
            digest = scenario_run_command_digest(command)
            prior = self.prior_command(
                session, auth, "scenario.run.create.v1", command.idempotency_key, digest
            )
            if prior is not None:
                root, run, job = self._run_rows(
                    session, auth, cast(UUID, prior.premium_resource_id)
                )
                if root.command_id != prior.id:
                    raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
                expired = self._restricted(session, root)
                if not expired:
                    self._current_inputs(session, auth, root, run)
                return self._view(root, run, job, retained_expired=expired)
            created_at = self._now()
            if command.source_cutoff_at > created_at:
                raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)
            selection = ScenarioCaptureSelection(
                scenario_version_id=command.scenario_version_id,
                portfolio_snapshot_id=command.portfolio_snapshot_id,
                xray_run_id=command.xray_run_id,
                reporting_currency=command.reporting_currency,
                source_cutoff_at=command.source_cutoff_at,
                replay=command.replay,
            )
            captured = self.capture(session, auth, selection, retained_at=created_at)
            self.reserve_run_capacity(session, auth)
            identifier = uuid4()
            identity = self.command_identity(
                session,
                auth,
                "scenario.run.create.v1",
                command.idempotency_key,
                digest,
                identifier,
                command.correlation_id,
            )
            root = PremiumRunModel(
                id=identifier,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                kind="scenario",
                command_id=identity.id,
                actor_principal_id=auth.principal_id,
                input_digest=captured.value.input_digest,
                expires_at=captured.value.expires_at,
                method_version="1.0.0",
                schema_version="1.0.0",
                numerical_profile="premium_decimal96_q18_v1",
                reserved_bytes=MAX_SCENARIO_RUN_BYTES,
                retained_bytes=0,
                created_at=created_at,
            )
            session.add(root)
            session.flush()
            run = self.persist_capture(session, auth, root, captured)
            job = PremiumJobModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                run_id=root.id,
                state="queued",
                consumer_attempts=0,
                created_at=created_at,
            )
            session.add(job)
            session.flush()
            session.add(
                PremiumOutboxModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    job_id=job.id,
                    task_name="scenarios.calculate.v1",
                    state="pending",
                    publication_attempts=0,
                    available_at=created_at,
                    created_at=created_at,
                )
            )
            session.flush()
            auth = _conditional_auth(self, session, auth, run.historical_input_id)
            self._finish_result_authority(session, auth, root)
            return self._view(root, run, job)

        return await self._execute(principal, command.account_id, operation, write=True)

    def _retained_result(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        run: ScenarioRunModel,
        job: PremiumJobModel,
    ) -> RetainedScenarioResult:
        if self._restricted(session, root):
            raise scenario_error(app.ScenarioErrorCode.RUN_EXPIRED)
        if job.state != "succeeded":
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        auth = _conditional_auth(self, session, auth, run.historical_input_id)
        inputs = self._current_inputs(session, auth, root, run)
        value = self.read_result(session, auth, root, inputs)
        row = session.scalar(
            select(ScenarioResultModel).where(
                ScenarioResultModel.run_id == root.id,
                ScenarioResultModel.owner_id == auth.owner_id,
                ScenarioResultModel.account_id == auth.account_id,
            )
        )
        if row is None or not row.sealed:
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        return RetainedScenarioResult(
            run_id=root.id,
            result_id=row.id,
            account_id=auth.account_id,
            created_at=root.created_at,
            expires_at=inputs.expires_at,
            result_digest=row.content_digest,
            calculation=value,
        )

    async def get_run(
        self,
        principal: Principal,
        run_id: UUID,
        query: app.ScenarioComponentPageQuery,
        *,
        expected_account_id: UUID | None = None,
    ) -> ScenarioRunView:
        if type(query) is not app.ScenarioComponentPageQuery or (
            expected_account_id is not None and type(expected_account_id) is not UUID
        ):
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ScenarioRunView:
            # Account-scoped transports must bind the requested account before private reads.
            if expected_account_id is not None and auth.account_id != expected_account_id:
                raise scenario_error(app.ScenarioErrorCode.NOT_FOUND)
            root, run, job = self._run_rows(session, auth, run_id)
            expired = self._restricted(session, root)
            if expired or job.state != "succeeded":
                if query.component_cursor is not None:
                    raise scenario_error(
                        app.ScenarioErrorCode.RUN_EXPIRED
                        if expired
                        else app.ScenarioErrorCode.SCENARIO_UNAVAILABLE
                    )
                return self._view(root, run, job, retained_expired=expired)
            auth = _conditional_auth(self, session, auth, run.historical_input_id)
            retained = self._retained_result(session, auth, root, run, job)
            # Projection parses the cursor only after complete current financial authority.
            page = project_scenario_page(
                principal, auth.account_id, retained, query, cursors=self._cursors, now=self._now()
            )
            self._finish_result_authority(session, auth, root)
            return self._view(root, run, job, page)

        return await self._execute(principal, None, operation, resource=(ScenarioRunModel, run_id))

    async def list_runs(
        self, principal: Principal, account_id: UUID, query: app.ScenarioPageQuery
    ) -> Page[ScenarioRunView]:
        def operation(session: Session, auth: ReportAuthorization) -> Page[ScenarioRunView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.SCENARIO_RUNS,
                query,
                select(PremiumRunModel.id)
                .where(
                    PremiumRunModel.owner_id == auth.owner_id,
                    PremiumRunModel.account_id == auth.account_id,
                    PremiumRunModel.kind == "scenario",
                )
                .order_by(PremiumRunModel.created_at.desc(), PremiumRunModel.id.desc()),
            )
            rows = []
            for identifier in page.record_ids:
                root, run, job = self._run_rows(session, auth, identifier)
                rows.append(
                    self._view(root, run, job, retained_expired=self._restricted(session, root))
                )
            return Page(tuple(rows), page.next_cursor, page.limit, page.exact_total)

        return await self._execute(principal, account_id, operation)

    async def compare(
        self, principal: Principal, account_id: UUID, query: app.ScenarioComparisonQuery
    ) -> ScenarioComparisonPage:
        if type(query) is not app.ScenarioComparisonQuery:
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ScenarioComparisonPage:
            before_rows = self._run_rows(session, auth, query.run_ids[0])
            after_rows = self._run_rows(session, auth, query.run_ids[1])
            for _, run, _ in (before_rows, after_rows):
                auth = _conditional_auth(self, session, auth, run.historical_input_id)
            before = self._retained_result(session, auth, *before_rows)
            after = self._retained_result(session, auth, *after_rows)
            comparison = compare_scenario_results(before.calculation, after.calculation)
            result = project_scenario_comparison_page(
                principal,
                account_id,
                before,
                after,
                comparison,
                query,
                cursors=self._cursors,
                now=self._now(),
            )
            for root, _, _ in (before_rows, after_rows):
                self._finish_result_authority(session, auth, root)
            return result

        return await self._execute(principal, account_id, operation)

    async def cancel_run(
        self, principal: Principal, command: app.CancelScenarioRun
    ) -> ScenarioRunView:
        if type(command) is not app.CancelScenarioRun:
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ScenarioRunView:
            root, run, job = self._run_rows(session, auth, command.run_id)
            digest = sha256(
                b"t212pi.command.scenario.run.cancel.v1\0" + auth.account_id.bytes + root.id.bytes
            ).hexdigest()
            prior = self.prior_command(
                session, auth, "scenario.run.cancel.v1", command.idempotency_key, digest
            )
            if prior is None:
                if job.state not in ("queued", "running"):
                    raise scenario_error(app.ScenarioErrorCode.INVALID_STATE_TRANSITION)
                self.command_identity(
                    session,
                    auth,
                    "scenario.run.cancel.v1",
                    command.idempotency_key,
                    digest,
                    root.id,
                    command.correlation_id,
                )
                self._finish_job(session, root, job, "cancelled", None)
            elif prior.premium_resource_id != root.id:
                raise scenario_error(app.ScenarioErrorCode.CONFLICT)
            return self._view(root, run, job, retained_expired=self._restricted(session, root))

        return await self._execute(
            principal, None, operation, write=True, resource=(ScenarioRunModel, command.run_id)
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
        if (
            root.kind != "scenario"
            or job.run_id != root.id
            or (job.owner_id, job.account_id) != (root.owner_id, root.account_id)
            or job.state not in ("queued", "running")
            or state not in ("succeeded", "failed", "cancelled", "expired")
        ):
            raise scenario_error(app.ScenarioErrorCode.INVALID_STATE_TRANSITION)
        actual_bytes = self._result_bytes(session, root)
        if state == "succeeded" and retained_bytes != actual_bytes:
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        capacity = self._capacity_for_owner(session, root.owner_id)
        if (
            capacity.active_jobs < 1
            or capacity.reserved_bytes < root.reserved_bytes
            or capacity.retained_bytes < root.retained_bytes
        ):
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        outbox = session.scalar(
            select(PremiumOutboxModel).where(
                PremiumOutboxModel.job_id == job.id,
                PremiumOutboxModel.owner_id == root.owner_id,
                PremiumOutboxModel.account_id == root.account_id,
            )
        )
        if outbox is None:
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        at = self._now()
        premium_attempt(
            session,
            job,
            kind="consumer",
            event=state,
            number=job.consumer_attempts,
            token=job.lease_token,
            at=at,
            failure=failure_code,
        )
        capacity.active_jobs -= 1
        capacity.reserved_bytes -= root.reserved_bytes
        # Terminal failure/cancellation leaves private input bytes for bounded retention cleanup.
        capacity.retained_bytes += actual_bytes - root.retained_bytes
        capacity.updated_at = at
        root.reserved_bytes = 0
        root.retained_bytes = actual_bytes
        job.state, job.failure_code, job.completed_at = state, failure_code, at
        job.lease_token = job.lease_expires_at = job.heartbeat_at = job.deadline_at = (
            job.consumer_id
        ) = None
        outbox.state = "completed" if state in ("succeeded", "cancelled") else "dead_letter"
        outbox.failure_code = failure_code
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        session.flush()
