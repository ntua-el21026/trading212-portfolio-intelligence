"""Normalized premium report lineage and current permission checks before decoding."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_security.principals import AuthorizationError, Scope

from .historical_models import HistoricalInputModel
from .premium_models import (
    PremiumJobModel,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_models import (
    ReportInputLicenseModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
)
from .risk_models import RiskResultModel, RiskRunModel


def authorize_risk_report_metadata(
    session: Session, authorization: ReportAuthorization, run_id: UUID, *, now: datetime
) -> tuple[PremiumRunModel, RiskRunModel, PremiumJobModel, RiskResultModel]:
    """Load only owned, deferred-payload headers and require full-proof read scopes."""
    root = session.scalar(
        select(PremiumRunModel).where(
            PremiumRunModel.owner_id == authorization.owner_id,
            PremiumRunModel.account_id == authorization.account_id,
            PremiumRunModel.id == run_id,
        )
    )
    run = session.scalar(
        select(RiskRunModel).where(
            RiskRunModel.owner_id == authorization.owner_id,
            RiskRunModel.account_id == authorization.account_id,
            RiskRunModel.id == run_id,
        )
    )
    if root is None or run is None or root.kind != "risk":
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    job = session.scalar(
        select(PremiumJobModel).where(
            PremiumJobModel.owner_id == authorization.owner_id,
            PremiumJobModel.account_id == authorization.account_id,
            PremiumJobModel.run_id == run_id,
        )
    )
    result = session.scalar(
        select(RiskResultModel).where(
            RiskResultModel.owner_id == authorization.owner_id,
            RiskResultModel.account_id == authorization.account_id,
            RiskResultModel.run_id == run_id,
        )
    )
    if (
        not run.sealed
        or job is None
        or result is None
        or not result.sealed
        or job.state != "succeeded"
    ):
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    if (
        root.expires_at <= now
        or session.scalar(
            select(PremiumRetentionModel.id)
            .where(
                PremiumRetentionModel.owner_id == authorization.owner_id,
                PremiumRetentionModel.run_id == root.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    history = session.execute(
        select(
            HistoricalInputModel.id,
            HistoricalInputModel.target_version_id,
        ).where(
            HistoricalInputModel.owner_id == authorization.owner_id,
            HistoricalInputModel.broker_account_id == authorization.account_id,
            HistoricalInputModel.id == run.historical_input_id,
            HistoricalInputModel.sealed.is_(True),
        )
    ).first()
    if history is None:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    scopes = authorization.required_scopes | {Scope.ANALYTICS_READ, Scope.ACTIVITY_READ}
    if history.target_version_id is not None:
        scopes |= {Scope.TARGETS_READ}
    replace(authorization, required_scopes=scopes).check(session, now=now)
    licenses = session.scalars(
        select(PremiumRunLicenseModel.license_version_id)
        .where(
            PremiumRunLicenseModel.owner_id == authorization.owner_id,
            PremiumRunLicenseModel.account_id == authorization.account_id,
            PremiumRunLicenseModel.run_id == run_id,
        )
        .limit(257)
    ).all()
    if len(licenses) > 256:
        raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED)
    return root, run, job, result


def bind_report_premium_dependency(
    session: Session,
    authorization: ReportAuthorization,
    capture: ReportInputSnapshotModel,
    selection: r.ReportSelection | r.ExportSelection,
    summary: r.ReportCaptureSummary,
    *,
    now: datetime,
) -> datetime | None:
    if not isinstance(selection, r.ReportSelection) or selection.risk_run_id is None:
        if capture.contract_version != 1:
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        return None
    if capture.contract_version != 2:
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    root, run, _job, result = authorize_risk_report_metadata(
        session, authorization, selection.risk_run_id, now=now
    )
    if (
        run.portfolio_snapshot_id != selection.snapshot_id
        or run.reporting_currency != selection.reporting_currency.value
        or run.window_start_at != datetime.combine(selection.start_date, time.min, tzinfo=UTC)
        or run.window_end_at
        != datetime.combine(selection.end_date + timedelta(days=1), time.min, tzinfo=UTC)
        or run.source_cutoff_at != selection.source_cutoff_at
        or not any(
            pin.family is r.ReportFamily.RISK
            and pin.role is r.ReportInputRole.INPUT
            and pin.subject_id == root.id
            and pin.content_digest == root.input_digest
            for pin in summary.immutable_bindings
        )
        or not any(
            pin.family is r.ReportFamily.RISK
            and pin.role is r.ReportInputRole.RESULT
            and pin.subject_id == result.id
            and pin.content_digest == result.content_digest
            and pin.parent_id == root.id
            for pin in summary.immutable_bindings
        )
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    deadline = min(root.expires_at, summary.copy_expires_at or root.expires_at)
    session.add(
        ReportInputPremiumDependencyModel(
            id=uuid4(),
            owner_id=authorization.owner_id,
            account_id=authorization.account_id,
            input_id=capture.id,
            run_id=root.id,
            kind="risk",
            input_digest=root.input_digest,
            result_digest=result.content_digest,
            expires_at=deadline,
            created_at=now,
        )
    )
    session.flush()
    authorize_report_premium_sources(session, authorization, input_id=capture.id, now=now)
    return deadline


def authorize_report_premium_sources(
    session: Session, authorization: ReportAuthorization, *, input_id: UUID, now: datetime
) -> None:
    version = session.scalar(
        select(ReportInputSnapshotModel.contract_version).where(
            ReportInputSnapshotModel.owner_id == authorization.owner_id,
            ReportInputSnapshotModel.account_id == authorization.account_id,
            ReportInputSnapshotModel.id == input_id,
        )
    )
    dependencies = session.scalars(
        select(ReportInputPremiumDependencyModel)
        .where(
            ReportInputPremiumDependencyModel.owner_id == authorization.owner_id,
            ReportInputPremiumDependencyModel.account_id == authorization.account_id,
            ReportInputPremiumDependencyModel.input_id == input_id,
        )
        .limit(2)
    ).all()
    if version == 1 and not dependencies:
        return
    if version != 2 or len(dependencies) != 1:
        raise AuthorizationError("access denied")
    dependency = dependencies[0]
    # SQL shares this predicate with bounded expiry and its database authorization
    # guard. No canonical result, history or report bytes are selected here.
    if (
        session.scalar(
            select(func.report_premium_restricted(authorization.owner_id, input_id, now))
        )
        is not False
    ):
        raise AuthorizationError("access denied")
    root, _run, _job, result = authorize_risk_report_metadata(
        session, authorization, dependency.run_id, now=now
    )
    if (
        root.input_digest != dependency.input_digest
        or result.content_digest != dependency.result_digest
    ):
        raise AuthorizationError("access denied")
    missing_license = session.scalar(
        select(PremiumRunLicenseModel.id)
        .where(
            PremiumRunLicenseModel.owner_id == authorization.owner_id,
            PremiumRunLicenseModel.run_id == dependency.run_id,
            ~select(ReportInputLicenseModel.id)
            .where(
                ReportInputLicenseModel.owner_id == authorization.owner_id,
                ReportInputLicenseModel.input_id == input_id,
                ReportInputLicenseModel.license_version_id
                == PremiumRunLicenseModel.license_version_id,
                ReportInputLicenseModel.provider_id == PremiumRunLicenseModel.provider_id,
            )
            .exists(),
        )
        .limit(1)
    )
    if missing_license is not None:
        raise AuthorizationError("access denied")
