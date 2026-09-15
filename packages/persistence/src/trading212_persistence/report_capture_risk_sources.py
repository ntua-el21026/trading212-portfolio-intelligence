"""Copy original authorized source headers and memberships for a selected risk run."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.risk_execution import RiskExecutionInput
from trading212_domain.risk_result import RiskCalculation
from trading212_domain.sources import SourceUse
from trading212_domain.xray import XrayInput
from trading212_domain.xray_codec import encode_xray_input, encode_xray_policy
from trading212_domain.xray_result import XrayCalculation

from .historical_base import digest
from .historical_service import PostgresHistoricalService
from .report_builder import ReportBuilder
from .report_capture_historical import _sources
from .report_capture_risk_xray import capture_risk_xray_paths
from .report_capture_xray import (
    _SOURCE_KINDS,
    _input_proof,
    _result_proof,
    _source_key,
    _source_parents,
)
from .report_capture_xray_proof import capture_xray_semantics
from .xray_service import PostgresXrayService

if TYPE_CHECKING:
    from .report_capture_risk import RiskReportContexts


def capture_risk_history_sources(
    builder: ReportBuilder,
    contexts: RiskReportContexts,
    value: RiskCalculation,
    execution: RiskExecutionInput,
    service: PostgresHistoricalService,
    session: Session,
) -> None:
    """Recheck licensed source headers, then retain complete physical/input proofs.

    The caller must authorize all copy rights before decoding the execution input.
    This second traversal preserves source metadata and protects the final capture.
    """
    context, actual = contexts.historical, value.history.canonical_performance_context
    _sources(builder, context, execution.historical, service, session, SourceUse.REPORT)
    original = {(source.kind, source.id): source for source in execution.historical.sources}
    for source in actual.sources:
        if original.get((source.kind, source.id)) != source:
            fail_validation(
                "Risk historical context source differs from its input.", field="source"
            )
    references = {
        reference.key: reference
        for reference in builder.references.values()
        if reference.key.startswith("historical.source.")
    }
    for source in execution.historical.sources:
        reference = references[f"historical.source.{source.kind}.{source.id}"]
        for target in (contexts.observed, contexts.modeled):
            builder.add_reference(reference, provenance_set_key=target.provenance_set_key)
    by_subject: dict[str, list[str]] = {}
    for source in actual.sources:
        by_subject.setdefault(source.id, []).append(f"historical.source.{source.kind}.{source.id}")
    for ordinal, issue in enumerate(actual.warnings):
        for identifier in issue.reference_ids:
            keys = by_subject.get(identifier)
            if not keys:
                fail_validation("Risk warning source identity is absent.", field="source")
            for key in keys:
                builder.add_reference(
                    references[key], provenance_set_key=f"{context.key}.warning.{ordinal}.sources"
                )


def capture_risk_xray_sources(
    builder: ReportBuilder,
    contexts: RiskReportContexts,
    value: XrayInput,
    result: XrayCalculation,
    service: PostgresXrayService,
    session: Session,
    *,
    run_id: UUID,
    input_id: UUID,
) -> r.ReportContext:
    """Copy the exact selected X-ray's licensed issuer lineage without recomputing overlap."""
    if (
        value.owner_id != builder.owner_id
        or value.account_id != builder.selection.account_id
        or result.owner_id != builder.owner_id
        or result.account_id != builder.selection.account_id
        or result.snapshot_id != builder.selection.snapshot_id
        or result.input_digest != sha256(encode_xray_input(value)).hexdigest()
    ):
        fail_validation("Risk X-ray proof differs from its selected input.", field="risk_run_id")
    key = f"{contexts.observed.key}.xray"
    context = r.ReportContext(
        key=key,
        family=r.ReportFamily.XRAY,
        method_key=value.policy.method_name,
        method_version=value.policy.method_version,
        valuation_at=result.valuation_at.value,
        source_cutoff_at=result.source_cutoff_at.value,
        quality=result.portfolio_summary.total.quality,
        provenance_set_key=f"{key}.sources",
        coverage_set_key=f"{key}.coverage",
        note_set_key=f"{key}.notes",
        schema_version=r.PREMIUM_REPORT_SCHEMA_VERSION,
    )
    builder.add_context(context)
    for dependency in result.source_dependencies:
        # The loader already authorized the complete selected capture before decode.
        # Recheck current permissions while copying metadata in this transaction.
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
        for target in (context, contexts.modeled, contexts.concentration):
            builder.add_reference(reference, provenance_set_key=target.provenance_set_key)
    _source_parents(builder, context, session, service, result, SourceUse.REPORT)
    for role, identifier, content in (
        (r.ReportInputRole.INPUT, input_id, result.input_digest),
        (r.ReportInputRole.RESULT, run_id, result.content_digest),
        (
            r.ReportInputRole.POLICY,
            value.policy.id,
            sha256(encode_xray_policy(value.policy)).hexdigest(),
        ),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=r.ReportFamily.XRAY,
                role=role,
                subject_id=identifier,
                content_digest=content,
                method_key=context.method_key,
                method_version=context.method_version,
            )
        )
    _input_proof(builder, context, value)
    _result_proof(builder, context, result)
    capture_xray_semantics(builder, context, value, result)
    capture_risk_xray_paths(builder, context, value, result)
    return context
