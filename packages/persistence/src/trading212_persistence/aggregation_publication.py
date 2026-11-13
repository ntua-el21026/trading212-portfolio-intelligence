"""Atomic complete aggregate publication; authorization and original deadline stay with caller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from trading212_analytics.aggregation_validation import (
    validate_activity_binding,
    validate_holdings_binding,
)
from trading212_application import aggregation as app
from trading212_domain.aggregation import AggregateRecord
from trading212_domain.aggregation_codec import aggregation_record_bytes
from trading212_domain.aggregation_inputs import AggregateActivityInput, AggregateHoldingsInput
from trading212_domain.aggregation_results import (
    AggregateActivityResult,
    AggregateActivitySummary,
    AggregateHoldingsResult,
    AggregateHoldingsSummary,
)

from . import aggregation_models as m
from .aggregation_authorization import AggregateAuthorization

_PREFIX = b"t212pi.aggregation.record.v1\0"


def _bytes(value: AggregateRecord, check: Callable[[], None]) -> tuple[bytes, str]:
    check()
    payload = aggregation_record_bytes(value)
    digest = sha256(_PREFIX)
    digest.update(payload)
    check()
    return payload, digest.hexdigest()


def _row[T: m.AggregateProjectionRow](
    model: type[T],
    owner: UUID,
    run: UUID,
    ordinal: int,
    value: AggregateRecord,
    now: datetime,
    check: Callable[[], None],
) -> T:
    payload, digest = _bytes(value, check)
    return model(
        id=uuid4(),
        owner_id=owner,
        run_id=run,
        ordinal=ordinal,
        payload=payload,
        content_digest=digest,
        created_at=now,
    )


def publish_aggregate(
    session: Session,
    auth: AggregateAuthorization,
    root: m.AggregateRunModel,
    *,
    holdings_input: AggregateHoldingsInput,
    holdings_result: AggregateHoldingsResult,
    activity_input: AggregateActivityInput | None,
    activity_result: AggregateActivityResult | None,
    now: datetime,
    check_deadline: Callable[[], None],
) -> None:
    if (
        root.owner_id != auth.owner_id
        or root.sealed
        or tuple(x.account_id for x in holdings_input.selection.members) != auth.account_ids
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    if root.activity_requested != (activity_input is not None) or (activity_input is None) != (
        activity_result is None
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.VALIDATION_FAILED)
    validate_holdings_binding(holdings_input, holdings_result, check_deadline=check_deadline)
    if activity_input is not None and activity_result is not None:
        validate_activity_binding(activity_input, activity_result, check_deadline=check_deadline)
        if (
            activity_input.holdings_input_digest != holdings_result.input_digest
            or activity_input.account_ids != auth.account_ids
        ):
            raise app.AggregateServiceError(app.AggregateErrorCode.VALIDATION_FAILED)
    input_payload, input_digest = _bytes(holdings_input, check_deadline)
    result_payload, result_digest = _bytes(holdings_result, check_deadline)
    summary = AggregateHoldingsSummary(
        input_digest=input_digest,
        reporting_currency=holdings_result.reporting_currency,
        source_cutoff_at=holdings_result.source_cutoff_at,
        snapshots=holdings_result.snapshots,
        securities=holdings_result.securities,
        cash=holdings_result.cash,
        total=holdings_result.total,
        rounding_residual=holdings_result.rounding_residual,
        component_count=len(holdings_result.components),
        holding_count=len(holdings_result.holdings),
    )
    summary_payload, summary_digest = _bytes(summary, check_deadline)
    root.holdings_input_digest = input_digest
    root.holdings_result_digest = result_digest
    session.flush()
    session.add(
        m.AggregateHoldingsPayloadModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            run_id=root.id,
            input_payload=input_payload,
            result_payload=result_payload,
            summary_payload=summary_payload,
            summary_digest=summary_digest,
            created_at=now,
        )
    )
    sources: set[tuple[str, str, UUID]] = set()
    for index, pin in enumerate(holdings_input.snapshots):
        snapshot_row = _row(
            m.AggregateSnapshotModel, auth.owner_id, root.id, index, pin, now, check_deadline
        )
        snapshot_row.account_id = pin.account_id
        snapshot_row.snapshot_id = pin.portfolio_snapshot_id
        snapshot_row.calculation_run_id = pin.calculation_run_id
        session.add(snapshot_row)
        sources.update(
            (
                ("holdings", "snapshot", pin.portfolio_snapshot_id),
                ("holdings", "calculation", pin.calculation_run_id),
            )
        )
    # Native and FX guards read these run-specific pins. Trigger dependencies
    # are absent from ORM foreign keys, so they need an explicit flush boundary.
    check_deadline()
    session.flush()
    for index, quote in enumerate(holdings_input.fx_uses):
        fx_row = _row(m.AggregateFxModel, auth.owner_id, root.id, index, quote, now, check_deadline)
        fx_row.account_id = quote.account_id
        fx_row.source_currency = str(quote.source_currency)
        fx_row.target_currency = str(quote.target_currency)
        fx_row.fx_snapshot_id = quote.fx_snapshot_id
        fx_row.fx_observation_id = quote.fx_observation_id
        fx_row.license_version_id = quote.license_version_id
        fx_row.original_rate = quote.original_rate
        fx_row.state = quote.state.value
        fx_row.inverted = quote.inverted
        session.add(fx_row)
        sources.update(
            (
                ("holdings", "fx", quote.fx_snapshot_id),
                ("holdings", "fx_observation", quote.fx_observation_id),
            )
        )
    if holdings_input.fx_uses:
        # Cross-currency components must see their exact admitted FX proof too.
        check_deadline()
        session.flush()
    for index, component in enumerate(holdings_result.components):
        component_row = _row(
            m.AggregateComponentModel, auth.owner_id, root.id, index, component, now, check_deadline
        )
        native = component.native
        component_row.component_id = native.component_id
        component_row.account_id = native.account_id
        component_row.snapshot_id = native.portfolio_snapshot_id
        component_row.kind = native.kind
        component_row.position_id = native.component_id if native.kind == "position" else None
        component_row.cash_id = native.component_id if native.kind == "cash" else None
        component_row.listing_id = native.listing_id
        component_row.instrument_id = native.instrument_id
        component_row.quantity = native.quantity
        component_row.native_currency = str(native.native_currency)
        component_row.native_value = native.native_value
        component_row.reporting_currency = str(component.reporting_currency)
        component_row.converted_value = component.converted_value
        component_row.fx_observation_id = component.fx_observation_id
        component_row.quality = component.quality.value
        component_row.origin = native.origin.value
        component_row.reason = None if component.reason is None else component.reason.value
        session.add(component_row)
        sources.update(("holdings", "broker_record", source) for source in native.source_record_ids)
    for index, holding in enumerate(holdings_result.holdings):
        holding_row = _row(
            m.AggregateHoldingModel, auth.owner_id, root.id, index, holding, now, check_deadline
        )
        holding_row.instrument_id = holding.instrument_id
        holding_row.quantity = holding.quantity
        holding_row.currency = str(holding.money.currency)
        holding_row.value = holding.money.value
        holding_row.known_value = holding.money.known_value
        holding_row.known_count = holding.money.known_count
        holding_row.total_count = holding.money.total_count
        session.add(holding_row)
    for index, account in enumerate(holdings_result.accounts):
        account_total_row = _row(
            m.AggregateAccountTotalModel,
            auth.owner_id,
            root.id,
            index,
            account,
            now,
            check_deadline,
        )
        account_total_row.account_id = account.account_id
        account_total_row.currency = str(account.money.currency)
        account_total_row.value = account.money.value
        account_total_row.known_value = account.money.known_value
        account_total_row.known_count = account.money.known_count
        account_total_row.total_count = account.money.total_count
        session.add(account_total_row)
    if activity_input is not None and activity_result is not None:
        _publish_activity(
            session, auth, root, activity_input, activity_result, sources, now, check_deadline
        )
    fields = {
        "snapshot": "snapshot_id",
        "calculation": "calculation_run_id",
        "broker_record": "source_record_id",
        "fx": "fx_snapshot_id",
        "fx_observation": "fx_observation_id",
        "coverage": "coverage_id",
        "coverage_parent": "evidence_id",
        "revision": "revision_id",
    }
    for index, (view, kind, source_id) in enumerate(sorted(sources)):
        if index % 64 == 0:
            check_deadline()
        source_row = m.AggregateSourceModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            run_id=root.id,
            view_kind=view,
            source_kind=kind,
            source_id=source_id,
            created_at=now,
        )
        setattr(source_row, fields[kind], source_id)
        session.add(source_row)
    check_deadline()
    session.flush()
    # The caller repeats all current authority/deadline checks, then seals. A
    # failure rolls back this whole transaction, including capacity and commands.


def _publish_activity(
    session: Session,
    auth: AggregateAuthorization,
    root: m.AggregateRunModel,
    source: AggregateActivityInput,
    result: AggregateActivityResult,
    sources: set[tuple[str, str, UUID]],
    now: datetime,
    check: Callable[[], None],
) -> None:
    input_payload, input_digest = _bytes(source, check)
    result_payload, result_digest = _bytes(result, check)
    summary = AggregateActivitySummary(
        input_digest=input_digest,
        holdings_input_digest=result.holdings_input_digest,
        window=result.window,
        currency_totals=result.currency_totals,
        complete=result.complete,
        reasons=result.reasons,
        candidate_count=result.candidate_count,
        selected_count=result.selected_count,
        match_count=len(result.matches),
    )
    summary_payload, summary_digest = _bytes(summary, check)
    root.activity_input_digest = input_digest
    root.activity_result_digest = result_digest
    # The canonical payload guard reads the persisted digests before insertion.
    # Flush the root update before queuing its activity children.
    check()
    session.flush()
    session.add(
        m.AggregateActivityPayloadModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            run_id=root.id,
            input_payload=input_payload,
            result_payload=result_payload,
            summary_payload=summary_payload,
            summary_digest=summary_digest,
            created_at=now,
        )
    )
    for index, candidate in enumerate(source.candidates):
        activity_evidence_row = _row(
            m.AggregateActivityEvidenceModel, auth.owner_id, root.id, index, candidate, now, check
        )
        activity_evidence_row.account_id = candidate.account_id
        activity_evidence_row.source_record_id = candidate.source_record_id
        activity_evidence_row.selected = candidate.selected
        activity_evidence_row.amount = candidate.amount
        activity_evidence_row.currency = (
            None if candidate.currency is None else str(candidate.currency)
        )
        session.add(activity_evidence_row)
        sources.add(("activity", "broker_record", candidate.source_record_id))
    for index, coverage in enumerate(source.coverage):
        coverage_row = _row(
            m.AggregateCoverageModel, auth.owner_id, root.id, index, coverage, now, check
        )
        coverage_row.account_id = coverage.account_id
        coverage_row.coverage_id = coverage.coverage_id
        coverage_row.evidence_id = coverage.historical_evidence_id
        coverage_row.evidence_digest = coverage.evidence_digest
        coverage_row.ingestion_run_id = coverage.ingestion_run_id
        coverage_row.capability = coverage.capability
        coverage_row.start_at = coverage.start_at
        coverage_row.end_at = coverage.end_at
        coverage_row.first_observed_at = coverage.first_observed_at
        coverage_row.complete = coverage.complete
        session.add(coverage_row)
        sources.update(
            (
                ("activity", "coverage", coverage.coverage_id),
                ("activity", "coverage_parent", coverage.historical_evidence_id),
            )
        )
    for index, witness in enumerate(source.revisions):
        revision_row = _row(
            m.AggregateRevisionModel, auth.owner_id, root.id, index, witness, now, check
        )
        revision_row.account_id = witness.account_id
        revision_row.evidence_id = witness.evidence_id
        revision_row.new_source_record_id = witness.new_source_record_id
        revision_row.superseded_source_record_id = witness.superseded_source_record_id
        session.add(revision_row)
        sources.add(("activity", "revision", witness.evidence_id))
    for index, leg in enumerate(result.legs):
        flow_row = _row(m.AggregateFlowModel, auth.owner_id, root.id, index, leg, now, check)
        flow_row.account_id = leg.account_id
        flow_row.source_record_id = leg.source_record_id
        flow_row.amount = leg.amount
        flow_row.currency = None if leg.currency is None else str(leg.currency)
        flow_row.classification = leg.classification
        flow_row.counterpart_record_id = leg.counterpart_record_id
        session.add(flow_row)
    for index, pair in enumerate(result.matches):
        transfer_row = _row(
            m.AggregateTransferModel, auth.owner_id, root.id, index, pair, now, check
        )
        transfer_row.outgoing_record_id = pair.outgoing_record_id
        transfer_row.incoming_record_id = pair.incoming_record_id
        transfer_row.outgoing_account_id = pair.outgoing_account_id
        transfer_row.incoming_account_id = pair.incoming_account_id
        transfer_row.outgoing_principal = pair.outgoing_principal
        transfer_row.incoming_principal = pair.incoming_principal
        transfer_row.outgoing_currency = str(pair.outgoing_currency)
        transfer_row.incoming_currency = str(pair.incoming_currency)
        transfer_row.fx_rate = pair.fx_rate
        session.add(transfer_row)
