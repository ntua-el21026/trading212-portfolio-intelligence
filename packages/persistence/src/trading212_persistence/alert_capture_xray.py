"""Alert selection over the complete retained exact X-ray calculation."""

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.alerts import xray_observation
from trading212_analytics.quality import combine_quality
from trading212_domain import alerts as d
from trading212_domain.enums import QualityState
from trading212_domain.reports import ReportSourceKind

from . import source_models as sm
from . import xray_catalog_models as cm
from . import xray_run_models as xm
from .alert_capture_common import AlertCaptureState, AlertCaptureUnavailable, bounded
from .alert_capture_fx import capture_physical
from .alert_capture_xray_sources import capture_xray_sources
from .models import PortfolioSnapshotModel
from .portfolio_service import _snapshot_quality
from .xray_service import PostgresXrayService

_PHYSICAL: dict[
    str, tuple[type[sm.SourceSnapshotFields | cm.XrayEvidenceFields], ReportSourceKind]
] = {
    "fx_snapshot_id": (sm.FxSnapshotModel, ReportSourceKind.FX_SNAPSHOT),
    "entity_evidence_version_id": (
        cm.EntityEvidenceVersionModel,
        ReportSourceKind.ENTITY_EVIDENCE_VERSION,
    ),
    "classification_snapshot_id": (
        cm.ClassificationSnapshotModel,
        ReportSourceKind.CLASSIFICATION_SNAPSHOT,
    ),
    "fund_definition_id": (cm.FundDefinitionModel, ReportSourceKind.FUND_DEFINITION),
    "fund_mapping_id": (cm.FundSourceMappingModel, ReportSourceKind.FUND_MAPPING),
    "constituent_snapshot_id": (cm.ConstituentSnapshotModel, ReportSourceKind.CONSTITUENT_SNAPSHOT),
}


def capture_xray(
    state: AlertCaptureState, *, sessions: sessionmaker[Session], cursor_signing_key: bytes
) -> d.AlertThresholdInput:
    run, capture = xm.XrayRunModel, xm.XrayInputSnapshotModel
    query = (
        select(run.id, run.input_id)
        .join(capture, capture.id == run.input_id)
        .where(
            run.owner_id == state.version.owner_id,
            capture.owner_id == state.version.owner_id,
            capture.account_id == state.version.account_id,
            run.created_at <= state.cutoff,
            run.calculated_at <= state.cutoff,
            run.sealed_at <= state.cutoff,
            capture.created_at <= state.cutoff,
            capture.captured_at <= state.cutoff,
            capture.sealed_at <= state.cutoff,
            capture.source_cutoff_at <= state.cutoff,
            capture.valuation_at <= state.cutoff,
        )
    )
    if state.version.definition.source_policy_version_id is not None:
        query = query.where(capture.policy_id == state.version.definition.source_policy_version_id)
    identifiers = state.session.execute(
        query.order_by(
            capture.valuation_at.desc(),
            capture.source_cutoff_at.desc(),
            run.calculated_at.desc(),
            run.id,
        ).limit(1)
    ).first()
    if identifiers is None:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    run_id, input_id = identifiers
    dependency = xm.XrayInputDependencyModel
    columns = tuple(getattr(dependency, name) for name in _PHYSICAL)
    rows = bounded(
        list(
            state.session.execute(
                select(*columns)
                .where(
                    dependency.owner_id == state.version.owner_id, dependency.input_id == input_id
                )
                .limit(100001)
            )
        ),
        100000,
    )
    # STORE+DISPLAY applies before decoding any retained calculation or dependency bytes.
    for row in rows:
        for identifier, (model, kind) in zip(row, _PHYSICAL.values(), strict=True):
            if identifier is None:
                continue
            header = state.session.get(model, identifier)
            if not isinstance(header, (sm.SourceSnapshotFields, cm.XrayEvidenceFields)):
                raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
            capture_physical(state, header, kind)
    service = PostgresXrayService(
        sessions=sessions, cursor_signing_key=cursor_signing_key, clock=lambda: state.now
    )
    principal = state.authorization.as_principal(now=state.now)
    handle = service._authorize_xray_run(state.session, principal, state.version.account_id, run_id)
    result = service._load_xray_result(state.session, principal, state.version.account_id, handle)
    snapshot = state.session.get(PortfolioSnapshotModel, result.snapshot_id)
    if snapshot is None or snapshot.broker_account_id != state.version.account_id:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    current_quality = _snapshot_quality(snapshot, now=state.cutoff)
    # The canonical X-ray policy remains evaluated at its original frozen basis.
    # Its aged valuation is a separate material alert input, never a new X-ray run.
    state.context = replace(
        state.context,
        valuation_at=result.valuation_at.value,
        reporting_currency=result.reporting_currency,
        quality=combine_quality(
            (
                result.portfolio_summary.total.quality,
                QualityState(current_quality.state.value),
            )
        ),
        method_key=result.policy.method_name,
        method_version=result.policy.method_version,
        warnings=tuple(
            d.AlertWarning(code="valuation_warning", message=message)
            for message in current_quality.warnings
        ),
    )
    capture_xray_sources(state, result.source_dependencies, snapshot_id=result.snapshot_id)
    for role, identifier, content in (
        (d.AlertInputRole.INPUT, handle.input_id, result.input_digest),
        (d.AlertInputRole.RESULT, handle.run_id, result.content_digest),
    ):
        state.bindings.append(
            d.AlertCanonicalBinding(
                family=d.AlertCanonicalFamily.XRAY,
                role=role,
                subject_id=identifier,
                content_digest=content,
                method_key=result.policy.method_name,
                method_version=result.policy.method_version,
                numeric_policy_version=result.policy.numeric_policy,
            )
        )
    return d.AlertThresholdInput(
        observation=xray_observation(state.predicate, result, context=state.context)
    )
