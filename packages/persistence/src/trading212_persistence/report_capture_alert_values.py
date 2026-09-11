"""Lossless public alert values and licensed proof in fixed private export tables."""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from uuid import UUID

from trading212_domain import alerts as a
from trading212_domain import reports as r
from trading212_domain.alert_serialization import alert_record_digest
from trading212_domain.values import CurrencyCode

from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row
from .source_store import digest


def emit(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    values: dict[str, ReportValue | CurrencyCode],
) -> None:
    builder.append_dataset_row(
        table,
        capture_row(
            builder,
            context,
            table,
            key=key,
            values={
                key: value.value if isinstance(value, CurrencyCode) else value
                for key, value in values.items()
            },
            currency=builder.selection.reporting_currency,
        ),
    )


def _scalar(
    value: Decimal | int | bool | None, *, currency: CurrencyCode | None = None
) -> r.ReportCell:
    kind = (
        r.CellKind.DECIMAL
        if type(value) is Decimal
        else r.CellKind.INTEGER
        if type(value) is int
        else r.CellKind.BOOLEAN
    )
    return r.ReportCell(
        kind=kind,
        value=value,
        state=r.CellState.AVAILABLE if value is not None else r.CellState.NOT_APPLICABLE,
        decimal_role=(r.DecimalRole.MONEY if currency else r.DecimalRole.RATIO)
        if kind is r.CellKind.DECIMAL
        else None,
        currency=currency if kind is r.CellKind.DECIMAL else None,
    )


def project_version(
    builder: ReportBuilder, context: r.ReportContext, version: a.AlertRuleVersion
) -> None:
    definition, schedule = version.definition, version.definition.schedule
    key = f"alert.version.{version.id}"
    emit(
        builder,
        context,
        r.ReportTableKey.ALERT_RULE_VERSIONS,
        key,
        {
            "rule_version_id": version.id,
            "rule_id": version.rule_id,
            "account_id": version.account_id,
            "version_number": version.version_number,
            "created_at": version.created_at,
            "content_digest": version.content_digest,
            "name": definition.name,
            "severity": definition.severity,
            "quality_policy": definition.quality_policy,
            "cooldown_seconds": definition.cooldown_seconds,
            "source_policy_version_id": definition.source_policy_version_id,
            "remediation": definition.remediation,
            "schedule_kind": schedule.kind,
            "anchor_at": schedule.anchor_at
            if isinstance(schedule, a.AlertIntervalSchedule)
            else None,
            "interval_seconds": schedule.interval_seconds
            if isinstance(schedule, a.AlertIntervalSchedule)
            else None,
            "minute_utc": schedule.minute_utc
            if isinstance(schedule, a.AlertDailyUtcSchedule)
            else None,
        },
    )
    predicate = definition.predicate
    values: dict[str, ReportValue | CurrencyCode] = {
        field.name: getattr(predicate, field.name) for field in fields(predicate)
    }
    values["rule_version_id"] = version.id
    values["threshold"] = _scalar(predicate.threshold, currency=predicate.currency)
    emit(builder, context, r.ReportTableKey.ALERT_PREDICATES, key, values)
    for destination in definition.destination_ids:
        emit(
            builder,
            context,
            r.ReportTableKey.ALERT_RULE_DESTINATIONS,
            f"{key}.{destination}",
            {
                "rule_version_id": version.id,
                "destination_id": destination,
            },
        )


def _context(
    builder: ReportBuilder,
    evaluation_id: UUID,
    ordinal: int,
    value: a.AlertResultContext,
    sources: dict[str, r.ReportSourceReference],
) -> r.ReportContext:
    prefix = f"alert.{evaluation_id.hex}.context.{ordinal}"
    context = r.ReportContext(
        key=prefix,
        family=r.ReportFamily.ALERTS,
        method_key=value.method_key,
        method_version=value.method_version,
        valuation_at=value.valuation_at,
        source_cutoff_at=value.source_cutoff_at,
        quality=value.quality,
        provenance_set_key=f"{prefix}.sources",
        coverage_set_key=f"{prefix}.coverage",
        note_set_key=f"{prefix}.notes",
    )
    builder.add_context(context)
    emit(
        builder,
        context,
        r.ReportTableKey.ALERT_CONTEXT_DETAILS,
        prefix,
        {
            "evaluation_id": evaluation_id,
            "original_key": value.key,
            "context_key": context.key,
            "reporting_currency": value.reporting_currency,
            "reconciliation_id": value.reconciliation_id,
        },
    )
    for index, key in enumerate(value.source_reference_keys):
        source = sources[key]
        builder.add_reference(source, provenance_set_key=context.provenance_set_key)
        emit(
            builder,
            context,
            r.ReportTableKey.ALERT_CONTEXT_MEMBERS,
            f"{prefix}.source.{index}",
            {
                "context_key": context.key,
                "role": "source",
                "ordinal": index,
                "note_key": None,
                "source_key": source.key,
            },
        )
    for fact in value.coverage:
        for name in ("expected_count", "available_count", "complete", "covered_fraction"):
            builder.add_coverage(
                r.ReportCoverageFact(
                    set_key=context.coverage_set_key,
                    family=context.family,
                    metric_key=f"{fact.key}.{name}",
                    value=replace(_scalar(getattr(fact, name)), context_key=context.key),
                )
            )
    for index, warning in enumerate(value.warnings):
        note = capture_note(
            builder,
            context,
            key=f"{prefix}.warning.{index}",
            text=warning.message,
            kind=r.ReportNoteKind.WARNING,
            code=warning.code,
        )
        for member, key in enumerate(warning.source_reference_keys):
            emit(
                builder,
                context,
                r.ReportTableKey.ALERT_CONTEXT_MEMBERS,
                f"{prefix}.warning.{index}.{member}",
                {
                    "context_key": context.key,
                    "role": "warning_source",
                    "ordinal": member,
                    "note_key": note,
                    "source_key": sources[key].key,
                },
            )
    for index, text in enumerate(value.assumptions):
        capture_note(
            builder,
            context,
            key=f"{prefix}.assumption.{index}",
            text=text,
            kind=r.ReportNoteKind.ASSUMPTION,
            code="canonical_assumption",
        )
    return context


def _observation_cell(
    builder: ReportBuilder, context: r.ReportContext, key: str, value: a.AlertObservedMetric
) -> r.ReportCell:
    reason_key = (
        capture_note(
            builder, context, key=f"{key}.reason", text=value.reason.value, code=value.reason.value
        )
        if value.reason
        else None
    )
    bound_key = f"{key}.bound"
    builder.add_bound(
        r.ReportBoundFact(
            key=bound_key,
            family=context.family,
            kind=r.ReportBoundKind(value.bound.value),
            positive_below_quantum=value.positive_below_quantum,
        )
    )
    kind = {
        a.AlertMetricKind.DECIMAL: r.CellKind.DECIMAL,
        a.AlertMetricKind.INTEGER: r.CellKind.INTEGER,
        a.AlertMetricKind.BOOLEAN: r.CellKind.BOOLEAN,
        a.AlertMetricKind.EVENT: r.CellKind.BOOLEAN,
    }[value.kind]
    return r.ReportCell(
        kind=kind,
        value=value.value,
        state=r.CellState(value.availability.value),
        decimal_role=(r.DecimalRole.MONEY if value.currency else r.DecimalRole.RATIO)
        if kind is r.CellKind.DECIMAL
        else None,
        currency=value.currency if kind is r.CellKind.DECIMAL else None,
        context_key=context.key,
        reason_key=reason_key,
        bound_key=bound_key,
        quality=value.quality,
        origin=r.ReportMetricOrigin(value.origin.value),
        coverage_key=context.coverage_set_key,
        method_key=context.method_key,
        method_version=context.method_version,
        provenance_set_key=context.provenance_set_key,
        note_set_key=context.note_set_key,
    )


def project_evaluation(
    builder: ReportBuilder,
    metadata: r.ReportContext,
    *,
    evaluation_id: UUID,
    captured: a.AlertEvaluationInput,
    result: a.AlertEvaluationResult,
) -> None:
    """Copy canonical public outputs and actual sources; never private comparison bases."""
    prefix = f"alert.{evaluation_id.hex}"
    sources = {}
    for source in captured.source_references:
        reference = r.ReportSourceReference(
            key=f"alert.source.{alert_record_digest(source)}",
            kind=source.kind,
            subject_id=source.subject_id,
            content_digest=source.content_digest,
            parent_id=source.parent_id,
            source_at=source.effective_at,
            first_observed_at=source.first_observed_at,
            provider_id=source.provider_id,
            license_version_id=source.license_version_id,
        )
        sources[source.key] = reference
        builder.add_reference(reference, provenance_set_key=metadata.provenance_set_key)
        emit(
            builder,
            metadata,
            r.ReportTableKey.ALERT_SOURCE_REFERENCES,
            f"{prefix}.source.{len(sources)}",
            {
                "evaluation_id": evaluation_id,
                "original_key": source.key,
                "source_key": reference.key,
                "expires_at": source.expires_at,
            },
        )
    for license in captured.licenses:
        builder.add_license(
            r.ReportLicenseReference(
                version_id=UUID(license.id),
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
    for index, binding in enumerate(captured.canonical_bindings):
        emit(
            builder,
            metadata,
            r.ReportTableKey.ALERT_CANONICAL_BINDINGS,
            f"{prefix}.binding.{index}",
            {
                "evaluation_id": evaluation_id,
                "family": binding.family,
                "role": binding.role,
                "subject_id": binding.subject_id,
                "content_digest": binding.content_digest,
                "parent_id": binding.parent_id,
                "method_key": binding.method_key,
                "method_version": binding.method_version,
                "numeric_policy_version": binding.numeric_policy_version,
            },
        )
    contexts = {
        value.key: _context(builder, evaluation_id, index, value, sources)
        for index, value in enumerate(result.contexts)
    }
    candidates = (
        {(event.identity, event.revision_id): event for event in captured.payload.events}
        if isinstance(captured.payload, a.AlertEventBatchInput)
        else {}
    )
    observed = (
        ((result.observation, None),)
        if result.observation is not None
        else tuple((decision.observation, decision) for decision in result.event_decisions)
    )
    for index, (value, decision) in enumerate(observed):
        context, key = contexts[value.context_key], f"{prefix}.observation.{index}"
        event = candidates.get((decision.identity, decision.revision_id)) if decision else None
        emit(
            builder,
            context,
            r.ReportTableKey.ALERT_OBSERVATIONS,
            key,
            {
                "evaluation_id": evaluation_id,
                "event_identity": decision.identity if decision else None,
                "revision_id": decision.revision_id if decision else None,
                "correction_of": decision.correction_of if decision else None,
                "metric": value.metric,
                "kind": value.kind,
                "observed": _observation_cell(builder, context, key, value),
                "observed_currency": value.currency,
                "availability": value.availability,
                "bound": value.bound,
                "positive_below_quantum": value.positive_below_quantum,
                "decision": decision.decision if decision else result.decision,
                "outcome": decision.outcome if decision else result.outcome,
                "reason": decision.reason if decision else result.reason,
                "deduplication_digest": decision.deduplication_digest if decision else None,
                "economic_at": event.economic_at if event else None,
                "first_eligible_at": event.first_eligible_at if event else None,
                "instrument_id": event.instrument_id if event else None,
                "activity_kind": event.activity_kind if event else None,
                "capability_family": event.capability_family if event else None,
                "report_type": event.report_type if event else None,
                "report_outcome": event.report_outcome if event else None,
                "net_amount": event.net_amount if event else None,
            },
        )
    for index, conversion in enumerate(captured.fx_conversions):
        key = f"{prefix}.fx.{index}"
        reason = (
            capture_note(
                builder,
                metadata,
                key=f"{key}.reason",
                text=conversion.reason.value,
                code=conversion.reason.value,
            )
            if conversion.reason
            else None
        )
        emit(
            builder,
            metadata,
            r.ReportTableKey.ALERT_FX_CONVERSIONS,
            key,
            {
                "evaluation_id": evaluation_id,
                "ordinal": index,
                "original": conversion.original,
                "reporting_currency": conversion.reporting_currency,
                "converted": r.ReportCell(
                    kind=r.CellKind.DECIMAL,
                    value=conversion.converted.amount if conversion.converted else None,
                    state=r.CellState.AVAILABLE
                    if conversion.converted
                    else r.CellState.UNAVAILABLE,
                    decimal_role=r.DecimalRole.MONEY,
                    currency=conversion.reporting_currency,
                    reason_key=reason,
                    context_key=metadata.key,
                ),
                "reason": conversion.reason,
            },
        )
        for ordinal, leg in enumerate(conversion.legs):
            leg_key = f"{key}.{ordinal}"
            leg_reason = (
                capture_note(
                    builder,
                    metadata,
                    key=f"{leg_key}.reason",
                    text=leg.reason.value,
                    code=leg.reason.value,
                )
                if leg.reason
                else None
            )
            emit(
                builder,
                metadata,
                r.ReportTableKey.ALERT_FX_LEGS,
                leg_key,
                {
                    "evaluation_id": evaluation_id,
                    "conversion_ordinal": index,
                    "ordinal": ordinal,
                    "base": leg.base,
                    "quote": leg.quote,
                    "rate": r.ReportCell(
                        kind=r.CellKind.DECIMAL,
                        value=leg.rate,
                        state=r.CellState.AVAILABLE
                        if leg.rate is not None
                        else r.CellState.UNAVAILABLE,
                        decimal_role=r.DecimalRole.FX,
                        reason_key=leg_reason,
                        context_key=metadata.key,
                    ),
                    "source_key": sources[leg.source_reference_key].key,
                    "snapshot_id": leg.snapshot_id,
                    "provider_id": leg.provider_id,
                    "observed_at": leg.observed_at,
                    "inverse": leg.inverse,
                    "reason": leg.reason,
                },
            )
