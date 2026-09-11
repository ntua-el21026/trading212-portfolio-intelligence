"""Alert inputs from complete canonical valuation rows and published target trees."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.alerts import (
    cash_observation,
    direct_concentration_observation,
    drift_observation,
)
from trading212_analytics.planning import calculate_drift
from trading212_analytics.portfolio import FxQuote, convert_money
from trading212_analytics.quality import combine_quality
from trading212_domain import alerts as d
from trading212_domain import planning as p
from trading212_domain.enums import QualityState
from trading212_domain.reports import ReportSourceKind
from trading212_domain.values import CurrencyCode, FxRate, Instant, Money

from .alert_capture_common import AlertCaptureState, AlertCaptureUnavailable, bounded
from .models import (
    CalculationRunModel,
    PortfolioSnapshotModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .planning_inputs import capture_input, digest
from .portfolio_service import _FRESHNESS_SECONDS, _snapshot_quality
from .target_models import TargetVersionModel
from .target_service import PostgresTargetService


def selected_snapshot(state: AlertCaptureState) -> PortfolioSnapshotModel:
    model, calculation = PortfolioSnapshotModel, CalculationRunModel
    query = (
        select(model)
        .join(calculation, calculation.id == model.calculation_run_id)
        .where(
            model.broker_account_id == state.version.account_id,
            calculation.broker_account_id == state.version.account_id,
            model.valuation_at <= state.cutoff,
            model.source_cutoff_at <= state.cutoff,
            model.created_at <= state.cutoff,
            calculation.created_at <= state.cutoff,
            calculation.calculated_at <= state.cutoff,
            calculation.source_cutoff_at <= state.cutoff,
        )
    )
    if state.predicate.source_id is not None:
        query = query.where(model.id == state.predicate.source_id)
    row = state.session.scalar(
        query.order_by(model.valuation_at.desc(), model.created_at.desc(), model.id).limit(1)
    )
    if row is None:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    return row


def capture_snapshot(
    state: AlertCaptureState, snapshot: PortfolioSnapshotModel
) -> CalculationRunModel:
    calculation = state.session.get(CalculationRunModel, snapshot.calculation_run_id)
    if calculation is None or calculation.broker_account_id != state.version.account_id:
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    if (
        max(calculation.calculated_at, calculation.created_at, calculation.source_cutoff_at)
        > state.cutoff
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    coverage = snapshot.coverage if isinstance(snapshot.coverage, dict) else {}
    complete = coverage.get("is_complete", coverage.get("complete")) is True
    quality = _snapshot_quality(snapshot, now=state.cutoff)
    state.context = replace(
        state.context,
        valuation_at=snapshot.valuation_at,
        reporting_currency=CurrencyCode(snapshot.reporting_currency),
        quality=QualityState(quality.state.value),
        method_key=calculation.calculation_name,
        method_version=calculation.version,
        coverage=(d.AlertCoverageFact(key="valuation", complete=complete),),
        assumptions=tuple(calculation.assumptions),
        warnings=tuple(
            d.AlertWarning(code="valuation_warning", message=message)
            for message in quality.warnings
        ),
    )
    state.reference(
        kind=ReportSourceKind.PORTFOLIO_SNAPSHOT,
        identifier=snapshot.id,
        digest=digest(
            (
                snapshot.id,
                snapshot.calculation_run_id,
                snapshot.valuation_at,
                snapshot.source_cutoff_at,
                snapshot.reporting_currency,
                snapshot.cash_total,
                snapshot.invested_total,
                snapshot.portfolio_total,
                snapshot.quality_state,
                snapshot.coverage,
                snapshot.warnings,
            )
        ),
        effective_at=snapshot.valuation_at,
        known_at=snapshot.created_at,
    )
    state.reference(
        kind=ReportSourceKind.CALCULATION,
        identifier=calculation.id,
        digest=calculation.output_fingerprint,
        effective_at=calculation.valuation_at,
        known_at=max(calculation.calculated_at, calculation.created_at),
    )
    identifiers = [UUID(item) for item in bounded(calculation.input_ids, 8190)]
    records = list(
        state.session.scalars(
            select(SourceRecordModel).where(SourceRecordModel.id.in_(identifiers))
        )
    )
    if len(records) != len(set(identifiers)):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    for record in sorted(records, key=lambda item: item.id):
        capture_broker_record(state, record)
    state.bindings.append(
        d.AlertCanonicalBinding(
            family=d.AlertCanonicalFamily.VALUATION,
            role=d.AlertInputRole.SNAPSHOT,
            subject_id=snapshot.id,
            parent_id=calculation.id,
            content_digest=calculation.output_fingerprint,
            method_key=calculation.calculation_name,
            method_version=calculation.version,
        )
    )
    return calculation


def capture_broker_record(state: AlertCaptureState, record: SourceRecordModel) -> None:
    if (
        record.broker_account_id != state.version.account_id
        or max(record.observed_at, record.created_at) > state.cutoff
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    state.reference(
        kind=ReportSourceKind.BROKER_SOURCE_RECORD,
        identifier=record.id,
        digest=record.payload_fingerprint,
        effective_at=record.source_updated_at or record.observed_at,
        known_at=max(record.observed_at, record.created_at),
    )


def _quotes(state: AlertCaptureState, calculation: CalculationRunModel) -> dict[UUID, FxQuote]:
    raw = calculation.options.get("fx_quotes", []) if isinstance(calculation.options, dict) else []
    if not isinstance(raw, list):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
    result: dict[UUID, FxQuote] = {}
    for item in bounded(raw, 4096):
        if not isinstance(item, dict) or any(
            type(item.get(key)) is not str
            for key in ("listing_id", "source_record_id", "base_currency", "quote_currency", "rate")
        ):
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
        record = state.session.get(SourceRecordModel, UUID(str(item["source_record_id"])))
        if record is None:
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
        capture_broker_record(state, record)
        at = (
            datetime.fromisoformat(str(item["observed_at"]).replace("Z", "+00:00"))
            if isinstance(item.get("observed_at"), str)
            else record.source_updated_at or record.observed_at
        )
        if at > state.cutoff or at != (record.source_updated_at or record.observed_at):
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
        identifier = UUID(str(item["listing_id"]))
        quote = FxQuote(
            FxRate(
                CurrencyCode(str(item["base_currency"])),
                CurrencyCode(str(item["quote_currency"])),
                Decimal(str(item["rate"])),
                Instant(at),
                str(record.id),
            )
        )
        if identifier in result and result[identifier] != quote:
            raise AlertCaptureUnavailable(d.AlertReason.AMBIGUOUS_SOURCE)
        result[identifier] = quote
    return result


def capture_direct(state: AlertCaptureState) -> d.AlertThresholdInput:
    from .alert_capture_fx import convert_captured_money

    snapshot = selected_snapshot(state)
    calculation = capture_snapshot(state, snapshot)
    currency = CurrencyCode(snapshot.reporting_currency)
    cash_rows = bounded(
        list(
            state.session.scalars(
                select(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == snapshot.id)
                .order_by(SnapshotCashModel.currency)
                .limit(257)
            )
        ),
        256,
    )
    if snapshot.cash_total is None:
        raise AlertCaptureUnavailable(d.AlertReason.INCOMPLETE_COVERAGE)
    cash_currency = state.predicate.currency or currency
    cash = []
    for cash_row in cash_rows:
        state.reference(
            kind=ReportSourceKind.SNAPSHOT_CASH,
            identifier=cash_row.id,
            parent_id=snapshot.id,
            digest=digest(
                (
                    cash_row.id,
                    cash_row.amount,
                    cash_row.currency,
                    cash_row.quality_state,
                    cash_row.value_origin,
                    cash_row.provenance,
                )
            ),
            effective_at=snapshot.valuation_at,
            known_at=snapshot.created_at,
        )
        cash.append(
            convert_captured_money(
                state,
                Money(cash_row.amount, CurrencyCode(cash_row.currency)),
                cash_currency,
                at=snapshot.valuation_at,
            )
        )
    portfolio_total = (
        None if snapshot.portfolio_total is None else Money(snapshot.portfolio_total, currency)
    )
    if state.predicate.metric is d.AlertMetric.CASH_AMOUNT:
        qualities = [QualityState(row.quality_state) for row in cash_rows]
        if snapshot.quality_state in {"unreconciled", "failed"}:
            qualities.append(QualityState(snapshot.quality_state))
        if state.cutoff - snapshot.source_cutoff_at > timedelta(seconds=_FRESHNESS_SECONDS):
            qualities.append(QualityState.STALE)
        # Price gaps in unrelated positions do not change known cash. Preserve
        # each actual cash component's quality and the account reconciliation gate.
        state.context = replace(
            state.context,
            quality=combine_quality(qualities),
            coverage=(
                *state.context.coverage,
                d.AlertCoverageFact(
                    key="cash",
                    expected_count=len(cash_rows),
                    available_count=len(cash_rows),
                    complete=True,
                ),
            ),
        )
    if state.predicate.family is d.AlertFamily.CASH_THRESHOLD:
        observed = cash_observation(
            state.predicate,
            cash=tuple(cash),
            portfolio_total=portfolio_total,
            context=state.context,
        )
    else:
        positions = bounded(
            list(
                state.session.scalars(
                    select(SnapshotPositionModel)
                    .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                    .order_by(SnapshotPositionModel.listing_id)
                    .limit(4097)
                )
            ),
            4096,
        )
        quotes = _quotes(state, calculation)
        values = []
        for row in positions:
            state.reference(
                kind=ReportSourceKind.SNAPSHOT_POSITION,
                identifier=row.id,
                parent_id=snapshot.id,
                digest=digest(
                    (
                        row.id,
                        row.listing_id,
                        row.quantity,
                        row.market_value,
                        row.currency,
                        row.quality_state,
                        row.value_origin,
                        row.provenance,
                    )
                ),
                effective_at=snapshot.valuation_at,
                known_at=snapshot.created_at,
            )
            if row.market_value is None:
                raise AlertCaptureUnavailable(d.AlertReason.INCOMPLETE_COVERAGE)
            value = Money(row.market_value, CurrencyCode(row.currency))
            if value.amount < 0:
                raise AlertCaptureUnavailable(d.AlertReason.UNSUPPORTED)
            if value.currency != currency:
                quote = quotes.get(row.listing_id)
                conversion = convert_money(
                    value,
                    reporting_currency=currency,
                    fx_quotes=() if quote is None else (quote,),
                    source_cutoff_at=Instant(snapshot.source_cutoff_at),
                )
                if conversion.converted_value is None or conversion.rate is None:
                    raise AlertCaptureUnavailable(d.AlertReason.MISSING_FX)
                rate = conversion.rate
                state.fx_conversions.append(
                    d.AlertMoneyConversion(
                        original=value,
                        reporting_currency=currency,
                        converted=conversion.converted_value,
                        comparison_basis=conversion.converted_value.amount,
                        legs=(
                            d.AlertFxLeg(
                                base=rate.base_currency,
                                quote=rate.quote_currency,
                                rate=rate.rate,
                                source_reference_key=(
                                    f"{ReportSourceKind.BROKER_SOURCE_RECORD.value}.{rate.source}"
                                ),
                                snapshot_id=None,
                                provider_id=None,
                                observed_at=rate.observed_at.value,
                                inverse=conversion.inverted,
                            ),
                        ),
                    )
                )
                value = conversion.converted_value
            values.append(value)
        if any(item.amount < 0 for item in cash):
            raise AlertCaptureUnavailable(d.AlertReason.UNSUPPORTED)
        observed = direct_concentration_observation(
            state.predicate,
            positions=tuple(values),
            cash=tuple(cash),
            portfolio_total=portfolio_total,
            context=state.context,
        )
    complete = state.context.coverage[0].complete is True
    if state.predicate.metric is d.AlertMetric.CASH_AMOUNT:
        complete = True  # Known cash does not require complete prices for unrelated positions.
    if not complete:
        observed = replace(
            observed,
            material_complete=False,
            observed=replace(
                observed.observed,
                availability=d.AlertAvailability.PARTIAL
                if observed.observed.value is not None
                else d.AlertAvailability.UNAVAILABLE,
            ),
        )
    return d.AlertThresholdInput(observation=observed)


def capture_drift(
    state: AlertCaptureState, *, sessions: sessionmaker[Session], cursor_signing_key: bytes
) -> d.AlertThresholdInput:
    snapshot = selected_snapshot(state)
    capture_snapshot(state, snapshot)
    version = state.session.get(TargetVersionModel, state.predicate.target_version_id)
    if (
        version is None
        or version.owner_id != state.version.owner_id
        or version.published_at is None
        or version.content_digest is None
        or max(version.created_at, version.published_at, version.effective_at) > state.cutoff
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    targets = PostgresTargetService(
        sessions=sessions, cursor_signing_key=cursor_signing_key, clock=lambda: state.now
    )
    value = capture_input(
        state.session,
        owner=state.version.owner_id,
        account=state.version.account_id,
        portfolio_id=version.virtual_portfolio_id,
        target_id=version.id,
        snapshot_id=snapshot.id,
        options=p.PlanningOptions(
            Money(Decimal(0), CurrencyCode(snapshot.reporting_currency)),
            p.PlanningMode.GLOBAL,
            p.CoveragePolicy(state.version.definition.quality_policy.value),
        ),
        targets=targets,
    )
    if any(
        max(item.effective_at, item.first_observed_at) > state.cutoff
        for item in value.valuation.sources
    ):
        raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
    result = calculate_drift(value)
    state.reference(
        kind=ReportSourceKind.TARGET_VERSION,
        identifier=version.id,
        parent_id=version.virtual_portfolio_id,
        digest=version.content_digest,
        effective_at=version.effective_at,
        known_at=version.published_at,
    )
    state.bindings.append(
        d.AlertCanonicalBinding(
            family=d.AlertCanonicalFamily.TARGET,
            role=d.AlertInputRole.TARGET_VERSION,
            subject_id=version.id,
            parent_id=version.virtual_portfolio_id,
            content_digest=version.content_digest,
        )
    )
    state.bindings.append(
        d.AlertCanonicalBinding(
            family=d.AlertCanonicalFamily.PLANNING,
            role=d.AlertInputRole.INPUT,
            subject_id=snapshot.id,
            content_digest=digest(value),
            method_key=result.context.method,
            method_version=result.context.method_version,
        )
    )
    state.context = replace(
        state.context,
        method_key=result.context.method,
        method_version=result.context.method_version,
        quality=combine_quality((result.context.quality, state.context.quality)),
    )
    observed = drift_observation(state.predicate, result, context_key=state.context.key)
    observed = replace(
        observed,
        observed=replace(
            observed.observed,
            quality=combine_quality((observed.observed.quality, state.context.quality)),
        ),
    )
    return d.AlertThresholdInput(observation=observed)
