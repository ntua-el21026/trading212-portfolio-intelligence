"""Health of explicitly named immutable sources, using only declared coverage universes."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics._decimal import add, divide, persisted_decimal, subtract
from trading212_analytics.portfolio import convert_money
from trading212_domain import alerts as d
from trading212_domain.enums import QualityState
from trading212_domain.historical_serialization import (
    historical_result_digest,
    historical_result_from_json,
)
from trading212_domain.reports import ReportSourceKind
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode, Instant, Money

from .alert_capture_common import AlertCaptureState, AlertCaptureUnavailable, bounded
from .alert_capture_fx import capture_physical, convert_captured_money
from .alert_capture_portfolio import _quotes, capture_snapshot, selected_snapshot
from .historical_base import REFERENCE_MODELS
from .historical_models import (
    HistoricalClassificationModel,
    HistoricalDependencyModel,
    HistoricalEvidenceModel,
    HistoricalInputModel,
    HistoricalRunModel,
)
from .historical_service import PostgresHistoricalService
from .models import SnapshotCashModel, SnapshotPositionModel
from .planning_inputs import digest
from .planning_models import AnalyticsRunModel
from .source_models import (
    BenchmarkSnapshotModel,
    CorporateActionSnapshotModel,
    FxSnapshotModel,
    PriceSnapshotModel,
    ProviderLicenseVersionModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
    SourceSnapshotFields,
)
from .source_store import license_view
from .xray_catalog_models import (
    ClassificationAssignmentModel,
    ClassificationSnapshotAssignmentModel,
    ClassificationSnapshotInstrumentModel,
    ClassificationSnapshotModel,
    ConstituentSnapshotModel,
    XrayTaxonomyModel,
)

_HISTORY_KINDS = {
    "broker_source_record": ReportSourceKind.BROKER_SOURCE_RECORD,
    "broker_source_occurrence": ReportSourceKind.BROKER_SOURCE_OCCURRENCE,
    "ingestion_run": ReportSourceKind.INGESTION_RUN,
    "portfolio_snapshot": ReportSourceKind.PORTFOLIO_SNAPSHOT,
    "calculation_run": ReportSourceKind.CALCULATION,
    "reconciliation_run": ReportSourceKind.RECONCILIATION,
    "price_snapshot": ReportSourceKind.PRICE_SNAPSHOT,
    "fx_snapshot": ReportSourceKind.FX_SNAPSHOT,
    "corporate_action_snapshot": ReportSourceKind.CORPORATE_ACTION,
    "provider_benchmark_snapshot": ReportSourceKind.BENCHMARK,
    "instrument_mapping": ReportSourceKind.MAPPING,
    "calendar_version": ReportSourceKind.CALENDAR,
    "provider_license_version": ReportSourceKind.LICENSE,
    "benchmark_version": ReportSourceKind.BENCHMARK_VERSION,
    "target_version": ReportSourceKind.TARGET_VERSION,
    "classification_evidence": ReportSourceKind.HISTORICAL_CLASSIFICATION,
    "historical_evidence": ReportSourceKind.HISTORICAL_EVIDENCE,
    "activity_revision_evidence": ReportSourceKind.ACTIVITY_REVISION_EVIDENCE,
}


def _sessions_missed(state: AlertCaptureState, effective_at: datetime) -> int:
    calendar = state.session.get(SourceCalendarModel, state.predicate.calendar_version_id)
    if (
        calendar is None
        or calendar.owner_id != state.version.owner_id
        or calendar.created_at > state.cutoff
        or calendar.period_start > effective_at.date()
        or calendar.period_end < state.cutoff.date()
    ):
        raise AlertCaptureUnavailable(d.AlertReason.INCOMPLETE_COVERAGE)
    rows = bounded(
        list(
            state.session.scalars(
                select(SourceCalendarSessionModel)
                .where(
                    SourceCalendarSessionModel.owner_id == state.version.owner_id,
                    SourceCalendarSessionModel.calendar_id == calendar.id,
                    SourceCalendarSessionModel.close_at > effective_at,
                    SourceCalendarSessionModel.close_at <= state.cutoff,
                )
                .order_by(SourceCalendarSessionModel.close_at)
                .limit(10001)
            )
        ),
        10000,
    )
    if any(row.created_at > state.cutoff for row in rows):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    state.reference(
        kind=ReportSourceKind.CALENDAR,
        identifier=calendar.id,
        digest=calendar.content_digest,
        effective_at=calendar.created_at,
        known_at=calendar.created_at,
    )
    state.bindings.append(
        d.AlertCanonicalBinding(
            family=d.AlertCanonicalFamily.HISTORICAL,
            role=d.AlertInputRole.CALENDAR,
            subject_id=calendar.id,
            content_digest=calendar.content_digest,
        )
    )
    return len(rows)


def coverage_observation(
    state: AlertCaptureState, effective_at: datetime, fact: d.AlertCoverageFact
) -> d.AlertThresholdInput:
    """An absent denominator is unknown even when the missing subtotal happens to be zero."""
    metric = state.predicate.metric
    if effective_at > state.cutoff:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    if metric is d.AlertMetric.SOURCE_AGE_SECONDS:
        elapsed = state.cutoff - effective_at
        value: Decimal | int | None = elapsed.days * 86400 + elapsed.seconds
    elif metric is d.AlertMetric.SOURCE_MISSING_SESSIONS:
        value = _sessions_missed(state, effective_at)
    elif metric is d.AlertMetric.MISSING_COUNT:
        value = (
            None
            if fact.expected_count is None or fact.available_count is None
            else fact.expected_count - fact.available_count
        )
    else:
        fraction = fact.covered_fraction
        if (
            fraction is None
            and fact.expected_count is not None
            and fact.expected_count > 0
            and fact.available_count is not None
        ):
            fraction = divide(Decimal(fact.available_count), Decimal(fact.expected_count))
        value = None if fraction is None else persisted_decimal(subtract(Decimal(1), fraction))
    return d.AlertThresholdInput(
        observation=state.observation(
            value,
            reason=d.AlertReason.UNKNOWN_DENOMINATOR if value is None else None,
            complete=value is not None,
        )
    )


def _valuation(state: AlertCaptureState) -> tuple[datetime, d.AlertCoverageFact]:
    snapshot = selected_snapshot(state)
    calculation = capture_snapshot(state, snapshot)
    coverage = calculation.coverage if isinstance(calculation.coverage, dict) else {}
    inventory_complete = coverage.get("is_complete", coverage.get("complete")) is True
    # Counts refer to the complete saved position/cash valuation-cell inventory, not market weight.
    if not inventory_complete:
        return snapshot.valuation_at, d.AlertCoverageFact(key="valuation", complete=False)
    positions = bounded(
        list(
            state.session.scalars(
                select(SnapshotPositionModel)
                .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                .order_by(SnapshotPositionModel.id)
                .limit(10001)
            )
        ),
        10000,
    )
    cash = bounded(
        list(
            state.session.scalars(
                select(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == snapshot.id)
                .order_by(SnapshotCashModel.id)
                .limit(10001)
            )
        ),
        10000,
    )
    bounded([*positions, *cash], 10000)
    quotes = _quotes(state, calculation)
    currency = CurrencyCode(snapshot.reporting_currency)
    available = 0
    for position in positions:
        state.reference(
            kind=ReportSourceKind.SNAPSHOT_POSITION,
            identifier=position.id,
            parent_id=snapshot.id,
            digest=digest(
                (
                    position.id,
                    position.listing_id,
                    position.market_value,
                    position.currency,
                    position.quality_state,
                    position.provenance,
                )
            ),
            effective_at=snapshot.valuation_at,
            known_at=snapshot.created_at,
        )
        if position.market_value is None:
            continue
        quote = quotes.get(position.listing_id)
        converted = convert_money(
            Money(position.market_value, CurrencyCode(position.currency)),
            reporting_currency=currency,
            fx_quotes=() if quote is None else (quote,),
            source_cutoff_at=Instant(snapshot.source_cutoff_at),
        )
        available += converted.converted_value is not None
    # Retain each wallet and the actual sourced conversion used to count availability.
    for wallet in cash:
        state.reference(
            kind=ReportSourceKind.SNAPSHOT_CASH,
            identifier=wallet.id,
            parent_id=snapshot.id,
            digest=digest(
                (wallet.id, wallet.amount, wallet.currency, wallet.quality_state, wallet.provenance)
            ),
            effective_at=snapshot.valuation_at,
            known_at=snapshot.created_at,
        )
        try:
            convert_captured_money(
                state,
                Money(wallet.amount, CurrencyCode(wallet.currency)),
                currency,
                at=snapshot.valuation_at,
            )
        except AlertCaptureUnavailable as exc:
            if exc.reason not in {d.AlertReason.MISSING_FX, d.AlertReason.MISSING_INPUT}:
                raise
        else:
            available += 1
    expected = len(positions) + len(cash)
    return snapshot.valuation_at, d.AlertCoverageFact(
        key="valuation_cells",
        expected_count=expected,
        available_count=available,
        complete=available == expected,
    )


def _classification(
    state: AlertCaptureState, row: ClassificationSnapshotModel
) -> d.AlertCoverageFact:
    taxonomy = state.session.get(XrayTaxonomyModel, row.taxonomy_id)
    if (
        taxonomy is None
        or taxonomy.owner_id != state.version.owner_id
        or taxonomy.created_at > state.cutoff
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    state.reference(
        kind=ReportSourceKind.TAXONOMY,
        identifier=taxonomy.id,
        digest=digest((taxonomy.id, taxonomy.key, taxonomy.version, taxonomy.dimension)),
        effective_at=taxonomy.created_at,
        known_at=taxonomy.created_at,
    )
    requested = bounded(
        list(
            state.session.scalars(
                select(ClassificationSnapshotInstrumentModel)
                .where(
                    ClassificationSnapshotInstrumentModel.owner_id == state.version.owner_id,
                    ClassificationSnapshotInstrumentModel.snapshot_id == row.id,
                )
                .order_by(ClassificationSnapshotInstrumentModel.ordinal)
                .limit(101)
            )
        ),
        100,
    )
    assignments = bounded(
        list(
            state.session.scalars(
                select(ClassificationAssignmentModel)
                .join(
                    ClassificationSnapshotAssignmentModel,
                    ClassificationSnapshotAssignmentModel.assignment_id
                    == ClassificationAssignmentModel.id,
                )
                .where(
                    ClassificationSnapshotAssignmentModel.snapshot_id == row.id,
                    ClassificationAssignmentModel.owner_id == state.version.owner_id,
                )
                .order_by(ClassificationSnapshotAssignmentModel.ordinal)
                .limit(10001)
            )
        ),
        10000,
    )
    if len(assignments) != row.row_count or any(
        item.created_at > state.cutoff for item in (*requested, *assignments)
    ):
        raise AlertCaptureUnavailable(d.AlertReason.INCOMPLETE_COVERAGE)
    by_instrument: dict[UUID, list[ClassificationAssignmentModel]] = {}
    for item in assignments:
        if item.dimension != taxonomy.dimension or item.effective_at > state.cutoff:
            continue
        parent = row
        if item.snapshot_id != row.id:
            actual_parent = state.session.get(ClassificationSnapshotModel, item.snapshot_id)
            if actual_parent is None or actual_parent.owner_id != state.version.owner_id:
                raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
            parent = actual_parent
            capture_physical(state, parent, ReportSourceKind.CLASSIFICATION_SNAPSHOT)
        state.reference(
            kind=ReportSourceKind.CLASSIFICATION_ASSIGNMENT,
            identifier=item.id,
            parent_id=item.snapshot_id,
            digest=digest(
                (
                    item.id,
                    item.instrument_id,
                    item.entity_id,
                    item.dimension,
                    item.bucket_key,
                    item.effective_at,
                    item.valid_until,
                    item.state,
                )
            ),
            effective_at=item.effective_at,
            known_at=max(item.created_at, parent.first_observed_at),
            provider_id=parent.provider_id,
            license_id=parent.license_version_id,
            expires_at=parent.expires_at,
        )
        if item.effective_at <= state.cutoff and (
            item.valid_until is None or state.cutoff < item.valid_until
        ):
            by_instrument.setdefault(item.instrument_id, []).append(item)
    available = 0
    for request in requested:
        candidates = by_instrument.get(request.instrument_id, [])
        available += (
            bool(candidates)
            and all(
                item.state == "available" and item.bucket_key is not None for item in candidates
            )
            and len({item.bucket_key for item in candidates}) == 1
        )
    return d.AlertCoverageFact(
        key=f"classification.{taxonomy.dimension}",
        expected_count=len(requested),
        available_count=available,
        complete=available == len(requested),
    )


def _require_history_store(state: AlertCaptureState, input_id: UUID) -> None:
    """Check licensed normalized dependencies before loading either historical payload."""
    pending = [(True, input_id)]
    visited: set[tuple[bool, UUID]] = set()
    remaining = d.MAX_ALERT_SOURCE_REFERENCES
    model = HistoricalDependencyModel
    while pending:
        capture, identifier = pending.pop()
        if (capture, identifier) in visited:
            continue
        visited.add((capture, identifier))
        rows = bounded(
            list(
                state.session.scalars(
                    select(model)
                    .where(
                        model.owner_id == state.version.owner_id,
                        model.input_id == identifier
                        if capture
                        else model.evidence_id == identifier,
                    )
                    .limit(remaining + 1)
                )
            ),
            remaining,
        )
        remaining -= len(rows)
        for row in rows:
            for physical_id, physical_model in (
                (row.price_snapshot_id, PriceSnapshotModel),
                (row.fx_snapshot_id, FxSnapshotModel),
                (row.action_snapshot_id, CorporateActionSnapshotModel),
                (row.benchmark_snapshot_id, BenchmarkSnapshotModel),
            ):
                if physical_id is None:
                    continue
                header = state.session.get(physical_model, physical_id)
                if header is None or header.owner_id != state.version.owner_id:
                    raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
                state.sources._permit(
                    state.session,
                    state.version.owner_id,
                    header.license_version_id,
                    SourceUse.STORE,
                )
            if row.classification_id is not None:
                classification, evidence = HistoricalClassificationModel, HistoricalEvidenceModel
                license_id = state.session.scalar(
                    select(classification.license_version_id)
                    .join(evidence, evidence.id == classification.evidence_id)
                    .where(
                        classification.id == row.classification_id,
                        classification.owner_id == state.version.owner_id,
                        evidence.owner_id == state.version.owner_id,
                        evidence.broker_account_id == state.version.account_id,
                    )
                )
                if license_id is None:
                    raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
                state.sources._permit(
                    state.session, state.version.owner_id, license_id, SourceUse.STORE
                )
            if row.license_version_id is not None:
                state.sources._permit(
                    state.session, state.version.owner_id, row.license_version_id, SourceUse.STORE
                )
            if row.registered_evidence_id is not None:
                pending.append((False, row.registered_evidence_id))


def _history(
    state: AlertCaptureState, *, sessions: sessionmaker[Session], cursor_signing_key: bytes
) -> tuple[datetime, d.AlertCoverageFact]:
    run = state.session.get(HistoricalRunModel, state.predicate.source_id)
    if (
        run is None
        or run.owner_id != state.version.owner_id
        or not run.sealed
        or run.created_at > state.cutoff
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    source = state.session.get(HistoricalInputModel, run.input_id)
    stored = state.session.get(AnalyticsRunModel, run.analytics_run_id)
    if (
        source is None
        or stored is None
        or source.owner_id != state.version.owner_id
        or stored.owner_id != state.version.owner_id
        or source.broker_account_id != state.version.account_id
        or stored.broker_account_id != state.version.account_id
        or max(
            source.created_at,
            source.source_cutoff_at,
            stored.created_at,
            stored.source_cutoff_at,
            stored.valuation_at,
        )
        > state.cutoff
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    _require_history_store(state, source.id)
    service = PostgresHistoricalService(
        sessions,
        cursor_signing_key=cursor_signing_key,
        clock=lambda: state.now,
    )
    # Owner/current DISPLAY+STORE checks precede both immutable payload decodes.
    captured = service._capture_view(state.session, state.version.owner_id, source)
    for reference in captured.input.sources:
        model, _ = REFERENCE_MODELS[reference.kind]
        physical = state.session.get(model, UUID(reference.id))
        if isinstance(physical, SourceSnapshotFields):
            capture_physical(state, physical, _HISTORY_KINDS[reference.kind])
            continue
        provider_id = license_id = None
        if isinstance(physical, HistoricalClassificationModel):
            license_id = physical.license_version_id
        elif isinstance(physical, ProviderLicenseVersionModel):
            license_id = physical.id
        if license_id is not None:
            state.sources._permit(
                state.session, state.version.owner_id, license_id, SourceUse.STORE
            )
            license_row = state.session.get(ProviderLicenseVersionModel, license_id)
            if license_row is None:
                raise AlertCaptureUnavailable(d.AlertReason.SOURCE_RESTRICTED)
            license = license_view(license_row)
            state.licenses[license.id] = license
            provider_id = license_row.provider_id
        state.reference(
            kind=_HISTORY_KINDS[reference.kind],
            identifier=UUID(reference.id),
            digest=reference.semantic_digest or reference.original_fingerprint or digest(reference),
            effective_at=reference.effective_at,
            known_at=reference.first_observed_at,
            provider_id=provider_id,
            license_id=license_id,
        )
    result = historical_result_from_json(stored.canonical_result)
    if (
        historical_result_digest(result) != stored.content_digest
        or result.context.input_digest != captured.input_digest
    ):
        raise AlertCaptureUnavailable(d.AlertReason.COMPUTATION_FAILED)
    state.reference(
        kind=ReportSourceKind.HISTORICAL_INPUT,
        identifier=source.id,
        digest=source.input_digest,
        effective_at=stored.valuation_at,
        known_at=source.created_at,
    )
    state.reference(
        kind=ReportSourceKind.HISTORICAL_RESULT,
        identifier=run.id,
        parent_id=source.id,
        digest=stored.content_digest,
        effective_at=stored.valuation_at,
        known_at=max(run.created_at, stored.created_at),
    )
    state.bindings.append(
        d.AlertCanonicalBinding(
            family=d.AlertCanonicalFamily.HISTORICAL,
            role=d.AlertInputRole.RESULT,
            subject_id=run.id,
            parent_id=source.id,
            content_digest=stored.content_digest,
            method_key=result.context.method.name,
            method_version=result.context.method.version,
        )
    )
    measures = result.context.coverage.measures
    facts = tuple(
        d.AlertCoverageFact(
            key=item.key.value,
            expected_count=item.expected_count,
            available_count=item.available_count,
            complete=item.complete,
        )
        for item in measures
    )
    state.context = replace(
        state.context,
        valuation_at=stored.valuation_at,
        quality=result.context.quality,
        method_key=result.context.method.name,
        method_version=result.context.method.version,
        coverage=facts,
        assumptions=(
            *result.context.assumptions,
            "history_coverage_counts_all_canonical_measure_cells",
        ),
        warnings=tuple(
            d.AlertWarning(code=item.reason_code.value, message=item.reason_code.value)
            for item in result.context.warnings
        ),
    )
    expected = sum(item.expected_count for item in measures)
    available = sum(item.available_count for item in measures)
    return stored.valuation_at, d.AlertCoverageFact(
        key="history",
        expected_count=expected,
        available_count=available,
        complete=all(item.complete for item in measures),
    )


def capture_source_health(
    state: AlertCaptureState, *, sessions: sessionmaker[Session], cursor_signing_key: bytes
) -> d.AlertThresholdInput:
    family = state.predicate.source_family or state.predicate.domain
    row: (
        PriceSnapshotModel
        | FxSnapshotModel
        | ClassificationSnapshotModel
        | ConstituentSnapshotModel
        | None
    )
    if family is d.AlertSourceFamily.VALUATION:
        effective, fact = _valuation(state)
    elif family is d.AlertSourceFamily.HISTORY:
        effective, fact = _history(state, sessions=sessions, cursor_signing_key=cursor_signing_key)
    else:
        if family is d.AlertSourceFamily.PRICE:
            row = state.session.get(PriceSnapshotModel, state.predicate.source_id)
            kind = ReportSourceKind.PRICE_SNAPSHOT
        elif family is d.AlertSourceFamily.FX:
            row = state.session.get(FxSnapshotModel, state.predicate.source_id)
            kind = ReportSourceKind.FX_SNAPSHOT
        elif family is d.AlertSourceFamily.CLASSIFICATION:
            row = state.session.get(ClassificationSnapshotModel, state.predicate.source_id)
            kind = ReportSourceKind.CLASSIFICATION_SNAPSHOT
        elif family is d.AlertSourceFamily.CONSTITUENT:
            row = state.session.get(ConstituentSnapshotModel, state.predicate.source_id)
            kind = ReportSourceKind.CONSTITUENT_SNAPSHOT
        else:
            raise AlertCaptureUnavailable(d.AlertReason.UNSUPPORTED)
        if row is None or row.owner_id != state.version.owner_id:
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
        capture_physical(state, row, kind)
        effective = row.effective_at
        state.context = replace(
            state.context,
            valuation_at=effective,
            quality=QualityState(row.quality),
            method_key="immutable_source_coverage",
            method_version="1.0.0",
        )
        if isinstance(row, (PriceSnapshotModel, FxSnapshotModel)):
            fact = d.AlertCoverageFact(
                key=family.value,
                expected_count=row.expected_count,
                available_count=row.available_count,
                complete=row.expected_count == row.available_count,
            )
        elif isinstance(row, ClassificationSnapshotModel):
            fact = _classification(state, row)
        else:
            covered = (
                None
                if row.known_weight is None or row.cash_weight is None
                else persisted_decimal(add(row.known_weight, row.cash_weight))
            )
            fact = d.AlertCoverageFact(
                key="constituent_weight",
                covered_fraction=covered,
                complete=None if covered is None else covered == 1,
            )
    if not any(item.key == fact.key for item in state.context.coverage):
        state.context = replace(state.context, coverage=(*state.context.coverage, fact))
    return coverage_observation(state, effective, fact)
