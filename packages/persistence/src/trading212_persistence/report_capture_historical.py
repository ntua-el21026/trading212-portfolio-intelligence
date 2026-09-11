"""Copy complete canonical historical calculations and immutable activity into reports."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics._historical_core import selected_events
from trading212_application import historical as app
from trading212_domain import historical as d
from trading212_domain import historical_results as h
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_schema import report_tables, table_schema
from trading212_domain.sources import SourceAvailability, SourceUse
from trading212_domain.values import CurrencyCode

from . import source_models as sm
from .historical_base import digest
from .historical_models import HistoricalInputModel, HistoricalPolicyModel, HistoricalRunModel
from .historical_normalization import number, obj
from .historical_publication import composite_header, read_historical_result
from .historical_service import PostgresHistoricalService, Query
from .models import SourceRecordModel
from .report_authorization import ReportAuthorization
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row, capture_table

_HISTORICAL_TABLES = {
    r.ReportTableKey.PERFORMANCE_SUMMARY,
    r.ReportTableKey.PERFORMANCE_POINTS,
    r.ReportTableKey.PERFORMANCE_PERIODS,
    r.ReportTableKey.BENCHMARK_SUMMARY,
    r.ReportTableKey.BENCHMARK_POINTS,
    r.ReportTableKey.BENCHMARK_PERIODS,
    r.ReportTableKey.INCOME_SUMMARY,
    r.ReportTableKey.INCOME_COMPONENTS,
    r.ReportTableKey.INCOME_TOTALS,
    r.ReportTableKey.INCOME_PERIODS,
    r.ReportTableKey.INCOME_REPORTING_PERIODS,
    r.ReportTableKey.CASH_FLOW_SUMMARY,
    r.ReportTableKey.CASH_FLOW_TOTALS,
    r.ReportTableKey.CASH_FLOW_PERIODS,
    r.ReportTableKey.CASH_FLOW_EVENTS,
    r.ReportTableKey.ATTRIBUTION_SUMMARY,
    r.ReportTableKey.ATTRIBUTION_COMPONENTS,
    r.ReportTableKey.ATTRIBUTION_EFFECTS,
    r.ReportTableKey.ACTIVITY,
    r.ReportTableKey.DIVIDENDS,
}
_SOURCE_KINDS: dict[str, r.ReportSourceKind] = {
    "broker_source_record": r.ReportSourceKind.BROKER_SOURCE_RECORD,
    "broker_source_occurrence": r.ReportSourceKind.BROKER_SOURCE_OCCURRENCE,
    "ingestion_run": r.ReportSourceKind.INGESTION_RUN,
    "portfolio_snapshot": r.ReportSourceKind.PORTFOLIO_SNAPSHOT,
    "calculation_run": r.ReportSourceKind.CALCULATION,
    "reconciliation_run": r.ReportSourceKind.RECONCILIATION,
    "price_snapshot": r.ReportSourceKind.PRICE_SNAPSHOT,
    "fx_snapshot": r.ReportSourceKind.FX_SNAPSHOT,
    "corporate_action_snapshot": r.ReportSourceKind.CORPORATE_ACTION,
    "provider_benchmark_snapshot": r.ReportSourceKind.BENCHMARK,
    "instrument_mapping": r.ReportSourceKind.MAPPING,
    "calendar_version": r.ReportSourceKind.CALENDAR,
    "provider_license_version": r.ReportSourceKind.LICENSE,
    "benchmark_version": r.ReportSourceKind.BENCHMARK_VERSION,
    "target_version": r.ReportSourceKind.TARGET_VERSION,
    "classification_evidence": r.ReportSourceKind.HISTORICAL_CLASSIFICATION,
    "historical_evidence": r.ReportSourceKind.HISTORICAL_EVIDENCE,
    "activity_revision_evidence": r.ReportSourceKind.ACTIVITY_REVISION_EVIDENCE,
}

type HistoricalRow = (
    h.PerformanceMetrics
    | h.PerformancePoint
    | h.HistoricalPeriodReturn
    | h.BenchmarkComparisonMetrics
    | h.BenchmarkComparisonPoint
    | h.HistoricalBenchmarkPeriodReturn
    | h.IncomeMetrics
    | h.IncomeComponent
    | h.CurrencyIncomeTotals
    | h.IncomePeriod
    | h.CashFlowMetrics
    | h.CurrencyCashFlowTotals
    | h.HistoricalCashFlowPoint
    | h.AttributionMetrics
    | h.AttributionComponent
    | h.AttributionEffect
    | h.HistoricalUseConsumer
    | h.HistoricalObservationUse
    | h.HistoricalEvidenceUse
    | h.HistoricalConversionUse
)
type HistoricalValue = ReportValue | d.HistoricalMoneyMetric | d.HistoricalRatioMetric


@dataclass(frozen=True, slots=True)
class HistoricalEventLabels:
    ticker: str | None
    description: str | None
    quantity: Decimal | None


def _event_labels(session: Session, value: d.HistoricalInput) -> dict[str, HistoricalEventLabels]:
    identifiers = {UUID(item.identity.source_record_id) for item in value.event_candidates}
    result = {}
    for row in session.scalars(
        select(SourceRecordModel).where(
            SourceRecordModel.broker_account_id == UUID(value.account_id),
            SourceRecordModel.id.in_(identifiers),
        )
    ):
        body = obj(row.sanitized_payload)
        ticker = (
            obj(body.get("order")).get("ticker")
            if row.capability == "historical_orders"
            else body.get("ticker")
        )
        description = body.get("description")
        result[str(row.id)] = HistoricalEventLabels(
            ticker=ticker if isinstance(ticker, str) else None,
            description=description if isinstance(description, str) else None,
            quantity=number(body.get("quantity"))
            if row.capability == "historical_dividends"
            else None,
        )
    if set(result) != {str(identifier) for identifier in identifiers}:
        fail_validation("A captured event source record is unavailable.", field="events")
    return result


def _proof(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    values: Mapping[str, ReportValue],
) -> None:
    builder.add_proof(
        r.ReportProofRelation(
            table=table,
            row=capture_row(builder, context, table, key=key, values=values),
        )
    )


def _metric(
    builder: ReportBuilder,
    context: r.ReportContext,
    *,
    row_key: str,
    column_key: str,
    value: d.HistoricalMoneyMetric | d.HistoricalRatioMetric,
    missing_currency: CurrencyCode,
) -> r.ReportCell:
    key = f"{row_key}.{column_key}"
    reason = None
    if value.reason_code is not None:
        reason = capture_note(
            builder,
            context,
            key=f"{key}.reason",
            text=value.reason_code.value,
            code=value.reason_code.value,
        )
    money = isinstance(value, d.HistoricalMoneyMetric)
    amount: Decimal | None
    currency = None
    if isinstance(value, d.HistoricalMoneyMetric):
        amount = None if value.value is None else value.value.amount
        currency = missing_currency if value.value is None else value.value.currency
    else:
        amount = value.value
    return r.ReportCell(
        kind=r.CellKind.DECIMAL,
        value=amount,
        state=r.CellState(value.availability.value),
        decimal_role=r.DecimalRole.MONEY if money else r.DecimalRole.RATIO,
        currency=currency,
        context_key=context.key,
        reason_key=reason,
        quality=value.quality,
        origin=r.ReportMetricOrigin(value.origin.value),
        coverage_key=value.coverage_key.value,
        method_key=context.method_key,
        method_version=context.method_version,
        provenance_set_key=context.provenance_set_key,
        note_set_key=context.note_set_key,
    )


def _row(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    source: HistoricalRow | None = None,
    *,
    extra: Mapping[str, HistoricalValue] | None = None,
    missing_currency: CurrencyCode | None = None,
) -> r.ReportRow:
    supplied = extra or {}
    if isinstance(source, (h.IncomeComponent, h.CurrencyIncomeTotals, h.CurrencyCashFlowTotals)):
        missing_currency = source.currency
    values: dict[str, ReportValue] = {}
    # The fixed registry controls every name; this is projection of a closed union,
    # never a wildcard dataclass dump or an extensible financial expression.
    for column in table_schema(table).columns:
        value = supplied[column.key] if column.key in supplied else getattr(source, column.key)
        if isinstance(value, (d.HistoricalMoneyMetric, d.HistoricalRatioMetric)):
            values[column.key] = _metric(
                builder,
                context,
                row_key=key,
                column_key=column.key,
                value=value,
                missing_currency=missing_currency or builder.selection.reporting_currency,
            )
        elif isinstance(value, CurrencyCode):
            values[column.key] = value.value
        else:
            values[column.key] = value
    return capture_row(
        builder,
        context,
        table,
        key=key,
        values=values,
        currency=builder.selection.reporting_currency,
    )


def _context(builder: ReportBuilder, result: h.HistoricalCalculation) -> r.ReportContext:
    actual = result.context
    family = r.ReportFamily(result.family)
    context = r.ReportContext(
        key=f"historical.{family.value}",
        family=family,
        method_key=actual.method.name,
        method_version=actual.method.version,
        valuation_at=actual.window.end_at,
        source_cutoff_at=actual.window.source_cutoff_at,
        quality=actual.quality,
        provenance_set_key=f"historical.{family.value}.sources",
        coverage_set_key=f"historical.{family.value}.coverage",
        note_set_key=f"historical.{family.value}.notes",
    )
    builder.add_context(context)
    for index, issue in enumerate(actual.warnings):
        note_key = f"{context.key}.warning.{index}"
        builder.add_note(
            r.ReportNote(
                key=note_key,
                family=family,
                text=issue.reason_code.value,
                kind=r.ReportNoteKind.WARNING,
                code=issue.reason_code.value,
                related_provenance_set_key=f"{note_key}.sources" if issue.reference_ids else None,
            ),
            note_set_key=context.note_set_key,
        )
    assumptions = (
        *actual.assumptions,
        f"accounting_policy_version:{actual.accounting_policy_version}",
        f"source_policy_version:{actual.source_policy_version}",
        f"reconstruction:{actual.reconstruction}",
        *(f"primitive_method:{item.name}:{item.version}" for item in actual.primitive_methods),
    )
    for index, assumption in enumerate(assumptions):
        capture_note(
            builder,
            context,
            key=f"{context.key}.assumption.{index}",
            text=assumption,
            kind=r.ReportNoteKind.ASSUMPTION,
            code="canonical_method_assumption",
        )
    for measure in actual.coverage.measures:
        for label, amount in (
            ("expected_count", measure.expected_count),
            ("available_count", measure.available_count),
            ("complete", measure.complete),
        ):
            builder.add_coverage(
                r.ReportCoverageFact(
                    set_key=context.coverage_set_key,
                    family=family,
                    metric_key=f"{measure.key.value}.{label}",
                    value=r.ReportCell(
                        kind=r.CellKind.BOOLEAN if type(amount) is bool else r.CellKind.INTEGER,
                        value=amount,
                        context_key=context.key,
                    ),
                )
            )
        for index, reason in enumerate(measure.reasons):
            capture_note(
                builder,
                context,
                key=f"{context.key}.coverage.{measure.key.value}.{index}",
                text=reason.value,
                code=reason.value,
            )
    return context


def _sources(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.HistoricalInput,
    service: PostgresHistoricalService,
    session: Session,
    source_use: SourceUse,
) -> None:
    owner = UUID(value.owner_id)
    snapshots: dict[str, type[sm.SourceSnapshotFields]] = {
        "price_snapshot": sm.PriceSnapshotModel,
        "fx_snapshot": sm.FxSnapshotModel,
        "provider_benchmark_snapshot": sm.BenchmarkSnapshotModel,
        "corporate_action_snapshot": sm.CorporateActionSnapshotModel,
    }
    classifications = {item.id: item for item in value.classification_evidence}
    for source in value.sources:
        key = f"historical.source.{source.kind}.{source.id}"
        license_id = UUID(source.id) if source.kind == "provider_license_version" else None
        provider_id = None
        content_digest = source.semantic_digest or digest(source)
        if source.kind in snapshots:
            physical = service._sources._owned(session, owner, snapshots[source.kind], source.id)
            service._sources._snapshot_permit(session, physical)
            if source.semantic_digest != physical.content_digest:
                fail_validation(
                    "Historical source header differs from its immutable input.", field="source"
                )
            provider_id, license_id = physical.provider_id, physical.license_version_id
            content_digest = physical.content_digest
        elif source.kind == "classification_evidence":
            classification = classifications.get(source.id)
            if classification is None:
                fail_validation(
                    "Historical classification is absent from its input.", field="source"
                )
            license_id = UUID(classification.license_version_id)
        if license_id is not None:
            service._sources._permit(session, owner, license_id, source_use)
            license = service._sources._license(session, owner, license_id)
            provider_id = UUID(license.provider_id)
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=license_id,
                    provider_id=provider_id,
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
                key=key,
                kind=_SOURCE_KINDS[source.kind],
                subject_id=UUID(source.id),
                content_digest=content_digest,
                source_at=source.effective_at,
                first_observed_at=source.first_observed_at,
                provider_id=provider_id,
                license_version_id=license_id,
                parent_id=UUID(source.parent_ids[0]) if len(source.parent_ids) == 1 else None,
            ),
            provenance_set_key=context.provenance_set_key,
        )
        _proof(
            builder,
            context,
            r.ReportTableKey.HISTORICAL_SOURCE_DETAILS,
            f"{context.key}.{source.kind}.{source.id}.details",
            {
                "source_key": key,
                "kind": source.kind,
                "semantic_digest": source.semantic_digest,
                "derived_projection_digest": source.derived_projection_digest,
                "original_fingerprint": source.original_fingerprint,
                "version": source.version,
            },
        )
        for ordinal, parent in enumerate(source.parent_ids):
            _proof(
                builder,
                context,
                r.ReportTableKey.HISTORICAL_SOURCE_PARENTS,
                f"{context.key}.{source.kind}.{source.id}.parent.{ordinal}",
                {
                    "source_key": key,
                    "ordinal": ordinal,
                    "parent_id": parent,
                },
            )
    for event in value.event_candidates:
        item = event.identity
        _proof(
            builder,
            context,
            r.ReportTableKey.HISTORICAL_EVENT_IDENTITIES,
            f"{context.key}.event.{item.revision_id}",
            {
                "revision_id": item.revision_id,
                "economic_key": item.economic_key,
                "source_record_id": item.source_record_id,
                "source_occurrence_id": item.source_occurrence_id,
                "economic_at": item.economic_at,
                "first_observed_at": item.first_observed_at,
                "revision_sequence": item.revision_sequence,
                "supersedes_revision_id": item.supersedes_revision_id,
                "record_state": item.record_state,
                "quality": item.quality,
                "kind": event.kind,
                "event_digest": digest(event),
                "correction_of": event.correction_of
                if isinstance(event, d.HistoricalDividend)
                else None,
            },
        )
    reconciliations = tuple(
        source for source in value.sources if source.kind == "reconciliation_run"
    )
    if not reconciliations:
        builder.add_reconciliation(r.ReportReconciliationBinding(key=context.key, absent=True))
    for source in reconciliations:
        builder.add_reconciliation(
            r.ReportReconciliationBinding(
                key=f"{context.key}.{source.id}",
                absent=False,
                run_id=UUID(source.id),
                content_digest=digest(source),
            )
        )
    anchors = {anchor.id: anchor for anchor in value.valuation_anchors}
    if isinstance(value.opening, d.ObservedHistoricalOpening):
        anchors[value.opening.anchor.id] = value.opening.anchor
    for anchor in anchors.values():
        proof = anchor.reconciliation
        key = f"{context.key}.reconciliation.{anchor.id}"
        _proof(
            builder,
            context,
            r.ReportTableKey.HISTORICAL_ANCHOR_RECONCILIATION,
            key,
            {
                "anchor_id": anchor.id,
                "policy_version": proof.policy_version,
                "outcome": proof.outcome,
            },
        )
        for ordinal, line in enumerate(proof.lines):
            _proof(
                builder,
                context,
                r.ReportTableKey.HISTORICAL_RECONCILIATION_LINES,
                f"{key}.line.{ordinal}",
                {
                    "anchor_id": anchor.id,
                    "ordinal": ordinal,
                    "kind": line.kind,
                    "identity": line.identity,
                    "currency": None if line.currency is None else line.currency.value,
                    "expected": line.expected,
                    "observed": line.observed,
                    "residual": line.residual,
                    "tolerance": line.tolerance,
                    "state": line.state,
                },
            )
        for ordinal, identifier in enumerate(proof.anchor_refs):
            _proof(
                builder,
                context,
                r.ReportTableKey.HISTORICAL_RECONCILIATION_ANCHORS,
                f"{key}.anchor.{ordinal}",
                {
                    "anchor_id": anchor.id,
                    "ordinal": ordinal,
                    "reference_id": identifier,
                },
            )


def _uses(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.HistoricalInput,
    result: h.HistoricalCalculation,
) -> None:
    from .report_capture_historical_proof import retained_historical_trace

    uses, conversions = retained_historical_trace(value, result)
    capture_note(
        builder,
        context,
        key=f"{context.key}.source_projection",
        kind=r.ReportNoteKind.ASSUMPTION,
        code="report_source_projection_v1",
        text=(
            "Detailed source uses bind reported series instants, period boundaries, "
            "event conversions and distinct corporate actions. Complete source hashes, "
            "coverage and warnings are retained; the pinned canonical run retains "
            "intermediate daily reconstruction traces."
        ),
    )
    for use in uses:
        key = f"{context.key}.use.{use.use_key}"
        consumer = _row(
            builder,
            context,
            r.ReportTableKey.HISTORICAL_USE_CONSUMERS,
            f"{key}.consumer",
            use.consumer,
            extra={"use_key": use.use_key},
        )
        builder.add_proof(
            r.ReportProofRelation(table=r.ReportTableKey.HISTORICAL_USE_CONSUMERS, row=consumer)
        )
        if isinstance(use, h.HistoricalObservationUse):
            leg = use.conversion_leg
            row = _row(
                builder,
                context,
                r.ReportTableKey.HISTORICAL_OBSERVATION_USES,
                key,
                use,
                extra={
                    "conversion_key": None if leg is None else leg.conversion_key,
                    "leg_ordinal": None if leg is None else leg.ordinal,
                    "direction": None if leg is None else leg.direction,
                    "base": None if leg is None else leg.base.value,
                    "quote": None if leg is None else leg.quote.value,
                },
            )
            table = r.ReportTableKey.HISTORICAL_OBSERVATION_USES
        elif isinstance(use, h.HistoricalEvidenceUse):
            table = r.ReportTableKey.HISTORICAL_EVIDENCE_USES
            row = _row(builder, context, table, key, use)
        else:
            table = r.ReportTableKey.HISTORICAL_MISSING_USES
            expected = use.expected
            row = _row(
                builder,
                context,
                table,
                key,
                extra={
                    "use_key": use.use_key,
                    "role": use.role,
                    "use_at": use.use_at,
                    "knowledge_cutoff_at": use.knowledge_cutoff_at,
                    "expected_kind": expected.kind,
                    "series_id": expected.series_id
                    if isinstance(expected, h.HistoricalExpectedSeries)
                    else None,
                    "base": expected.base.value
                    if isinstance(expected, h.HistoricalExpectedFx)
                    else None,
                    "quote": expected.quote.value
                    if isinstance(expected, h.HistoricalExpectedFx)
                    else None,
                    "calendar_id": use.calendar_ref.id,
                    "calendar_version": use.calendar_ref.version,
                    "expected_session": use.expected_session,
                    "reason": use.reason,
                },
            )
            for ordinal, candidate in enumerate(use.candidate_snapshot_ids):
                _proof(
                    builder,
                    context,
                    r.ReportTableKey.HISTORICAL_USE_CANDIDATES,
                    f"{key}.candidate.{ordinal}",
                    {
                        "use_key": use.use_key,
                        "ordinal": ordinal,
                        "candidate_snapshot_id": candidate,
                    },
                )
        builder.add_proof(r.ReportProofRelation(table=table, row=row))
    for conversion in conversions:
        key = f"{context.key}.conversion.{conversion.conversion_key}"
        builder.add_proof(
            r.ReportProofRelation(
                table=r.ReportTableKey.HISTORICAL_CONVERSION_USES,
                row=_row(
                    builder, context, r.ReportTableKey.HISTORICAL_CONVERSION_USES, key, conversion
                ),
            )
        )
        for ordinal, leg_key in enumerate(conversion.leg_use_keys):
            _proof(
                builder,
                context,
                r.ReportTableKey.HISTORICAL_CONVERSION_LEGS,
                f"{key}.leg.{ordinal}",
                {
                    "conversion_key": conversion.conversion_key,
                    "ordinal": ordinal,
                    "leg_use_key": leg_key,
                },
            )


def _events(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.HistoricalInput,
    points: tuple[h.HistoricalCashFlowPoint, ...],
    table: r.ReportTableKey,
    labels: Mapping[str, HistoricalEventLabels],
) -> Iterable[r.ReportRow]:
    revisions = {event.identity.revision_id: event for event in value.event_candidates}
    for point in points:
        event = revisions.get(point.event_revision_id)
        if event is None:
            fail_validation("Canonical event revision is absent from its input.", field="events")
        identity = event.identity
        display = labels.get(identity.source_record_id)
        ticker = None if display is None else display.ticker
        key = f"{context.key}.{table.value}.{identity.revision_id}"
        quantity: ReportValue = event.quantity if isinstance(event, d.HistoricalExecution) else None
        if isinstance(event, d.HistoricalDividend):
            quantity = None if display is None else display.quantity
            if quantity is None:
                reason_key = capture_note(
                    builder,
                    context,
                    key=f"{key}.quantity.reason",
                    text="The immutable provider dividend record does not supply quantity.",
                    code="provider_quantity_unavailable",
                )
                quantity = r.ReportCell(
                    kind=r.CellKind.DECIMAL,
                    value=None,
                    state=r.CellState.UNAVAILABLE,
                    decimal_role=r.DecimalRole.QUANTITY,
                    context_key=context.key,
                    reason_key=reason_key,
                )
        if table is r.ReportTableKey.DIVIDENDS:
            if not isinstance(event, d.HistoricalDividend):
                continue
            yield _row(
                builder,
                context,
                table,
                key,
                extra={
                    "record_id": identity.source_record_id,
                    "revision_id": identity.revision_id,
                    "paid_on": identity.economic_at.date(),
                    "ticker": ticker,
                    "net": event.net,
                    "gross": event.gross,
                    "tax": event.withholding,
                    "quantity": quantity,
                },
                missing_currency=event.net.currency,
            )
        elif table is r.ReportTableKey.ACTIVITY:
            direction = (
                event.side
                if isinstance(event, d.HistoricalExecution)
                else event.kind
                if isinstance(event, d.HistoricalExternalFlow)
                else point.classification
            )
            yield _row(
                builder,
                context,
                table,
                key,
                extra={
                    "record_id": identity.source_record_id,
                    "revision_id": identity.revision_id,
                    "occurred_at": identity.economic_at,
                    "type": point.kind,
                    "direction": direction,
                    "amount": point.native_amount,
                    "ticker": ticker,
                    "quantity": quantity,
                    "description": None if display is None else display.description,
                    "status": identity.record_state,
                    "correction_of": point.correction_of,
                },
            )
        else:
            yield _row(builder, context, table, key, point)
        # Full source membership comes from the immutable identity, not the public
        # cash-flow point's capped source_ref_ids preview.
        ids = {identity.source_record_id, identity.source_occurrence_id}
        for reference in builder.references.values():
            if str(reference.subject_id) in ids:
                builder.add_reference(reference, provenance_set_key=f"{key}.sources")


def project_historical(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.HistoricalInput,
    result: h.HistoricalCalculation,
    *,
    labels: Mapping[str, HistoricalEventLabels] | None = None,
) -> None:
    """Pure scalar projection after the caller has authorized the full canonical records."""
    requested = set(report_tables(builder.selection))
    state = SourceAvailability(result.context.availability.value)
    reason = (
        None
        if state is SourceAvailability.AVAILABLE
        else capture_note(
            builder,
            context,
            key=f"{context.key}.availability",
            text=result.context.availability.value,
            code="canonical_family_availability",
        )
    )

    def put(table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> None:
        if table in requested:
            capture_table(builder, table, rows, state=state, reason_key=reason)

    def rows(table: r.ReportTableKey, records: Iterable[HistoricalRow]) -> Iterable[r.ReportRow]:
        for ordinal, record in enumerate(records):
            yield _row(builder, context, table, f"{context.key}.{table.value}.{ordinal}", record)

    if isinstance(result, h.PerformanceCalculation):
        put(
            r.ReportTableKey.PERFORMANCE_SUMMARY,
            rows(r.ReportTableKey.PERFORMANCE_SUMMARY, (result.summary,)),
        )
        put(
            r.ReportTableKey.PERFORMANCE_POINTS,
            rows(r.ReportTableKey.PERFORMANCE_POINTS, result.points),
        )
        put(
            r.ReportTableKey.PERFORMANCE_PERIODS,
            rows(
                r.ReportTableKey.PERFORMANCE_PERIODS,
                (*result.rolling_returns, *result.calendar_returns),
            ),
        )
        selected, _ = selected_events(value, value.selection.window.source_cutoff_at)
        previous = value.selection.window.start_at
        for point in result.points:
            revisions = point.flow_revision_ids
            if point.flow_revision_omitted_count:
                revisions = tuple(
                    event.identity.revision_id
                    for event in selected
                    if isinstance(event, d.HistoricalExternalFlow)
                    and previous <= event.identity.economic_at < point.valuation_at
                )
                if len(revisions) != point.flow_count or not set(point.flow_revision_ids) <= set(
                    revisions
                ):
                    fail_validation(
                        "Canonical performance memberships disagree with its input.",
                        field="flow_revision_ids",
                    )
            previous = point.valuation_at
            for ordinal, revision in enumerate(revisions):
                _proof(
                    builder,
                    context,
                    r.ReportTableKey.HISTORICAL_EVENT_MEMBERSHIPS,
                    f"{context.key}.point.{point.ordinal}.event.{ordinal}",
                    {
                        "parent_key": f"{context.key}.performance_points.{point.ordinal}",
                        "ordinal": ordinal,
                        "event_revision_id": revision,
                    },
                )
    elif isinstance(result, h.BenchmarkCalculation):
        put(
            r.ReportTableKey.BENCHMARK_SUMMARY,
            rows(r.ReportTableKey.BENCHMARK_SUMMARY, (result.summary,)),
        )
        put(
            r.ReportTableKey.BENCHMARK_POINTS,
            rows(r.ReportTableKey.BENCHMARK_POINTS, result.points),
        )
        put(
            r.ReportTableKey.BENCHMARK_PERIODS,
            rows(
                r.ReportTableKey.BENCHMARK_PERIODS,
                (*result.rolling_returns, *result.calendar_returns),
            ),
        )
    elif isinstance(result, h.IncomeCalculation):
        put(
            r.ReportTableKey.INCOME_SUMMARY,
            rows(r.ReportTableKey.INCOME_SUMMARY, (result.summary,)),
        )
        put(
            r.ReportTableKey.INCOME_COMPONENTS,
            (
                _row(
                    builder,
                    context,
                    r.ReportTableKey.INCOME_COMPONENTS,
                    f"{context.key}.component.{kind}.{index}",
                    item,
                    extra={"grouping": kind},
                )
                for kind, members in (
                    ("instrument", result.instrument_rows),
                    ("group", result.group_rows),
                )
                for index, item in enumerate(members)
            ),
        )
        put(
            r.ReportTableKey.INCOME_TOTALS,
            (
                _row(
                    builder,
                    context,
                    r.ReportTableKey.INCOME_TOTALS,
                    f"{context.key}.total.{basis}.{index}",
                    item,
                    extra={"basis": basis},
                )
                for basis, members in (
                    ("native", result.native_currency_totals),
                    ("reporting", (result.reporting_totals,)),
                )
                for index, item in enumerate(members)
            ),
        )
        put(
            r.ReportTableKey.INCOME_PERIODS,
            (
                _row(
                    builder,
                    context,
                    r.ReportTableKey.INCOME_PERIODS,
                    f"{context.key}.period.{ordinal}.{index}",
                    item,
                    extra={"start_date": period.start_date, "end_date": period.end_date},
                )
                for ordinal, period in enumerate(result.period_rows)
                for index, item in enumerate(period.totals)
            ),
        )
        put(
            r.ReportTableKey.INCOME_REPORTING_PERIODS,
            rows(r.ReportTableKey.INCOME_REPORTING_PERIODS, result.period_rows),
        )
        put(
            r.ReportTableKey.DIVIDENDS,
            _events(
                builder, context, value, result.events, r.ReportTableKey.DIVIDENDS, labels or {}
            ),
        )
    elif isinstance(result, h.CashFlowCalculation):
        put(
            r.ReportTableKey.CASH_FLOW_SUMMARY,
            rows(r.ReportTableKey.CASH_FLOW_SUMMARY, (result.summary,)),
        )
        put(
            r.ReportTableKey.CASH_FLOW_TOTALS,
            (
                _row(
                    builder,
                    context,
                    r.ReportTableKey.CASH_FLOW_TOTALS,
                    f"{context.key}.total.{basis}.{index}",
                    item,
                    extra={"basis": basis},
                )
                for basis, members in (
                    ("native", result.native_currency_totals),
                    ("reporting", (result.reporting_totals,)),
                )
                for index, item in enumerate(members)
            ),
        )
        put(
            r.ReportTableKey.CASH_FLOW_PERIODS,
            (
                _row(
                    builder,
                    context,
                    r.ReportTableKey.CASH_FLOW_PERIODS,
                    f"{context.key}.period.{ordinal}.{basis}.{index}",
                    item,
                    extra={
                        "start_date": period.start_date,
                        "end_date": period.end_date,
                        "basis": basis,
                    },
                )
                for ordinal, period in enumerate(result.period_rows)
                for basis, members in (
                    ("native", period.native_totals),
                    ("reporting", (period.reporting_totals,)),
                )
                for index, item in enumerate(members)
            ),
        )
        for table in (r.ReportTableKey.CASH_FLOW_EVENTS, r.ReportTableKey.ACTIVITY):
            put(table, _events(builder, context, value, result.events, table, labels or {}))
    else:
        put(
            r.ReportTableKey.ATTRIBUTION_SUMMARY,
            rows(r.ReportTableKey.ATTRIBUTION_SUMMARY, (result.summary,)),
        )
        put(
            r.ReportTableKey.ATTRIBUTION_COMPONENTS,
            rows(r.ReportTableKey.ATTRIBUTION_COMPONENTS, result.rows),
        )
        put(
            r.ReportTableKey.ATTRIBUTION_EFFECTS,
            (
                _row(
                    builder,
                    context,
                    r.ReportTableKey.ATTRIBUTION_EFFECTS,
                    f"{context.key}.effect.{parent_index}.{ordinal}",
                    item,
                    extra={"parent_key": parent},
                )
                for parent_index, (parent, effects) in enumerate(
                    (
                        ("portfolio", result.effects),
                        *((item.key, item.effects) for item in result.rows),
                    )
                )
                for ordinal, item in enumerate(effects)
            ),
        )
    if (
        isinstance(result, (h.IncomeCalculation, h.CashFlowCalculation))
        and r.ReportTableKey.CASH_FLOW_EVENTS not in requested
    ):
        for row in _events(
            builder, context, value, result.events, r.ReportTableKey.CASH_FLOW_EVENTS, labels or {}
        ):
            builder.add_proof(
                r.ReportProofRelation(table=r.ReportTableKey.CASH_FLOW_EVENTS, row=row)
            )
    _uses(builder, context, value, result)
    from .report_capture_historical_proof import capture_historical_semantics

    capture_historical_semantics(builder, context, value, result)


def _capture_composite_binding(
    builder: ReportBuilder,
    session: Session,
    owner_id: UUID,
    run: HistoricalRunModel,
    result: h.HistoricalCalculation,
) -> None:
    if not isinstance(result, h.BenchmarkCalculation) or result.composite is None:
        return
    snapshot = composite_header(session, owner_id, run, result)
    builder.add_binding(
        r.ReportBinding(
            family=r.ReportFamily.BENCHMARK,
            role=r.ReportInputRole.SNAPSHOT,
            subject_id=UUID(snapshot.id),
            parent_id=run.id,
            content_digest=snapshot.content_digest,
            method_key=snapshot.method.name,
            method_version=snapshot.method.version,
        )
    )


def capture_historical(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
    source_use: SourceUse,
) -> None:
    selected = set(report_tables(builder.selection)) & _HISTORICAL_TABLES
    if not selected:
        return
    if source_use not in (SourceUse.REPORT, SourceUse.EXPORT):
        fail_validation("A report/export copy permission is required.", field="source_use")
    authorization.check(session, now=clock())
    principal = authorization.as_principal(now=clock())
    service = PostgresHistoricalService(
        sessions, cursor_signing_key=cursor_signing_key, clock=clock, required_copy_use=source_use
    )
    selection = builder.selection
    window = d.HistoricalWindow(
        start_date=selection.start_date,
        end_date=selection.end_date,
        source_cutoff_at=selection.source_cutoff_at,
        reporting_currency=selection.reporting_currency,
    )
    queries: list[tuple[str, Query]] = []
    if any(table.value.startswith("performance_") for table in selected):
        queries.append(("performance", app.PerformanceSummaryQuery(window=window)))
    if any(table.value.startswith("benchmark_") for table in selected):
        if selection.benchmark_version_id is None:
            fail_validation(
                "Benchmark capture requires its immutable version.", field="benchmark_version_id"
            )
        queries.append(
            (
                "benchmark",
                app.BenchmarkComparisonQuery(
                    window=window, benchmark_version_id=str(selection.benchmark_version_id)
                ),
            )
        )
    if (
        any(table.value.startswith("income_") for table in selected)
        or r.ReportTableKey.DIVIDENDS in selected
    ):
        queries.append(("income", app.DividendIntelligenceQuery(window=window)))
    if (
        any(table.value.startswith("cash_flow_") for table in selected)
        or r.ReportTableKey.ACTIVITY in selected
    ):
        queries.append(("cash_flow", app.CashFlowIntelligenceQuery(window=window)))
    if any(table.value.startswith("attribution_") for table in selected):
        queries.append(("attribution", app.AttributionQuery(window=window)))
    for family, query in queries:
        authorization.check(session, now=clock())
        capture, run, stored, result = read_historical_result(
            service,
            session,
            principal,
            authorization.owner_id,
            authorization.account_id,
            query,
            family,
        )
        context = _context(builder, result)
        _sources(builder, context, capture.input, service, session, source_use)
        for index, issue in enumerate(result.context.warnings):
            references = set(issue.reference_ids)
            for reference in builder.references.values():
                if str(reference.subject_id) in references:
                    builder.add_reference(
                        reference, provenance_set_key=f"{context.key}.warning.{index}.sources"
                    )
        for role, identifier, content in (
            (r.ReportInputRole.INPUT, UUID(capture.id), capture.input_digest),
            (r.ReportInputRole.RESULT, run.id, stored.content_digest),
        ):
            builder.add_binding(
                r.ReportBinding(
                    family=context.family,
                    role=role,
                    subject_id=identifier,
                    content_digest=content,
                    method_key=result.context.method.name,
                    method_version=result.context.method.version,
                )
            )
        _capture_composite_binding(builder, session, authorization.owner_id, run, result)
        input_row = service._owned(
            session, authorization.owner_id, HistoricalInputModel, capture.id
        )
        if input_row.policy_id is not None:
            policy = service._owned(
                session, authorization.owner_id, HistoricalPolicyModel, input_row.policy_id
            )
            builder.add_binding(
                r.ReportBinding(
                    family=context.family,
                    role=r.ReportInputRole.POLICY,
                    subject_id=policy.id,
                    content_digest=policy.content_digest,
                    method_key=result.context.method.name,
                    method_version=result.context.method.version,
                )
            )
        project_historical(
            builder, context, capture.input, result, labels=_event_labels(session, capture.input)
        )
        authorization.check(session, now=clock())
