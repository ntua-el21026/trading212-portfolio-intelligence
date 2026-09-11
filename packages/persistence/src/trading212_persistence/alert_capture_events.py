"""Canonical economic revisions and explicit activity coverage for event rules."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from trading212_analytics._historical_core import (
    event_revision_key,
    revision_first_eligible_at,
    selected_event_revisions,
)
from trading212_analytics.quality import combine_quality
from trading212_domain import alerts as d
from trading212_domain import historical as h
from trading212_domain.enums import QualityState
from trading212_domain.reports import ReportSourceKind
from trading212_domain.values import Money

from .activity_revision_store import activity_revision_sources, capture_activity_revisions
from .alert_capture_common import AlertCaptureState, AlertCaptureUnavailable, bounded
from .alert_capture_fx import convert_captured_money
from .historical_models import HistoricalActivityCoverageModel, HistoricalEvidenceModel
from .historical_normalization import normalize_record
from .models import IngestionRunModel, SourceRecordModel, SourceRecordOccurrenceModel
from .planning_inputs import digest
from .source_models import MarketDataInstrumentModel


def _coverage(state: AlertCaptureState, capabilities: tuple[str, ...]) -> bool:
    chunk, evidence, run = (
        HistoricalActivityCoverageModel,
        HistoricalEvidenceModel,
        IngestionRunModel,
    )
    rows = bounded(
        list(
            state.session.scalars(
                select(chunk)
                .join(evidence, evidence.id == chunk.evidence_id)
                .join(run, run.id == chunk.ingestion_run_id)
                .where(
                    chunk.owner_id == state.version.owner_id,
                    evidence.owner_id == state.version.owner_id,
                    evidence.broker_account_id == state.version.account_id,
                    evidence.sealed.is_(True),
                    evidence.first_observed_at <= state.cutoff,
                    evidence.created_at <= state.cutoff,
                    chunk.first_observed_at <= state.cutoff,
                    chunk.created_at <= state.cutoff,
                    chunk.end_at >= state.window.start_at,
                    chunk.start_at <= state.cutoff,
                    chunk.capability.in_(capabilities),
                    run.broker_account_id == state.version.account_id,
                    run.completed_at <= state.cutoff,
                    run.status == "succeeded",
                )
                .order_by(chunk.start_at, chunk.end_at, chunk.id)
                .limit(10001)
            )
        ),
        10000,
    )
    complete = True
    for capability in capabilities:
        through = state.window.start_at
        for row in rows:
            if row.capability != capability:
                continue
            state.reference(
                kind=ReportSourceKind.ACTIVITY_COVERAGE,
                identifier=row.id,
                parent_id=row.evidence_id,
                digest=digest(
                    (
                        row.id,
                        row.ingestion_run_id,
                        row.capability,
                        row.start_at,
                        row.end_at,
                        row.first_observed_at,
                        row.coverage_complete,
                    )
                ),
                effective_at=row.end_at,
                known_at=max(row.first_observed_at, row.created_at),
            )
            if row.coverage_complete and row.start_at <= through:
                through = max(through, row.end_at)
        complete = complete and through >= state.cutoff
    state.context = replace(
        state.context, coverage=(d.AlertCoverageFact(key="activity_window", complete=complete),)
    )
    return complete


def _kind(event: h.HistoricalEvent) -> h.HistoricalCashFlowKind:
    if isinstance(event, h.HistoricalExecution):
        return h.HistoricalCashFlowKind(event.side)
    if isinstance(event, h.HistoricalCashEffect):
        return h.HistoricalCashFlowKind(event.effect_kind)
    return h.HistoricalCashFlowKind(event.kind)


def _economic_identity(event: h.HistoricalEvent) -> UUID:
    # This is a derived deduplication identity; actual source/revision IDs remain separate.
    economic = event_revision_key(event)
    return uuid5(NAMESPACE_URL, f"urn:trading212-portfolio-intelligence:economic-event:{economic}")


def _in_scope(state: AlertCaptureState, event: h.HistoricalEvent) -> bool:
    predicate = state.predicate
    if predicate.metric is d.AlertMetric.POSITIVE_DIVIDEND:
        if not isinstance(event, h.HistoricalDividend):
            return False
        # Unknown identity can still affect the requested instrument; it must
        # reach the explicit unavailable guard after revision selection.
        if (
            predicate.instrument_id is not None
            and event.instrument_id is not None
            and str(predicate.instrument_id) != event.instrument_id
        ):
            return False
    elif predicate.metric is d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT:
        if not isinstance(event, h.HistoricalExternalFlow):
            return False
    elif predicate.metric is d.AlertMetric.UNCLASSIFIED_ACTIVITY and not isinstance(
        event, h.HistoricalUnknownActivity
    ):
        return False
    return predicate.activity_kind is None or _kind(event) is predicate.activity_kind


def _in_window(
    state: AlertCaptureState, event: h.HistoricalEvent, eligible_at: datetime | None = None
) -> bool:
    at = (
        (eligible_at if eligible_at is not None else event.identity.first_observed_at)
        if state.window.newly_known_revisions
        else event.identity.economic_at
    )
    return state.window.start_at < at <= state.cutoff


def _relevant_revisions(
    state: AlertCaptureState,
    events: tuple[h.HistoricalEvent, ...],
    eligible_times: dict[str, datetime] | None = None,
) -> tuple[h.HistoricalEvent, ...]:
    """Scope whole economic groups; never discard a conflicting or correcting member."""
    groups: dict[str, list[h.HistoricalEvent]] = {}
    by_economic: dict[tuple[str, datetime], set[str]] = {}
    relevant: set[str] = set()
    for event in events:
        key = event_revision_key(event)
        groups.setdefault(key, []).append(event)
        by_economic.setdefault(
            (event.identity.economic_key, event.identity.economic_at), set()
        ).add(key)
        eligible_at = (
            None if eligible_times is None else eligible_times[event.identity.source_record_id]
        )
        if _in_scope(state, event) and _in_window(state, event, eligible_at):
            relevant.add(key)
    pending = list(relevant)
    while pending:
        for event in groups[pending.pop()]:
            if not isinstance(event, h.HistoricalCashEffect):
                continue
            # Canonical linked cash-effect deduplication needs its same-instant
            # parent, even when that parent's kind is outside the alert scope.
            for related in event.related_event_keys:
                for key in by_economic.get((related, event.identity.economic_at), ()):
                    if key not in relevant:
                        relevant.add(key)
                        pending.append(key)
    return tuple(event for event in events if event_revision_key(event) in relevant)


def _sources(state: AlertCaptureState) -> tuple[tuple[h.HistoricalEvent, ...], dict[str, datetime]]:
    model = SourceRecordModel
    records = bounded(
        list(
            state.session.scalars(
                select(model)
                .where(
                    model.broker_account_id == state.version.account_id,
                    model.observed_at <= state.cutoff,
                    model.created_at <= state.cutoff,
                    model.capability.in_(
                        ("historical_orders", "historical_dividends", "historical_transactions")
                    ),
                )
                .order_by(model.observed_at, model.id)
                .limit(10001)
            )
        ),
        10000,
    )
    mapping = MarketDataInstrumentModel
    mappings = tuple(
        bounded(
            list(
                state.session.scalars(
                    select(mapping)
                    .where(
                        mapping.owner_id == state.version.owner_id,
                        mapping.created_at <= state.cutoff,
                        mapping.valid_from <= state.cutoff,
                    )
                    .order_by(mapping.id)
                    .limit(8193)
                )
            ),
            8192,
        )
    )
    occurrence = SourceRecordOccurrenceModel
    occurrences = {
        item.source_record_id: item
        for item in state.session.scalars(
            select(occurrence)
            .where(
                occurrence.source_record_id.in_([item.id for item in records]),
                occurrence.observed_at <= state.cutoff,
                occurrence.created_at <= state.cutoff,
            )
            .distinct(occurrence.source_record_id)
            .order_by(occurrence.source_record_id, occurrence.observed_at, occurrence.id)
            .limit(10001)
        )
    }
    events = []
    for record in records:
        event = normalize_record(record, occurrences.get(record.id), mappings)
        if event is None:
            continue
        event = replace(
            event,
            identity=replace(
                event.identity, first_observed_at=max(record.observed_at, record.created_at)
            ),
        )
        events.append(event)
    raw_events, proofs = capture_activity_revisions(
        state.session,
        owner_id=state.version.owner_id,
        account_id=state.version.account_id,
        events=tuple(events),
        cutoff=state.cutoff,
    )
    by_source = {event.identity.source_record_id: event for event in raw_events}
    visible_groups = {
        event_revision_key(event)
        for event in raw_events
        if event.identity.economic_at <= state.cutoff
    }
    proof_groups = {
        event_revision_key(by_source[str(proof.registration.new_source_record_id)])
        for proof in proofs
    }
    retained_groups = visible_groups & proof_groups
    # A proof may correct an erroneous future payment date. Keep its complete
    # known group, but preserve the existing inventory exactly when no proof exists.
    raw_events = tuple(
        event
        for event in raw_events
        if event.identity.economic_at <= state.cutoff
        or event_revision_key(event) in retained_groups
    )
    retained_ids = {event.identity.source_record_id for event in raw_events}
    proofs = tuple(
        proof for proof in proofs if str(proof.registration.new_source_record_id) in retained_ids
    )
    records_by_id = {str(record.id): record for record in records}
    for event in raw_events:
        record = records_by_id[event.identity.source_record_id]
        state.reference(
            kind=ReportSourceKind.BROKER_SOURCE_RECORD,
            identifier=record.id,
            digest=record.payload_fingerprint,
            # For a future economic parent this is evidence of actual source
            # arrival. The canonical event digest binds its true future payment time.
            effective_at=(
                event.identity.economic_at
                if event.identity.economic_at <= state.cutoff
                else record.observed_at
            ),
            known_at=event.identity.first_observed_at,
        )
    for proof in proofs:
        state.reference(
            kind=ReportSourceKind.ACTIVITY_REVISION_EVIDENCE,
            identifier=proof.registration.id,
            parent_id=proof.registration.new_source_record_id,
            digest=proof.content_digest,
            effective_at=proof.first_observed_at,
            known_at=proof.first_observed_at,
        )
    for event in raw_events:
        state.bindings.append(
            d.AlertCanonicalBinding(
                family=d.AlertCanonicalFamily.HISTORICAL,
                role=d.AlertInputRole.EVENT_REVISION,
                subject_id=UUID(event.identity.source_record_id),
                content_digest=digest(event),
                method_key="canonical_broker_event_normalization",
                method_version=h.HISTORICAL_METHOD_VERSION,
            )
        )
    revision_sources = activity_revision_sources(proofs)
    eligible_times = revision_first_eligible_at(raw_events, revision_sources, cutoff=state.cutoff)
    relevant = _relevant_revisions(state, raw_events, eligible_times)
    relevant_ids = {event.identity.source_record_id for event in relevant}
    selected, ambiguous = selected_event_revisions(
        relevant,
        state.cutoff,
        revision_sources=tuple(
            source for source in revision_sources if source.parent_ids[0] in relevant_ids
        ),
    )
    if ambiguous:
        raise AlertCaptureUnavailable(d.AlertReason.AMBIGUOUS_SOURCE)
    used = {event.mapping_id for event in selected if isinstance(event, h.HistoricalExecution)}
    used.update(
        str(row.id)
        for row in mappings
        if any(
            isinstance(event, h.HistoricalDividend)
            and event.instrument_id == str(row.instrument_id)
            and event.listing_id == str(row.listing_id)
            for event in selected
        )
    )
    for row in mappings:
        if str(row.id) in used:
            state.reference(
                kind=ReportSourceKind.MAPPING,
                identifier=row.id,
                digest=row.content_digest,
                effective_at=row.valid_from,
                known_at=row.created_at,
            )
    return tuple(
        event for event in selected if event.identity.economic_at <= state.cutoff
    ), eligible_times


def capture_activity(state: AlertCaptureState) -> d.AlertThresholdInput | d.AlertEventBatchInput:
    capabilities = (
        ("historical_dividends",)
        if state.predicate.family is d.AlertFamily.DIVIDEND_RECEIVED
        else ("historical_orders", "historical_dividends", "historical_transactions")
    )
    complete = _coverage(state, capabilities)
    selected, eligible_times = _sources(state)
    eligible = tuple(
        event
        for event in selected
        if _in_scope(state, event)
        and _in_window(state, event, eligible_times[event.identity.source_record_id])
    )
    state.context = replace(
        state.context,
        quality=combine_quality(
            (
                QualityState.FRESH if complete else QualityState.PARTIAL,
                *(item.identity.quality for item in eligible),
            )
        ),
        method_key="canonical_economic_activity",
        method_version=h.HISTORICAL_METHOD_VERSION,
    )
    if state.predicate.metric is d.AlertMetric.ACTIVITY_COUNT:
        return d.AlertThresholdInput(
            observation=state.observation(len(eligible), complete=complete)
        )
    events = []
    for event in eligible:
        amount: Money | None = None
        instrument: UUID | None = None
        metric: bool | Decimal = True
        if state.predicate.metric is d.AlertMetric.POSITIVE_DIVIDEND:
            if not isinstance(event, h.HistoricalDividend):
                continue
            if state.predicate.instrument_id is not None and event.instrument_id is None:
                raise AlertCaptureUnavailable(d.AlertReason.UNKNOWN_IDENTITY)
            instrument = UUID(event.instrument_id) if event.instrument_id else None
            amount = event.net
            if (
                state.predicate.minimum_net_amount is not None
                and amount.amount > 0
                and state.predicate.instrument_id in (None, instrument)
            ):
                amount = convert_captured_money(
                    state,
                    amount,
                    state.predicate.minimum_net_amount.currency,
                    at=event.identity.economic_at,
                )
        elif state.predicate.metric is d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT:
            if not isinstance(event, h.HistoricalExternalFlow):
                continue
            assert state.predicate.currency is not None
            amount = convert_captured_money(
                state, event.signed_amount, state.predicate.currency, at=event.identity.economic_at
            )
            metric = amount.amount.copy_abs()
        elif not isinstance(event, h.HistoricalUnknownActivity):
            continue
        correction = event.identity.supersedes_revision_id
        if isinstance(event, h.HistoricalDividend):
            correction = event.correction_of or correction
        events.append(
            d.AlertEventObservation(
                identity=_economic_identity(event),
                revision_id=UUID(event.identity.revision_id),
                correction_of=None if correction is None else UUID(correction),
                economic_at=event.identity.economic_at,
                first_eligible_at=eligible_times[event.identity.source_record_id],
                instrument_id=instrument,
                activity_kind=_kind(event),
                net_amount=amount,
                observation=state.observation(
                    metric, currency=state.predicate.currency, complete=complete
                ),
            )
        )
    return d.AlertEventBatchInput(
        events=tuple(events),
        complete=complete,
        reason=None if complete else d.AlertReason.INCOMPLETE_COVERAGE,
    )
