"""Authorized original source references and complete saved X-ray/replay proof."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from itertools import islice
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_domain import reports as r
from trading212_domain import xray as x
from trading212_domain.errors import fail_validation
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_sources import (
    ScenarioSensitivityEvidence,
    ScenarioSensitivityObservation,
    ScenarioSensitivitySourceVersion,
)
from trading212_domain.sources import SourceUse
from trading212_domain.xray_codec import encode_xray_policy

from .historical_base import digest
from .historical_service import PostgresHistoricalService
from .report_builder import ReportBuilder
from .report_capture_historical import _sources
from .report_capture_scenario_cells import ScenarioReportWriter
from .report_capture_scenario_proof import ScenarioSourceHeader, capture_scenario_source_headers
from .report_capture_xray import (
    _SOURCE_KINDS,
    _input_proof,
    _result_proof,
    _source_key,
    _source_parents,
)
from .report_capture_xray import _row as xray_row
from .report_capture_xray_proof import capture_xray_semantics
from .scenario_source_models import (
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityVersionModel,
)
from .scenario_source_store import ScenarioCopySources
from .xray_service import PostgresXrayService

type SourceHeaderModel = (
    ScenarioSensitivityVersionModel
    | ScenarioSensitivityObservationModel
    | ScenarioSensitivityEvidenceModel
)
type SourceRecord = (
    ScenarioSensitivitySourceVersion | ScenarioSensitivityObservation | ScenarioSensitivityEvidence
)


def capture_scenario_sensitivity_sources(
    builder: ReportBuilder,
    context: r.ReportContext,
    execution: ScenarioExecutionInput,
    session: Session,
    sources: ScenarioCopySources,
) -> tuple[ScenarioSourceHeader, ...]:
    """Recheck original header lifetimes and REPORT rights; never select coefficient bytes."""
    kinds: tuple[
        tuple[type[SourceHeaderModel], tuple[SourceRecord, ...], str, r.ReportSourceKind], ...
    ] = (
        (
            ScenarioSensitivityVersionModel,
            execution.sensitivities.versions,
            "version_id",
            r.ReportSourceKind.SCENARIO_SENSITIVITY_VERSION,
        ),
        (
            ScenarioSensitivityObservationModel,
            execution.sensitivities.observations,
            "observation_id",
            r.ReportSourceKind.SCENARIO_SENSITIVITY_OBSERVATION,
        ),
        (
            ScenarioSensitivityEvidenceModel,
            execution.sensitivities.evidence,
            "id",
            r.ReportSourceKind.SCENARIO_SENSITIVITY_EVIDENCE,
        ),
    )
    headers: list[ScenarioSourceHeader] = []
    for model, values, field, kind in kinds:
        remaining = iter(values)
        # Keep original-header SQL and temporary maps bounded even at the 100k aggregate.
        while batch := tuple(islice(remaining, 1000)):
            identifiers = tuple(getattr(item, field) for item in batch)
            owned = {
                item.id: item
                for item in session.scalars(
                    select(model).where(
                        model.owner_id == builder.owner_id, model.id.in_(identifiers)
                    )
                )
            }
            for item in batch:
                identifier = getattr(item, field)
                header = owned.get(identifier)
                if (
                    not isinstance(
                        header,
                        (
                            ScenarioSensitivityVersionModel,
                            ScenarioSensitivityObservationModel,
                            ScenarioSensitivityEvidenceModel,
                        ),
                    )
                    or header.content_digest != item.content_digest
                ):
                    fail_validation("Scenario original source header differs.", field="sources")
                sources.original_permit(session, header)
                sources._permit(
                    session, builder.owner_id, header.license_version_id, SourceUse.REPORT
                )
                headers.append(
                    ScenarioSourceHeader(
                        source_kind=kind.value,
                        subject_id=identifier,
                        content_digest=header.content_digest,
                        created_at=header.created_at,
                        expires_at=header.expires_at
                        if isinstance(header, ScenarioSensitivityVersionModel)
                        else None,
                    )
                )
                builder.add_reference(
                    r.ReportSourceReference(
                        key=f"scenario.source.{kind.value}.{identifier}",
                        kind=kind,
                        subject_id=identifier,
                        parent_id=item.source_record_id
                        if isinstance(item, ScenarioSensitivityEvidence)
                        else None,
                        content_digest=header.content_digest,
                        source_at=item.effective_at,
                        first_observed_at=item.first_known_at,
                        provider_id=item.provider_id,
                        license_version_id=item.license_version_id,
                    ),
                    provenance_set_key=context.provenance_set_key,
                )
    for reference in execution.sensitivities.licenses:
        license = sources._permit(
            session, builder.owner_id, reference.license_version_id, SourceUse.REPORT
        )
        if license != reference.license:
            fail_validation("Scenario pinned license differs.", field="license")
        builder.add_license(
            r.ReportLicenseReference(
                version_id=reference.license_version_id,
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
    builder.limit_copy_expiry(sources.copy_deadline)
    capture_scenario_source_headers(
        ScenarioReportWriter(builder, context), execution.sensitivities, tuple(headers)
    )
    return tuple(headers)


def capture_scenario_xray_sources(
    builder: ReportBuilder,
    context: r.ReportContext,
    execution: ScenarioExecutionInput,
    service: PostgresXrayService,
    session: Session,
) -> r.ReportContext:
    source, result, pins = execution.xray_input, execution.xray_result, execution.pins
    key = f"{context.key}.xray"
    child = r.ReportContext(
        key=key,
        family=r.ReportFamily.XRAY,
        method_key=source.policy.method_name,
        method_version=source.policy.method_version,
        valuation_at=result.valuation_at.value,
        source_cutoff_at=result.source_cutoff_at.value,
        quality=result.portfolio_summary.total.quality,
        provenance_set_key=f"{key}.sources",
        coverage_set_key=f"{key}.coverage",
        note_set_key=f"{key}.notes",
        schema_version="3.0.0",
    )
    builder.add_context(child)
    for dependency in result.source_dependencies:
        if dependency.license_version_id is not None:
            for use in (SourceUse.REPORT, SourceUse.STORE, SourceUse.DISPLAY):
                service._permit(session, builder.owner_id, dependency.license_version_id, use)
            license = service._license(session, builder.owner_id, dependency.license_version_id)
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=dependency.license_version_id,
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
        view = service._source_view(session, builder.owner_id, dependency)
        reference = r.ReportSourceReference(
            key=_source_key(dependency.id),
            kind=_SOURCE_KINDS[dependency.reference.kind],
            subject_id=dependency.reference.record_id,
            parent_id=dependency.reference.parent_record_id,
            content_digest=dependency.content_digest,
            source_at=view.source_at,
            first_observed_at=view.first_observed_at,
            provider_id=None if dependency.provider_id is None else UUID(dependency.provider_id),
            license_version_id=dependency.license_version_id,
        )
        for target in (context, child):
            builder.add_reference(reference, provenance_set_key=target.provenance_set_key)
    _source_parents(builder, child, session, service, result, SourceUse.REPORT)
    for role, identifier, content in (
        (r.ReportInputRole.INPUT, pins.xray_input_id, pins.xray_input_digest),
        (r.ReportInputRole.RESULT, pins.xray_run_id, pins.xray_result_digest),
        (
            r.ReportInputRole.POLICY,
            source.policy.id,
            sha256(encode_xray_policy(source.policy)).hexdigest(),
        ),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=r.ReportFamily.XRAY,
                role=role,
                subject_id=identifier,
                content_digest=content,
                method_key=child.method_key,
                method_version=child.method_version,
            )
        )
    _input_proof(builder, child, source)
    _result_proof(builder, child, result)
    capture_xray_semantics(builder, child, source, result)
    capture_scenario_xray_paths(builder, child, execution)
    return child


def capture_scenario_xray_paths(
    builder: ReportBuilder, context: r.ReportContext, execution: ScenarioExecutionInput
) -> None:
    roots: dict[str, x.PositionRoot | x.CashRoot] = {
        item.root.key: item.root for item in execution.xray_input.positions
    }
    roots.update({item.root.key: item.root for item in execution.xray_input.cash})
    if any(path.root_key not in roots for path in execution.xray_result.terminal_paths):
        fail_validation("Scenario X-ray terminal root is absent.", field="sources")

    def rows() -> Iterable[r.ReportRow]:
        for ordinal, path in enumerate(execution.xray_result.terminal_paths):
            root = roots[path.root_key]
            company = next(
                item.normalized_known_weight
                for item in path.dimension_weights
                if item.dimension is x.XrayDimension.COMPANY
            )
            yield xray_row(
                builder,
                context,
                r.ReportTableKey.SCENARIO_XRAY_PATHS_V1,
                f"{context.key}.terminal_path.{ordinal}",
                path,
                extra={
                    "root_kind": "position" if isinstance(root, x.PositionRoot) else "cash",
                    "position_id": root.position_id if isinstance(root, x.PositionRoot) else None,
                    "name": str(path.entity_id)
                    if path.entity_id
                    else str(path.instrument_id)
                    if path.instrument_id
                    else "Cash"
                    if path.explicit_cash
                    else "Unresolved exposure",
                    "normalized_known_weight": company,
                },
            )

    builder.add_table(r.ReportTableKey.SCENARIO_XRAY_PATHS_V1, rows())


def capture_scenario_history_sources(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: ScenarioCalculation,
    execution: ScenarioExecutionInput,
    service: PostgresHistoricalService,
    session: Session,
) -> None:
    if value.replay is None or execution.replay is None:
        return
    child = builder.contexts[f"{context.key}.history"]
    if not isinstance(child, r.ReportContext):
        fail_validation("Scenario context profile differs.", field="context")
    _sources(builder, child, execution.replay.historical_input, service, session, SourceUse.REPORT)
    originals = {(item.kind, item.id): item for item in execution.replay.historical_input.sources}
    for source in value.replay.context.sources:
        if originals.get((source.kind, source.id)) != source:
            fail_validation(
                "Scenario replay context source differs from saved history.", field="sources"
            )
        reference = builder.references[f"historical.source.{source.kind}.{source.id}"]
        builder.add_reference(reference, provenance_set_key=context.provenance_set_key)
