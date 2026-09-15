"""Owned succeeded projection capture; REPORT joins every original/current source check."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as projection_app
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_v4 import (
    ReportContextSnapshotBinding,
    ReportContextV4,
    ReportProjectionRunBinding,
    ReportProjectionVersionBinding,
    ReportSelectionV4,
)
from trading212_domain.sources import SourceUse
from trading212_security.principals import AuthorizationError, Scope

from . import projection_models as m
from .historical_models import HistoricalInputModel
from .premium_models import (
    PremiumJobModel,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from .projection_definition_store import ProjectionStorageError, projection_owner_lock
from .projection_result_store import ProjectionResultStore
from .projection_source_presentation import (
    projection_source_presentation,
    projection_sources_presentation,
)
from .projection_source_store import ProjectionSourceStore
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_capture_projection import ProjectionReportMetadata, project_projection
from .report_capture_projection_cells import ProjectionReportBuilder
from .source_store import digest


class ProjectionReportSources(ProjectionSourceStore):
    def _license(
        self, session: Session, auth: ReportAuthorization, identifier: UUID, original_at: datetime
    ) -> datetime:
        deadline = super()._license(session, auth, identifier, original_at)
        self._sources._permit(session, auth.owner_id, identifier, SourceUse.REPORT)
        return deadline


class ProjectionReportStore(ProjectionResultStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(sessions, cursor_signing_key=cursor_signing_key, clock=clock)
        self.sources = ProjectionReportSources(
            sessions, cursor_signing_key=cursor_signing_key, clock=clock
        )
        self._calibration_resolver = self.sources.resolve_calibration


def authorize_projection_report_metadata(
    session: Session, auth: ReportAuthorization, run_id: UUID, *, now: datetime
) -> tuple[PremiumRunModel, m.ProjectionRunModel, PremiumJobModel, m.ProjectionResultModel]:
    """Permanent owned headers only: no deferred bytes or normalized monetary rows."""
    auth.check(session, now=now)
    projection_owner_lock(session, auth.owner_id)
    root = session.scalar(
        select(PremiumRunModel)
        .where(
            PremiumRunModel.id == run_id,
            PremiumRunModel.owner_id == auth.owner_id,
            PremiumRunModel.account_id == auth.account_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None or root.kind != "projection":
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    run = session.scalar(
        select(m.ProjectionRunModel)
        .where(
            m.ProjectionRunModel.id == run_id,
            m.ProjectionRunModel.owner_id == auth.owner_id,
            m.ProjectionRunModel.account_id == auth.account_id,
        )
        .execution_options(populate_existing=True)
    )
    job = session.scalar(
        select(PremiumJobModel)
        .where(
            PremiumJobModel.run_id == run_id,
            PremiumJobModel.owner_id == auth.owner_id,
            PremiumJobModel.account_id == auth.account_id,
        )
        .execution_options(populate_existing=True)
    )
    result = session.scalar(
        select(m.ProjectionResultModel)
        .where(
            m.ProjectionResultModel.run_id == run_id,
            m.ProjectionResultModel.owner_id == auth.owner_id,
            m.ProjectionResultModel.account_id == auth.account_id,
        )
        .execution_options(populate_existing=True)
    )
    if (
        root.expires_at <= now
        or session.scalar(
            select(PremiumRetentionModel.id).where(PremiumRetentionModel.run_id == run_id).limit(1)
        )
        is not None
    ):
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    if (
        run is None
        or not run.sealed
        or job is None
        or job.state != "succeeded"
        or job.completed_at is None
        or result is None
        or not result.sealed
        or result.job_id != job.id
    ):
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    count = tuple(
        session.scalars(
            select(PremiumRunLicenseModel.license_version_id)
            .where(
                PremiumRunLicenseModel.run_id == run_id,
                PremiumRunLicenseModel.owner_id == auth.owner_id,
                PremiumRunLicenseModel.account_id == auth.account_id,
            )
            .limit(257)
        )
    )
    if len(count) > 256:
        raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
    # Read authorization uses complete original lineage, never cleanup scan caches.
    scopes = auth.required_scopes | {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}
    histories = tuple(
        session.execute(
            select(HistoricalInputModel.id, HistoricalInputModel.target_version_id)
            .join(
                m.ProjectionRunSourceModel,
                (m.ProjectionRunSourceModel.subject_id == HistoricalInputModel.id)
                & (m.ProjectionRunSourceModel.owner_id == HistoricalInputModel.owner_id),
            )
            .where(
                m.ProjectionRunSourceModel.run_id == root.id,
                m.ProjectionRunSourceModel.owner_id == auth.owner_id,
                m.ProjectionRunSourceModel.account_id == auth.account_id,
                HistoricalInputModel.broker_account_id == auth.account_id,
            )
            .limit(258)
        )
    )
    if len(histories) > 257:
        raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
    if histories:
        scopes |= {Scope.ACTIVITY_READ}
        for history in histories:
            target = (
                history.target_version_id is not None
                or session.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM projection_history_links(:owner, :history) "
                        "WHERE target_version_id IS NOT NULL)"
                    ),
                    {"owner": auth.owner_id, "history": history.id},
                )
                is True
            )
            if target:
                scopes |= {Scope.TARGETS_READ}
    replace(auth, required_scopes=frozenset(scopes)).check(session, now=now)
    if session.scalar(select(func.projection_report_sources_restricted(root.id, now))) is not False:
        raise AuthorizationError("access denied")
    return root, run, job, result


def _version(
    session: Session, auth: ReportAuthorization, identifier: UUID, *, goal: bool = False
) -> ReportProjectionVersionBinding:
    model = m.GoalVersionModel if goal else m.AssumptionVersionModel
    parent = m.GoalVersionModel.goal_id if goal else m.AssumptionVersionModel.set_id
    fields = (
        parent.label("aggregate_id"),
        model.id.label("version_id"),
        model.version_number,
        model.predecessor_id,
        model.name,
        model.description,
        model.content_digest,
        model.created_at,
    )
    row = (
        session.execute(
            select(*fields).where(
                model.id == identifier,
                model.owner_id == auth.owner_id,
                model.account_id == auth.account_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    return ReportProjectionVersionBinding(**dict(row))


def capture_projection(
    builder: ProjectionReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
) -> ReportProjectionRunBinding:
    """Caller owns report admission, normalized dependency sealing and shared quotas."""
    from trading212_application.sources import SourceServiceError

    selection = builder.selection
    if type(selection) is not ReportSelectionV4:
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    root, run, job, result = authorize_projection_report_metadata(
        session, authorization, selection.premium_run.run_id, now=clock()
    )
    if run.reporting_currency != selection.reporting_currency.value or (
        r.ReportSection.GOAL in selection.sections and run.goal_version_id is None
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    snapshots = tuple(
        binding
        for binding in builder.bindings
        if binding.family is r.ReportFamily.SNAPSHOT
        and binding.role is r.ReportInputRole.SNAPSHOT
        and binding.subject_id == selection.snapshot_id
    )
    if len(snapshots) != 1:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    store = ProjectionReportStore(sessions, cursor_signing_key=cursor_signing_key, clock=clock)
    try:
        captured = store.read_retained_input(session, authorization, root.id)
        saved = store.read_result(session, authorization, root, captured)
        if saved.id != result.id or job.completed_at is None:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        input_id = session.scalar(
            select(m.ProjectionInputModel.id).where(
                m.ProjectionInputModel.run_id == root.id,
                m.ProjectionInputModel.owner_id == authorization.owner_id,
                m.ProjectionInputModel.account_id == authorization.account_id,
            )
        )
        if input_id is None:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        metadata = ProjectionReportMetadata(
            run_id=root.id,
            input_id=input_id,
            assumption=_version(session, authorization, run.assumption_version_id),
            goal=None
            if run.goal_version_id is None
            else _version(session, authorization, run.goal_version_id, goal=True),
            created_at=root.created_at,
            completed_at=job.completed_at,
            expires_at=root.expires_at,
            report_context=ReportContextSnapshotBinding(
                snapshot_id=selection.snapshot_id,
                snapshot_digest=snapshots[0].content_digest,
                valuation_at=builder.valuation_at,
                source_cutoff_at=selection.source_cutoff_at,
            ),
        )
        prefix = f"projection.{root.id}"
        facts = projection_sources_presentation(captured.sources)
        context = ReportContextV4(
            key=prefix,
            family=r.ReportFamily.PROJECTION,
            method_key=saved.calculation.method,
            method_version=saved.calculation.method_version,
            valuation_at=None
            if captured.plan.snapshot is None
            else captured.plan.snapshot.valuation_at,
            source_cutoff_at=facts.source_cutoff_at,
            quality=saved.quality,
            provenance_set_key=f"{prefix}.sources",
            coverage_set_key=f"{prefix}.coverage",
            note_set_key=f"{prefix}.notes",
        )
        builder.add_context(context)
        for identifier in captured.sources.license_version_ids:
            license = store.sources._sources._license(session, authorization.owner_id, identifier)
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=identifier,
                    provider_id=UUID(license.provider_id),
                    license_digest=digest(license),
                    attribution=license.attribution,
                    pinned_store=license.store,
                    pinned_display=license.display,
                    pinned_report=license.report,
                    pinned_export=license.export,
                    valid_from=license.effective_at,
                )
            )
            builder.add_reference(
                r.ReportSourceReference(
                    key=f"{prefix}.license.{identifier}",
                    kind=r.ReportSourceKind.LICENSE,
                    subject_id=identifier,
                    provider_id=UUID(license.provider_id),
                    license_version_id=identifier,
                    content_digest=digest(license),
                ),
                provenance_set_key=context.provenance_set_key,
            )
        kinds = {
            "portfolio_snapshot": r.ReportSourceKind.PORTFOLIO_SNAPSHOT,
            "historical_input": r.ReportSourceKind.HISTORICAL_INPUT,
            "price_total_return": r.ReportSourceKind.PRICE_SNAPSHOT,
            "benchmark_total_return": r.ReportSourceKind.BENCHMARK,
        }
        for source in captured.sources.sources:
            item = projection_source_presentation(source)
            provider_id = license_id = None
            if source.header.kind in {"price_total_return", "benchmark_total_return"}:
                # This is the original physical header, already authorized before decoding.
                original = source.header.metadata[0]
                provider_id, license_id = (
                    original.get("provider_id"),
                    original.get("license_version_id"),
                )
                if not isinstance(provider_id, UUID) or not isinstance(license_id, UUID):
                    raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
            builder.add_reference(
                r.ReportSourceReference(
                    key=f"{prefix}.source.{source.header.kind}.{source.header.subject_id}",
                    kind=kinds[source.header.kind],
                    subject_id=source.header.subject_id,
                    provider_id=provider_id,
                    license_version_id=license_id,
                    content_digest=source.header.content_digest,
                    first_observed_at=item.first_observed_at,
                ),
                provenance_set_key=context.provenance_set_key,
            )
        binding = project_projection(builder, captured, saved, metadata)
        deadline = store._source_boundary(session, authorization, root, captured)
        authorize_projection_report_metadata(session, authorization, root.id, now=clock())
        builder.limit_copy_expiry(min(root.expires_at, captured.expires_at, deadline))
        authorization.check(session, now=clock())
        return binding
    except ProjectionStorageError as error:
        code = {
            projection_app.ProjectionErrorCode.NOT_FOUND: app.ReportServiceErrorCode.NOT_FOUND,
            projection_app.ProjectionErrorCode.ACCESS_DENIED: (
                app.ReportServiceErrorCode.ACCESS_DENIED
            ),
            projection_app.ProjectionErrorCode.SOURCE_UNAVAILABLE: (
                app.ReportServiceErrorCode.ACCESS_DENIED
            ),
            projection_app.ProjectionErrorCode.RUN_EXPIRED: (
                app.ReportServiceErrorCode.ARTIFACT_EXPIRED
            ),
            projection_app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED: (
                app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
            ),
        }.get(error.code, app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        raise report_error(code) from None
    except SourceServiceError:
        raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED) from None
    except DomainError as error:
        raise report_error(
            app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED
            if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
            else app.ReportServiceErrorCode.REPORT_UNAVAILABLE
        ) from None
