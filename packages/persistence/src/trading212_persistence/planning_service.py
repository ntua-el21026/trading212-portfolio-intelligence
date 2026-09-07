"""Canonical authorized drift projections and immutable durable contribution plans."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import planning as app
from trading212_application.planning_jobs import (
    PLAN_TASK_NAME,
    PlanJobFailureCode,
    PlanJobInputError,
)
from trading212_application.queries import CursorValidationError
from trading212_application.targets import (
    TargetServiceError,
    target_etag,
    validate_target_idempotency_key,
)
from trading212_application.views import Page
from trading212_domain import planning as d
from trading212_domain.errors import DomainError
from trading212_domain.planning_serialization import (
    contribution_plan_result_from_json,
    planning_input_digest,
    planning_input_from_json,
)
from trading212_domain.values import CurrencyCode, Money
from trading212_security.principals import Principal, Scope

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    collection_filter_fingerprint,
)
from .planning_collections import first_immutable_page
from .planning_inputs import capture_input, digest, unavailable, verify_references
from .planning_job_store import PlanningJobPersistence
from .planning_models import (
    AnalyticsDriftRowModel,
    AnalyticsRunModel,
    ContributionPlanJobModel,
    ContributionPlanLineModel,
    ContributionPlanModel,
    ContributionPlanOutboxModel,
    ContributionPlanRequestModel,
    ContributionPlanResultModel,
    PlanningAuditModel,
    PlanningCommandIdentityModel,
)
from .target_service import PostgresTargetService


def _error(code: app.PlanningServiceErrorCode) -> app.PlanningServiceError:
    return app.PlanningServiceError(
        code,
        {
            app.PlanningServiceErrorCode.NOT_FOUND: "The requested resource was not found.",
            app.PlanningServiceErrorCode.IDEMPOTENCY_KEY_REUSED: "Idempotency request mismatch.",
            app.PlanningServiceErrorCode.REVISION_REQUIRED: "A revision precondition is required.",
            app.PlanningServiceErrorCode.REVISION_MISMATCH: "The plan revision has changed.",
            app.PlanningServiceErrorCode.VALIDATION_FAILED: "The planning request is invalid.",
        }.get(code, "The planning request cannot be completed."),
    )


class PostgresPlanningService(PlanningJobPersistence, app.PlanningService):
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._targets = PostgresTargetService(
            sessions=sessions,
            cursor_signing_key=cursor_signing_key,
            clock=self._clock,
            cursor_ttl_seconds=cursor_ttl_seconds,
            max_active_collection_snapshots_per_owner=max_active_collection_snapshots_per_owner,
            max_active_collection_members_per_owner=max_active_collection_members_per_owner,
        )

    def _now(self) -> datetime:
        return self._targets._now()

    async def _run[T](
        self,
        principal: Principal,
        *,
        write: bool = False,
        target: bool = False,
        operation: Callable[[Session, UUID], T],
    ) -> T:
        for scope in (
            Scope.PORTFOLIO_READ,
            Scope.ANALYTICS_READ,
            *((Scope.TARGETS_READ,) if target or write else ()),
            *((Scope.PLANS_WRITE,) if write else ()),
        ):
            self._targets._authorizer.require_scope(principal, scope, now=self._now())
        owner = UUID(principal.owner_id)

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    self._owner_lock(session, owner)
                    return operation(session, owner)
            except TargetServiceError:
                code = app.PlanningServiceErrorCode.NOT_FOUND
            except IntegrityError:
                code = app.PlanningServiceErrorCode.VALIDATION_FAILED
            except SQLAlchemyError:
                code = app.PlanningServiceErrorCode.PLANNING_UNAVAILABLE
            except DomainError:
                code = app.PlanningServiceErrorCode.VALIDATION_FAILED
            except PlanJobInputError:
                code = app.PlanningServiceErrorCode.PLANNING_UNAVAILABLE
            raise _error(code)

        return await asyncio.to_thread(execute)

    def _capture(
        self, session: Session, owner: UUID, command: app.CreateContributionPlanCommand
    ) -> d.PlanningInput:
        from trading212_analytics.planning import validate_planning_input

        value = capture_input(
            session,
            owner=owner,
            account=UUID(command.account_id),
            portfolio_id=UUID(command.virtual_portfolio_id),
            target_id=UUID(command.target_version_id),
            snapshot_id=UUID(command.snapshot_id),
            options=command.options,
            targets=self._targets,
        )
        return validate_planning_input(value)

    def _load_request_input(
        self, session: Session, request: ContributionPlanRequestModel
    ) -> d.PlanningInput:
        value = planning_input_from_json(request.canonical_input)
        if planning_input_digest(value) != request.input_digest:
            raise PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED)
        verify_references(session, owner=request.owner_id, value=value)
        from .planning_storage import verify_normalized_input

        verify_normalized_input(session, request, value)
        return value

    def _persist_plan_result(
        self,
        session: Session,
        request: ContributionPlanRequestModel,
        result: d.ContributionPlanResult,
    ) -> None:
        from trading212_analytics.planning import verify_contribution_plan_result

        from .planning_storage import persist_result

        value = self._load_request_input(session, request)
        verify_contribution_plan_result(value, result)
        persist_result(session, request, result, at=self._now())

    def _job_view(
        self, session: Session, request: ContributionPlanRequestModel
    ) -> app.ContributionPlanJobView:
        plan = session.get(ContributionPlanModel, request.plan_id)
        job = session.scalar(
            select(ContributionPlanJobModel).where(
                ContributionPlanJobModel.request_id == request.id
            )
        )
        result = session.scalar(
            select(ContributionPlanResultModel).where(
                ContributionPlanResultModel.request_id == request.id
            )
        )
        if plan is None or job is None:
            raise unavailable()
        return app.ContributionPlanJobView(
            plan_id=str(plan.id),
            account_id=str(plan.broker_account_id),
            virtual_portfolio_id=str(plan.virtual_portfolio_id),
            target_version_id=str(request.target_version_id),
            snapshot_id=str(request.snapshot_id),
            request_id=str(request.id),
            request_revision=request.revision_number,
            job_id=str(job.id),
            state=app.PlanJobState(job.state),
            outcome=None if result is None else d.PlanOutcome(result.outcome),
            requested_at=request.created_at,
            input_digest=request.input_digest,
            plan_revision_id=None if result is None else str(result.id),
            failure_code=job.failure_code,
        )

    def _plan(self, session: Session, principal: Principal, plan_id: str) -> ContributionPlanModel:
        plan = session.scalar(
            select(ContributionPlanModel).where(
                ContributionPlanModel.id == UUID(plan_id),
                ContributionPlanModel.owner_id == UUID(principal.owner_id),
            )
        )
        if plan is None:
            raise unavailable()
        self._targets._account(session, principal, plan.broker_account_id)
        return plan

    def _create(
        self,
        session: Session,
        owner: UUID,
        principal: Principal,
        command: app.CreateContributionPlanCommand,
        *,
        key: str,
        correlation_id: str,
        plan_id: str | None = None,
        if_match: str | None = None,
    ) -> app.ContributionPlanJobView:
        validate_target_idempotency_key(key)
        if not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 120:
            raise _error(app.PlanningServiceErrorCode.VALIDATION_FAILED)
        self._targets._account(session, principal, UUID(command.account_id))
        plan = None if plan_id is None else self._plan(session, principal, plan_id)
        if plan is not None and (
            str(plan.broker_account_id) != command.account_id
            or str(plan.virtual_portfolio_id) != command.virtual_portfolio_id
        ):
            raise unavailable()
        kind = "create_plan" if plan is None else "revise_plan"
        command_digest = digest({"command": command, "plan_id": plan_id})
        identity = session.scalar(
            select(PlanningCommandIdentityModel).where(
                PlanningCommandIdentityModel.owner_id == owner,
                PlanningCommandIdentityModel.broker_account_id == UUID(command.account_id),
                PlanningCommandIdentityModel.command_kind == kind,
                PlanningCommandIdentityModel.idempotency_key == key,
            )
        )
        if identity is not None:
            if identity.request_digest != command_digest:
                raise _error(app.PlanningServiceErrorCode.IDEMPOTENCY_KEY_REUSED)
            request = session.get(ContributionPlanRequestModel, identity.request_id)
            if request is None:
                raise unavailable()
            return self._job_view(session, request)
        if plan is not None:
            if if_match is None:
                raise _error(app.PlanningServiceErrorCode.REVISION_REQUIRED)
            if if_match != target_etag(str(plan.id), plan.revision):
                raise _error(app.PlanningServiceErrorCode.REVISION_MISMATCH)
        value = self._capture(session, owner, command)
        now = self._now()
        if plan is None:
            plan = ContributionPlanModel(
                id=uuid4(),
                owner_id=owner,
                broker_account_id=UUID(command.account_id),
                virtual_portfolio_id=UUID(command.virtual_portfolio_id),
                revision=1,
                actor_principal_id=principal.principal_id,
                created_at=now,
                updated_at=now,
            )
            session.add(plan)
        else:
            plan.revision += 1
            plan.updated_at = now
        session.flush()
        from .planning_storage import persist_input

        request = persist_input(
            session,
            plan,
            value,
            command_digest=command_digest,
            actor=principal.principal_id,
            correlation=correlation_id,
            at=now,
        )
        job = ContributionPlanJobModel(
            id=uuid4(),
            owner_id=owner,
            request_id=request.id,
            state="queued",
            consumer_attempts=0,
            created_at=now,
        )
        session.add(job)
        session.flush()
        session.add_all(
            (
                ContributionPlanOutboxModel(
                    owner_id=owner,
                    job_id=job.id,
                    task_name=PLAN_TASK_NAME,
                    state="pending",
                    publication_attempts=0,
                    available_at=now,
                    created_at=now,
                ),
                PlanningCommandIdentityModel(
                    owner_id=owner,
                    broker_account_id=UUID(command.account_id),
                    request_id=request.id,
                    command_kind=kind,
                    idempotency_key=key,
                    request_digest=command_digest,
                    actor_principal_id=principal.principal_id,
                    created_at=now,
                ),
                PlanningAuditModel(
                    owner_id=owner,
                    request_id=request.id,
                    kind="requested",
                    actor_principal_id=principal.principal_id,
                    correlation_id=correlation_id,
                    created_at=now,
                ),
            )
        )
        session.flush()
        return self._job_view(session, request)

    async def create_contribution_plan(
        self,
        principal: Principal,
        command: app.CreateContributionPlanCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.ContributionPlanJobView:
        return await self._run(
            principal,
            write=True,
            operation=lambda s, o: self._create(
                s, o, principal, command, key=idempotency_key, correlation_id=correlation_id
            ),
        )

    async def create_contribution_plan_revision(
        self,
        principal: Principal,
        plan_id: str,
        command: app.CreateContributionPlanCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.ContributionPlanJobView:
        return await self._run(
            principal,
            write=True,
            operation=lambda s, o: self._create(
                s,
                o,
                principal,
                command,
                key=idempotency_key,
                correlation_id=correlation_id,
                plan_id=plan_id,
                if_match=if_match,
            ),
        )

    async def list_contribution_plans(
        self, principal: Principal, *, query: app.ContributionPlanQuery
    ) -> Page[app.ContributionPlanSummaryView]:
        def execute(session: Session, owner: UUID) -> Page[app.ContributionPlanSummaryView]:
            account = UUID(query.account_id)
            self._targets._account(session, principal, account)
            if query.virtual_portfolio_id is not None:
                portfolio = self._targets._portfolio(session, principal, query.virtual_portfolio_id)
                if portfolio.broker_account_id != account:
                    raise unavailable()
            if query.plan_id is not None:
                history_plan = self._plan(session, principal, query.plan_id)
                if history_plan.broker_account_id != account:
                    raise unavailable()
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.PLAN_REVISIONS
                if query.include_revisions
                else CollectionSnapshotResource.CONTRIBUTION_PLANS,
                owner,
                account,
                collection_filter_fingerprint(
                    query.virtual_portfolio_id,
                    query.state,
                    query.outcome,
                    query.plan_id,
                    query.include_revisions,
                ),
            )
            store = self._targets._store(session)
            if query.cursor is None:
                statement = (
                    select(ContributionPlanRequestModel.id)
                    .join(
                        ContributionPlanModel,
                        ContributionPlanRequestModel.plan_id == ContributionPlanModel.id,
                    )
                    .join(
                        ContributionPlanJobModel,
                        ContributionPlanJobModel.request_id == ContributionPlanRequestModel.id,
                    )
                    .outerjoin(
                        ContributionPlanResultModel,
                        ContributionPlanResultModel.request_id == ContributionPlanRequestModel.id,
                    )
                    .where(
                        ContributionPlanModel.owner_id == owner,
                        ContributionPlanModel.broker_account_id == account,
                    )
                )
                if query.include_revisions:
                    statement = statement.where(
                        ContributionPlanModel.id == UUID(str(query.plan_id))
                    )
                else:
                    statement = statement.where(
                        ContributionPlanRequestModel.revision_number
                        == ContributionPlanModel.revision
                    )
                if query.virtual_portfolio_id is not None:
                    statement = statement.where(
                        ContributionPlanModel.virtual_portfolio_id
                        == UUID(query.virtual_portfolio_id)
                    )
                if query.state is not None:
                    statement = statement.where(ContributionPlanJobModel.state == query.state.value)
                if query.outcome is not None:
                    statement = statement.where(
                        ContributionPlanResultModel.outcome == query.outcome.value
                    )
                page = store.materialize(
                    definition,
                    lambda: session.scalars(
                        statement.order_by(
                            ContributionPlanRequestModel.revision_number.desc()
                            if query.include_revisions
                            else ContributionPlanRequestModel.created_at.desc(),
                            ContributionPlanRequestModel.id.desc(),
                        ).execution_options(yield_per=1000)
                    ),
                    limit=query.limit,
                )
            else:
                page = store.resume(definition, cursor=query.cursor, limit=query.limit)
            items = []
            for record_id in page.record_ids:
                request = session.get(ContributionPlanRequestModel, record_id)
                if request is None:
                    raise unavailable()
                value = self._load_request_input(session, request)
                items.append(
                    app.ContributionPlanSummaryView(
                        self._job_view(session, request),
                        value.virtual_portfolio_id,
                        value.target_version_id,
                        value.valuation.snapshot_id,
                        value.options,
                    )
                )
            return Page(tuple(items), page.next_cursor, query.limit, page.exact_total)

        return await self._run(principal, operation=execute)

    async def get_contribution_plan(
        self, principal: Principal, plan_id: str, *, query: app.ContributionPlanDetailQuery
    ) -> app.ContributionPlanDetailView:
        def execute(session: Session, owner: UUID) -> app.ContributionPlanDetailView:
            plan = self._plan(session, principal, plan_id)
            if query.account_id is not None and query.account_id != str(plan.broker_account_id):
                raise unavailable()
            result = None
            if query.plan_revision_id is not None:
                result = session.scalar(
                    select(ContributionPlanResultModel)
                    .join(ContributionPlanRequestModel)
                    .where(
                        ContributionPlanResultModel.id == UUID(query.plan_revision_id),
                        ContributionPlanRequestModel.plan_id == plan.id,
                    )
                )
                if result is None:
                    raise unavailable()
                request = session.get(ContributionPlanRequestModel, result.request_id)
            else:
                request = session.scalar(
                    select(ContributionPlanRequestModel).where(
                        ContributionPlanRequestModel.plan_id == plan.id,
                        ContributionPlanRequestModel.revision_number == plan.revision,
                    )
                )
                if request is not None:
                    result = session.scalar(
                        select(ContributionPlanResultModel).where(
                            ContributionPlanResultModel.request_id == request.id
                        )
                    )
            if request is None:
                raise unavailable()
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.PLAN_LINES,
                owner,
                plan.broker_account_id,
                collection_filter_fingerprint(plan.id, query.plan_revision_id),
            )
            store = self._targets._store(session)
            if query.cursor is not None:
                page = store.resume(definition, cursor=query.cursor, limit=query.limit)
                if not page.record_ids:
                    raise CursorValidationError("The plan page is unavailable.")
                first = session.get(ContributionPlanLineModel, page.record_ids[0])
                result = (
                    None
                    if first is None
                    else session.get(ContributionPlanResultModel, first.result_id)
                )
                request = (
                    None
                    if result is None
                    else session.get(ContributionPlanRequestModel, result.request_id)
                )
                if request is None or request.plan_id != plan.id:
                    raise unavailable()
            else:
                ids = (
                    ()
                    if result is None
                    else tuple(
                        session.scalars(
                            select(ContributionPlanLineModel.id)
                            .where(ContributionPlanLineModel.result_id == result.id)
                            .order_by(ContributionPlanLineModel.ordinal)
                        )
                    )
                )
                page = first_immutable_page(
                    session,
                    store,
                    definition,
                    ids,
                    limit=query.limit,
                    source_kind="request" if result is None else "result",
                    source_id=request.id if result is None else result.id,
                )
            value = self._load_request_input(session, request)
            result_value = (
                None
                if result is None
                else contribution_plan_result_from_json(result.canonical_result)
            )
            lines = (
                ()
                if result_value is None
                else tuple(
                    result_value.lines[row.ordinal]
                    for line_id in page.record_ids
                    if (row := session.get(ContributionPlanLineModel, line_id)) is not None
                )
            )
            return app.ContributionPlanDetailView(
                self._job_view(session, request),
                app.CreateContributionPlanCommand(
                    account_id=value.valuation.account_id,
                    virtual_portfolio_id=value.virtual_portfolio_id,
                    target_version_id=value.target_version_id,
                    snapshot_id=value.valuation.snapshot_id,
                    options=value.options,
                ),
                None if result_value is None else result_value.summary,
                Page(lines, page.next_cursor, query.limit, page.exact_total),
                None if result is None else result.created_at,
                None if result is None else result.content_digest,
            )

        return await self._run(principal, operation=execute)

    def _drift(
        self,
        session: Session,
        owner: UUID,
        *,
        account_id: str,
        snapshot_id: str,
        portfolio_id: str,
        target_id: str,
        currency: CurrencyCode,
        kind: str,
        basis: d.DriftBasis,
    ) -> tuple[AnalyticsRunModel, d.DriftCalculation, d.PlanningInput]:
        from trading212_analytics.planning import calculate_drift
        from trading212_domain.planning_serialization import drift_calculation_from_json

        from .planning_storage import persist_drift

        value = self._capture(
            session,
            owner,
            app.CreateContributionPlanCommand(
                account_id=account_id,
                virtual_portfolio_id=portfolio_id,
                target_version_id=target_id,
                snapshot_id=snapshot_id,
                options=d.PlanningOptions(Money(Decimal(0), currency), d.PlanningMode.GLOBAL),
            ),
        )
        fingerprint = digest((planning_input_digest(value), basis))
        run = session.scalar(
            select(AnalyticsRunModel).where(
                AnalyticsRunModel.owner_id == owner,
                AnalyticsRunModel.broker_account_id == UUID(account_id),
                AnalyticsRunModel.kind == kind,
                AnalyticsRunModel.input_digest == fingerprint,
            )
        )
        if run is None:
            calculation = calculate_drift(value, basis=basis)
            run = persist_drift(
                session,
                owner,
                value,
                calculation,
                kind=kind,
                input_digest=fingerprint,
                at=self._now(),
            )
        else:
            calculation = drift_calculation_from_json(run.canonical_result)
        return run, calculation, value

    async def get_actual_vs_target(
        self, principal: Principal, account_id: str, *, query: app.ActualVsTargetQuery
    ) -> app.ActualVsTargetResult:
        def execute(session: Session, owner: UUID) -> app.ActualVsTargetResult:
            from trading212_domain.planning_serialization import drift_calculation_from_json

            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.ACTUAL_TARGET_ROWS,
                owner,
                UUID(account_id),
                collection_filter_fingerprint(
                    query.snapshot_id,
                    query.virtual_portfolio_id,
                    query.target_version_id,
                    query.reporting_currency.value,
                    query.node_id,
                ),
            )
            store = self._targets._store(session)
            resumed = None
            if query.cursor is not None:
                self._targets._account(session, principal, UUID(account_id))
                resumed = store.resume(definition, cursor=query.cursor, limit=query.limit)
                first_row = (
                    None
                    if not resumed.record_ids
                    else session.get(AnalyticsDriftRowModel, resumed.record_ids[0])
                )
                run = (
                    None if first_row is None else session.get(AnalyticsRunModel, first_row.run_id)
                )
                if (
                    run is None
                    or run.owner_id != owner
                    or run.broker_account_id != UUID(account_id)
                ):
                    raise unavailable()
                value = planning_input_from_json(run.canonical_input)
                verify_references(session, owner=owner, value=value)
                calculation = drift_calculation_from_json(run.canonical_result)
            else:
                run, calculation, value = self._drift(
                    session,
                    owner,
                    account_id=account_id,
                    snapshot_id=query.snapshot_id,
                    portfolio_id=query.virtual_portfolio_id,
                    target_id=query.target_version_id,
                    currency=query.reporting_currency,
                    kind="actual_vs_target",
                    basis=d.DriftBasis.DIRECT,
                )
            keys = None
            if query.node_id is not None:
                identity = next((x for x in value.node_identities if x.id == query.node_id), None)
                if identity is None:
                    raise unavailable()
                keys = {identity.key}
                for _ in range(8):
                    keys.update(x.key for x in value.target_content.nodes if x.parent_key in keys)
            if query.cursor is None:
                statement = select(AnalyticsDriftRowModel.id).where(
                    AnalyticsDriftRowModel.run_id == run.id
                )
                if keys is not None:
                    statement = statement.where(
                        AnalyticsDriftRowModel.key.in_({f"target/{key}" for key in keys})
                    )
                page = first_immutable_page(
                    session,
                    store,
                    definition,
                    tuple(session.scalars(statement.order_by(AnalyticsDriftRowModel.ordinal))),
                    limit=query.limit,
                    source_kind="run",
                    source_id=run.id,
                )
            else:
                assert resumed is not None
                page = resumed
            rows = tuple(
                calculation.rows[row.ordinal]
                for row_id in page.record_ids
                if (row := session.get(AnalyticsDriftRowModel, row_id)) is not None
            )
            return app.ActualVsTargetResult(
                calculation.context,
                run.created_at,
                calculation.totals,
                Page(rows, page.next_cursor, query.limit, page.exact_total),
                run.content_digest,
                target_identities=value.node_identities,
                node_id=query.node_id,
            )

        return await self._run(principal, target=True, operation=execute)

    async def get_drift_analysis(
        self, principal: Principal, account_id: str, *, query: app.DriftAnalysisQuery
    ) -> app.DriftAnalysisResult:
        def execute(session: Session, owner: UUID) -> app.DriftAnalysisResult:
            run, calculation, _ = self._drift(
                session,
                owner,
                account_id=account_id,
                snapshot_id=query.snapshot_id,
                portfolio_id=query.virtual_portfolio_id,
                target_id=query.target_version_id,
                currency=query.reporting_currency,
                kind="drift",
                basis=query.basis,
            )
            ranked = sorted(
                calculation.rows,
                key=lambda x: (x.absolute_drift is None, -(x.absolute_drift or Decimal(0)), x.key),
            )
            sampled = ranked[: query.top_n]
            return app.DriftAnalysisResult(
                calculation.context,
                run.created_at,
                calculation.totals,
                tuple(x for x in sampled if x.kind == "group"),
                tuple(x for x in sampled if x.kind == "holding"),
                tuple(x for x in sampled if x.kind not in {"group", "holding"}),
                query.basis,
                query.top_n,
                len(ranked),
                max(0, len(ranked) - query.top_n),
                run.content_digest,
            )

        return await self._run(principal, target=True, operation=execute)
