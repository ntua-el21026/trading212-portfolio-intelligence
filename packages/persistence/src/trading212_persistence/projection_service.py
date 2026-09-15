"""Atomic saved-input projection admission, retained pages and goal analysis."""

from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import projection as app
from trading212_application.projection_paging import project_saved_projection_page
from trading212_application.projection_presentation import (
    RetainedProjectionPresentation,
    project_goal_analysis,
    unavailable_goal_analysis,
)
from trading212_application.projection_views import (
    GoalAnalysisView,
    ProjectionFailure,
    ProjectionOperationalRunView,
    ProjectionRunView,
)
from trading212_application.risk import PremiumJobState
from trading212_application.views import Page
from trading212_domain.projection import PROJECTION_MAX_BYTES
from trading212_domain.serialization import canonical_json
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotResource
from .premium_models import PremiumAuditModel, PremiumJobModel, PremiumOutboxModel, PremiumRunModel
from .projection_job_lifecycle import finish_projection_job
from .projection_models import ProjectionRunModel
from .projection_retention_policy import projection_run_restricted
from .projection_run_authorization import require_projection_run_sources
from .projection_service_base import projection_error
from .projection_service_definitions import ProjectionDefinitionService
from .projection_source_presentation import projection_sources_presentation
from .report_authorization import ReportAuthorization
from .report_models import ApplicationCommandIdentityModel


def projection_run_command_digest(command: app.CreateProjectionRun) -> str:
    """Bind the complete original calendar/source selection, excluding retry/tracing IDs."""
    return sha256(
        b"t212pi.command.projection.run.create.v1\0"
        + canonical_json(command.selection).encode("utf-8")
    ).hexdigest()


class PostgresProjectionService(ProjectionDefinitionService):
    def _run_rows(
        self,
        session: Session,
        auth: ReportAuthorization,
        identifier: UUID,
    ) -> tuple[PremiumRunModel, ProjectionRunModel, PremiumJobModel]:
        root = self._owned(session, auth, PremiumRunModel, identifier)
        if root.kind != "projection":
            raise projection_error(app.ProjectionErrorCode.NOT_FOUND)
        run = self._owned(session, auth, ProjectionRunModel, identifier)
        job = session.scalar(
            select(PremiumJobModel).where(
                PremiumJobModel.run_id == identifier,
                PremiumJobModel.owner_id == auth.owner_id,
                PremiumJobModel.account_id == auth.account_id,
            )
        )
        if (
            not run.sealed
            or job is None
            or run.capture_digest != root.input_digest
            or run.created_at != root.created_at
        ):
            raise projection_error(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        return root, run, job

    def _restricted(self, session: Session, root: PremiumRunModel) -> bool:
        return (
            session.scalar(
                select(PremiumRunModel.id).where(
                    PremiumRunModel.id == root.id,
                    PremiumRunModel.owner_id == root.owner_id,
                    PremiumRunModel.account_id == root.account_id,
                    projection_run_restricted(self._now()),
                )
            )
            is not None
        )

    def _operational(
        self,
        root: PremiumRunModel,
        run: ProjectionRunModel,
        job: PremiumJobModel,
        *,
        expired: bool,
    ) -> ProjectionOperationalRunView:
        availability: Literal["pending", "available", "not_loaded", "expired", "unavailable"] = (
            "pending"
        )
        if expired or root.expires_at <= self._now() or job.state == "expired":
            availability = "expired"
        elif job.state == "succeeded":
            availability = "not_loaded"
        elif job.state in ("failed", "cancelled"):
            availability = "unavailable"
        return ProjectionOperationalRunView(
            id=root.id,
            account_id=root.account_id,
            assumption_version_id=run.assumption_version_id,
            goal_version_id=run.goal_version_id,
            job_id=job.id,
            capture_digest=root.input_digest,
            numerical_input_digest=run.numerical_input_digest,
            state=PremiumJobState(job.state),
            result_availability=availability,
            created_at=root.created_at,
            expires_at=root.expires_at,
            completed_at=job.completed_at,
            failure_code=cast(ProjectionFailure | None, job.failure_code),
        )

    def _run_command(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: Literal["projection.run.create.v1", "projection.run.cancel.v1"],
        request: app.ProjectionCommand,
        digest: str,
        identifier: UUID,
    ) -> ApplicationCommandIdentityModel:
        at = self._now()
        identity = ApplicationCommandIdentityModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            command=command,
            idempotency_key=request.idempotency_key,
            command_digest=digest,
            premium_resource_id=identifier,
            premium_actor_id=auth.principal_id,
            premium_correlation_id=request.correlation_id,
            report_job_id=None,
            export_job_id=None,
            created_at=at,
        )
        session.add(identity)
        session.flush()
        session.add(
            PremiumAuditModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                command_id=identity.id,
                kind="cancelled" if command == "projection.run.cancel.v1" else "created",
                created_at=at,
            )
        )
        session.flush()
        return identity

    async def create_run(
        self,
        principal: Principal,
        command: app.CreateProjectionRun,
    ) -> ProjectionOperationalRunView:
        if type(command) is not app.CreateProjectionRun:
            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ProjectionOperationalRunView:
            digest = projection_run_command_digest(command)
            prior = self.prior_command(
                session, auth, "projection.run.create.v1", command.idempotency_key, digest
            )
            if prior is not None:
                if prior.premium_resource_id is None:
                    raise projection_error(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
                root, run, job = self._run_rows(session, auth, prior.premium_resource_id)
                if root.command_id != prior.id:
                    raise projection_error(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
                expired = self._restricted(session, root)
                if not expired:
                    require_projection_run_sources(self, session, auth, root, run)
                return self._operational(root, run, job, expired=expired)
            created_at = self._now()
            captured = self.capture(session, auth, command.selection, retained_at=created_at)
            self.reserve_run_capacity(session, auth)
            identifier = uuid4()
            identity = self._run_command(
                session, auth, "projection.run.create.v1", command, digest, identifier
            )
            root = PremiumRunModel(
                id=identifier,
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                kind="projection",
                command_id=identity.id,
                actor_principal_id=auth.principal_id,
                input_digest=captured.input_digest,
                expires_at=captured.expires_at,
                method_version="1.0.0",
                schema_version="1.0.0",
                numerical_profile="premium_decimal96_q18_v1",
                reserved_bytes=PROJECTION_MAX_BYTES,
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
                    task_name="projections.calculate.v1",
                    state="pending",
                    publication_attempts=0,
                    available_at=created_at,
                    created_at=created_at,
                )
            )
            session.flush()
            require_projection_run_sources(self, session, auth, root, run)
            return self._operational(root, run, job, expired=False)

        return await self._execute(principal, command.selection.account_id, operation, write="run")

    def _retained(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
        run: ProjectionRunModel,
        job: PremiumJobModel,
    ) -> RetainedProjectionPresentation:
        if job.state != "succeeded" or job.completed_at is None:
            raise projection_error(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        require_projection_run_sources(self, session, auth, root, run)
        captured = self.read_retained_input(session, auth, root.id)
        result = self.read_result(session, auth, root, captured)
        source = projection_sources_presentation(captured.sources)
        saved = RetainedProjectionPresentation(
            account_id=auth.account_id,
            run_id=root.id,
            result_id=result.id,
            capture_digest=root.input_digest,
            saved_result_digest=result.content_digest,
            capture=captured.plan,
            calculation=result.calculation,
            calculated_at=result.created_at,
            source_cutoff_at=source.source_cutoff_at,
            quality=result.quality,
            source_evidence=source.evidence,
        )
        self._source_boundary(session, auth, root, captured)
        return saved

    async def get_run(
        self,
        principal: Principal,
        run_id: UUID,
        query: app.ProjectionPointPageQuery,
        *,
        expected_account_id: UUID | None = None,
    ) -> ProjectionRunView:
        if type(query) is not app.ProjectionPointPageQuery:
            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ProjectionRunView:
            root, run, job = self._run_rows(session, auth, run_id)
            expired = self._restricted(session, root)
            operational = self._operational(root, run, job, expired=expired)
            if expired or job.state != "succeeded":
                if query.point_cursor is not None:
                    raise projection_error(
                        app.ProjectionErrorCode.RUN_EXPIRED
                        if expired
                        else app.ProjectionErrorCode.PROJECTION_UNAVAILABLE
                    )
                return operational
            saved = self._retained(session, auth, root, run, job)
            page = project_saved_projection_page(
                principal,
                saved,
                query,
                cursors=self._cursors,
                expires_at=root.expires_at,
                now=self._now(),
            )
            require_projection_run_sources(self, session, auth, root, run)
            return ProjectionRunView(
                **{
                    field.name: getattr(operational, field.name)
                    for field in fields(operational)
                    if field.name not in ("result", "result_availability")
                },
                result=page,
                result_availability="available",
            )

        return await self._execute(
            principal,
            None,
            operation,
            resource=(ProjectionRunModel, run_id),
            expected_account_id=expected_account_id,
        )

    async def get_goal_analysis(
        self,
        principal: Principal,
        run_id: UUID,
        *,
        expected_account_id: UUID | None = None,
    ) -> GoalAnalysisView:
        def operation(session: Session, auth: ReportAuthorization) -> GoalAnalysisView:
            root, run, job = self._run_rows(session, auth, run_id)
            expired = self._restricted(session, root)
            if expired or job.state != "succeeded" or run.goal_version_id is None:
                if not expired:
                    require_projection_run_sources(self, session, auth, root, run)
                return unavailable_goal_analysis(self._operational(root, run, job, expired=expired))
            saved = self._retained(session, auth, root, run, job)
            result = project_goal_analysis(saved)
            require_projection_run_sources(self, session, auth, root, run)
            return result

        return await self._execute(
            principal,
            None,
            operation,
            resource=(ProjectionRunModel, run_id),
            expected_account_id=expected_account_id,
        )

    async def list_runs(
        self,
        principal: Principal,
        account_id: UUID,
        query: app.ProjectionPageQuery,
    ) -> Page[ProjectionOperationalRunView]:
        def operation(
            session: Session, auth: ReportAuthorization
        ) -> Page[ProjectionOperationalRunView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.PROJECTION_RUNS,
                query,
                select(PremiumRunModel.id)
                .where(
                    PremiumRunModel.owner_id == auth.owner_id,
                    PremiumRunModel.account_id == auth.account_id,
                    PremiumRunModel.kind == "projection",
                )
                .order_by(PremiumRunModel.created_at.desc(), PremiumRunModel.id.desc()),
            )
            rows = []
            for identifier in page.record_ids:
                root, run, job = self._run_rows(session, auth, identifier)
                rows.append(
                    self._operational(root, run, job, expired=self._restricted(session, root))
                )
            return Page(tuple(rows), page.next_cursor, page.limit, page.exact_total)

        return await self._execute(principal, account_id, operation)

    async def cancel_run(
        self,
        principal: Principal,
        command: app.CancelProjectionRun,
    ) -> ProjectionOperationalRunView:
        if type(command) is not app.CancelProjectionRun:
            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)

        def operation(session: Session, auth: ReportAuthorization) -> ProjectionOperationalRunView:
            root, run, job = self._run_rows(session, auth, command.run_id)
            digest = sha256(
                b"t212pi.command.projection.run.cancel.v1\0" + auth.account_id.bytes + root.id.bytes
            ).hexdigest()
            prior = self.prior_command(
                session, auth, "projection.run.cancel.v1", command.idempotency_key, digest
            )
            if prior is None:
                if job.state not in ("queued", "running"):
                    raise projection_error(app.ProjectionErrorCode.INVALID_STATE_TRANSITION)
                self._run_command(
                    session, auth, "projection.run.cancel.v1", command, digest, root.id
                )
                finish_projection_job(self, session, root, job, "cancelled", None)
            elif prior.premium_resource_id != root.id:
                raise projection_error(app.ProjectionErrorCode.CONFLICT)
            return self._operational(root, run, job, expired=self._restricted(session, root))

        return await self._execute(
            principal, None, operation, write="run", resource=(ProjectionRunModel, command.run_id)
        )
