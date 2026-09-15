"""Normalized premium report lineage and current permission checks before decoding."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.report_v3 import (
    ReportCaptureSummaryV3,
    ReportRiskRunBinding,
    ReportScenarioRunBinding,
    ReportScenarioRunSelection,
    ReportSelectionV3,
)
from trading212_security.principals import AuthorizationError, Scope

from .historical_models import HistoricalInputModel
from .models import PortfolioSnapshotModel
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
from .risk_models import RiskResultModel, RiskRunModel, RiskVersionModel
from .scenario_models import ScenarioResultModel, ScenarioRunModel, ScenarioVersionModel
from .xray_run_models import XrayInputSnapshotModel, XrayRunModel


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
    selection: r.ReportSelection | r.ExportSelection | ReportSelectionV3,
    summary: r.ReportCaptureSummary | ReportCaptureSummaryV3,
    *,
    now: datetime,
) -> datetime | None:
    if isinstance(selection, ReportSelectionV3):
        return _bind_v3(session, authorization, capture, selection, summary, now=now)
    if isinstance(summary, ReportCaptureSummaryV3):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
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
    if version not in (2, 3) or len(dependencies) != 1:
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
    result: RiskResultModel | ScenarioResultModel
    if version == 3 and dependency.kind == "scenario":
        root, _scenario, _job, result = _scenario_metadata(
            session, authorization, dependency.run_id, now=now
        )
    elif dependency.kind == "risk":
        root, _risk, _job, result = authorize_risk_report_metadata(
            session, authorization, dependency.run_id, now=now
        )
    else:
        raise AuthorizationError("access denied")
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


def _scenario_metadata(
    session: Session, authorization: ReportAuthorization, run_id: UUID, *, now: datetime
) -> tuple[PremiumRunModel, ScenarioRunModel, PremiumJobModel, ScenarioResultModel]:
    # Reuse the capture loader's permanent-header check; do not instantiate a
    # canonical reader merely to authorize already materialized report bytes.
    from .report_capture_scenario_store import authorize_scenario_report_metadata

    root, run, job, result = authorize_scenario_report_metadata(
        session, authorization, run_id, now=now
    )
    scopes = authorization.required_scopes | {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}
    if run.historical_input_id is not None:
        scopes |= {Scope.ACTIVITY_READ}
        history = session.execute(
            select(HistoricalInputModel.id, HistoricalInputModel.target_version_id).where(
                HistoricalInputModel.id == run.historical_input_id,
                HistoricalInputModel.owner_id == authorization.owner_id,
                HistoricalInputModel.broker_account_id == authorization.account_id,
                HistoricalInputModel.sealed.is_(True),
            )
        ).first()
        if history is None:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        if history.target_version_id is not None:
            scopes |= {Scope.TARGETS_READ}
    replace(authorization, required_scopes=scopes).check(session, now=now)
    return root, run, job, result


def _bind_v3(
    session: Session,
    authorization: ReportAuthorization,
    capture: ReportInputSnapshotModel,
    selection: ReportSelectionV3,
    summary: r.ReportCaptureSummary | ReportCaptureSummaryV3,
    *,
    now: datetime,
) -> datetime:
    if (
        capture.contract_version != 3
        or capture.kind != "report"
        or not isinstance(summary, ReportCaptureSummaryV3)
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    if summary.header.selection != selection:
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    pin = summary.header.premium_binding
    result: RiskResultModel | ScenarioResultModel
    if isinstance(selection.premium_run, ReportScenarioRunSelection):
        if not isinstance(pin, ReportScenarioRunBinding):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        root, scenario, job, result = _scenario_metadata(
            session, authorization, selection.premium_run.run_id, now=now
        )
        version = session.scalar(
            select(ScenarioVersionModel).where(
                ScenarioVersionModel.id == scenario.definition_version_id,
                ScenarioVersionModel.owner_id == authorization.owner_id,
                ScenarioVersionModel.account_id == authorization.account_id,
            )
        )
        if version is None or (
            pin.scenario_id != version.definition_id
            or pin.scenario_version_id != scenario.definition_version_id
            or pin.scenario_version_digest != scenario.definition_digest
            or pin.scenario_version_digest != version.content_digest
            or pin.snapshot_id != scenario.portfolio_snapshot_id
            or pin.snapshot_digest != scenario.portfolio_snapshot_digest
            or pin.reporting_currency.value != scenario.reporting_currency
            or pin.source_cutoff_at != scenario.source_cutoff_at
            or pin.xray.run_id != scenario.xray_run_id
            or pin.xray.input_id != scenario.xray_input_id
            or pin.xray.input_digest != scenario.xray_input_digest
            or pin.xray.result_digest != scenario.xray_result_digest
            or ((pin.historical is None) != (scenario.historical_input_id is None))
            or (
                pin.historical is not None
                and (
                    pin.historical.input_snapshot_id != scenario.historical_input_id
                    or pin.historical.input_digest != scenario.historical_input_digest
                    or selection.start_date != scenario.replay_start_date
                    or selection.end_date != scenario.replay_end_date
                )
            )
        ):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        definition_id, definition_digest = pin.scenario_version_id, pin.scenario_version_digest
    else:
        if not isinstance(pin, ReportRiskRunBinding):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        root, risk, job, result = authorize_risk_report_metadata(
            session, authorization, selection.premium_run.run_id, now=now
        )
        risk_version = session.scalar(
            select(RiskVersionModel).where(
                RiskVersionModel.id == risk.definition_version_id,
                RiskVersionModel.owner_id == authorization.owner_id,
                RiskVersionModel.account_id == authorization.account_id,
            )
        )
        if risk_version is None or (
            pin.definition_id != risk_version.definition_id
            or pin.definition_version_id != risk.definition_version_id
            or pin.definition_digest != risk_version.content_digest
            or pin.snapshot_id != risk.portfolio_snapshot_id
            or pin.reporting_currency.value != risk.reporting_currency
            or pin.source_cutoff_at != risk.source_cutoff_at
            or pin.historical.input_snapshot_id != risk.historical_input_id
            or pin.historical.input_digest != risk.historical_input_digest
            or pin.start_date != selection.start_date
            or pin.end_date != selection.end_date
            or risk.window_start_at != datetime.combine(selection.start_date, time.min, tzinfo=UTC)
            or risk.window_end_at
            != datetime.combine(selection.end_date + timedelta(days=1), time.min, tzinfo=UTC)
            or pin.benchmark_version_id != risk.benchmark_version_id
            or ((pin.xray is None) != (risk.xray_run_id is None))
            or (pin.xray is not None and pin.xray.run_id != risk.xray_run_id)
        ):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        definition_id, definition_digest = pin.definition_version_id, pin.definition_digest
    snapshot = session.scalar(
        select(PortfolioSnapshotModel.valuation_at).where(
            PortfolioSnapshotModel.id == pin.snapshot_id,
            PortfolioSnapshotModel.broker_account_id == authorization.account_id,
        )
    )
    if snapshot is None or (
        pin.run_id != root.id
        or pin.family.value != root.kind
        or pin.owner_id != authorization.owner_id
        or pin.account_id != authorization.account_id
        or pin.input_digest != root.input_digest
        or pin.result_id != result.id
        or pin.result_digest != result.content_digest
        or pin.created_at != root.created_at
        or pin.completed_at != job.completed_at
        or pin.expires_at != root.expires_at
        or pin.snapshot_id != selection.snapshot_id
        or pin.snapshot_id != capture.snapshot_id
        or pin.reporting_currency != selection.reporting_currency
        or pin.reporting_currency.value != capture.reporting_currency
        or pin.source_cutoff_at != selection.source_cutoff_at
        or pin.source_cutoff_at != capture.source_cutoff_at
        or pin.valuation_at != capture.valuation_at
        or pin.valuation_at != snapshot
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    if pin.xray is not None:
        xray = session.execute(
            select(XrayRunModel.input_id, XrayRunModel.content_digest).where(
                XrayRunModel.id == pin.xray.run_id,
                XrayRunModel.owner_id == authorization.owner_id,
                XrayRunModel.sealed_at.is_not(None),
            )
        ).first()
        xray_input = session.scalar(
            select(XrayInputSnapshotModel.input_digest).where(
                XrayInputSnapshotModel.id == pin.xray.input_id,
                XrayInputSnapshotModel.owner_id == authorization.owner_id,
                XrayInputSnapshotModel.account_id == authorization.account_id,
            )
        )
        if (
            xray is None
            or xray_input is None
            or xray.input_id != pin.xray.input_id
            or xray.content_digest != pin.xray.result_digest
            or xray_input != pin.xray.input_digest
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
            kind=root.kind,
            input_digest=root.input_digest,
            result_digest=result.content_digest,
            result_id=result.id,
            definition_version_id=definition_id,
            definition_digest=definition_digest,
            snapshot_id=pin.snapshot_id,
            snapshot_digest=pin.snapshot_digest,
            reporting_currency=pin.reporting_currency.value,
            source_cutoff_at=pin.source_cutoff_at,
            valuation_at=pin.valuation_at,
            expires_at=deadline,
            created_at=now,
        )
    )
    session.flush()
    # The input sink clamps every original-source deadline, then authorizes before sealing.
    return deadline
