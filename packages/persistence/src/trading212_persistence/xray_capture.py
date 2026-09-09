"""Build immutable X-ray inputs from authorized saved portfolio and licensed evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import xray as app
from trading212_domain import xray as d
from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.values import CurrencyCode, Instant, Money
from trading212_domain.xray_codec import decode_xray_policy, encode_xray_input

from .models import (
    CalculationRunModel,
    ListingModel,
    PortfolioSnapshotModel,
    PositionObservationModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .source_store import digest
from .xray_base import xray_error
from .xray_capture_base import XrayCaptureState, bounded_rows
from .xray_capture_catalog import capture_catalog
from .xray_catalog_models import XrayPolicyVersionModel
from .xray_ingestion import XrayIngestion


@dataclass(frozen=True, slots=True)
class XrayCapturedInput:
    value: d.XrayInput
    targets: dict[UUID, tuple[str, UUID]]
    valuation_run_id: UUID
    canonical_input: bytes


def money(
    value: Decimal | None,
    currency: str,
    quality: str,
    origin: str,
    refs: tuple[UUID, ...],
    reason: d.XrayReason = d.XrayReason.MISSING_VALUE,
) -> d.XrayMoneyMetric:
    return d.XrayMoneyMetric(
        None if value is None else Money(value, CurrencyCode(currency)),
        reason if value is None else None,
        QualityState(quality),
        ValueOrigin.UNAVAILABLE if value is None else ValueOrigin(origin),
        d.XrayBound.EXACT,
        d.XrayAvailability.UNAVAILABLE if value is None else d.XrayAvailability.AVAILABLE,
        None,
        refs,
    )


def capture_xray(
    service: XrayIngestion,
    session: Session,
    owner: UUID,
    account: UUID,
    request: app.XrayRunRequest,
) -> XrayCapturedInput:
    from trading212_analytics.xray import build_xray_reconciliation

    from .xray_capture_fx import convert_capture_values

    snapshot = session.scalar(
        select(PortfolioSnapshotModel).where(
            PortfolioSnapshotModel.id == UUID(request.snapshot_id),
            PortfolioSnapshotModel.broker_account_id == account,
        )
    )
    if snapshot is None:
        raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
    if (
        request.source_cutoff_at > service._now()
        or request.source_cutoff_at < snapshot.source_cutoff_at
    ):
        raise xray_error(app.XrayServiceErrorCode.VALIDATION_FAILED)
    calculation = session.scalar(
        select(CalculationRunModel).where(
            CalculationRunModel.id == snapshot.calculation_run_id,
            CalculationRunModel.broker_account_id == account,
        )
    )
    if (
        calculation is None
        or calculation.valuation_at != snapshot.valuation_at
        or calculation.reporting_currency != snapshot.reporting_currency
    ):
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    policy_row = session.scalar(
        select(XrayPolicyVersionModel)
        .where(
            XrayPolicyVersionModel.owner_id == owner,
            XrayPolicyVersionModel.account_id == account,
            XrayPolicyVersionModel.first_observed_at <= request.source_cutoff_at,
            XrayPolicyVersionModel.effective_at <= snapshot.valuation_at,
        )
        .order_by(
            XrayPolicyVersionModel.effective_at.desc(),
            XrayPolicyVersionModel.first_observed_at.desc(),
            XrayPolicyVersionModel.id.desc(),
        )
        .limit(1)
    )
    if policy_row is None:
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    policy = decode_xray_policy(policy_row.canonical_policy)
    from hashlib import sha256

    if (
        policy.id != policy_row.id
        or sha256(policy_row.canonical_policy).hexdigest() != policy_row.content_digest
    ):
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    state = XrayCaptureState(owner, snapshot, request.source_cutoff_at, policy)
    calculation_ref = state.dependency(
        d.XrayDependencyKind.VALUATION,
        d.XraySubjectKind.SOURCE_RECORD,
        calculation.id,
        d.XrayReferenceKind.CALCULATION_RUN,
        calculation.id,
        None,
        target=("valuation_run_id", calculation.id),
        fingerprint=digest((calculation.input_fingerprint, calculation.output_fingerprint)),
    )
    snapshot_ref = state.dependency(
        d.XrayDependencyKind.VALUATION,
        d.XraySubjectKind.SOURCE_RECORD,
        snapshot.id,
        d.XrayReferenceKind.PORTFOLIO_SNAPSHOT,
        snapshot.id,
        calculation.id,
        target=("valuation_run_id", calculation.id),
        fingerprint=digest((str(snapshot.id), calculation.output_fingerprint)),
    )
    if isinstance(policy.thresholds, d.ConcentrationThresholdPolicy):
        threshold = policy.thresholds
        state.dependencies[threshold.source_reference_id] = d.XraySourceDependency(
            threshold.source_reference_id,
            owner,
            account,
            snapshot.id,
            d.XrayDependencyKind.THRESHOLD,
            d.XraySubjectKind.POLICY,
            threshold.id,
            None,
            None,
            policy_row.content_digest,
            d.XrayPhysicalReference(d.XrayReferenceKind.OWNER_POLICY, policy_row.id, None),
        )
        state.dependency_targets[threshold.source_reference_id] = (
            "threshold_policy_id",
            policy_row.id,
        )
    position_rows = bounded_rows(
        session,
        select(SnapshotPositionModel)
        .where(SnapshotPositionModel.snapshot_id == snapshot.id)
        .order_by(SnapshotPositionModel.id),
        10_000,
    )
    cash_rows = bounded_rows(
        session,
        select(SnapshotCashModel)
        .where(SnapshotCashModel.snapshot_id == snapshot.id)
        .order_by(SnapshotCashModel.id),
        min(32, 10_000 - len(position_rows)),
    )
    positions: list[d.XrayPosition] = []
    broker_fx: list[d.XrayBrokerFx] = []
    raw_quotes = calculation.options.get("fx_quotes", [])
    if not isinstance(raw_quotes, list) or len(raw_quotes) > 10_000:
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    quotes: dict[tuple[UUID, UUID], dict[str, object]] = {}
    for raw in raw_quotes:
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "listing_id",
                "source_record_id",
                "base_currency",
                "quote_currency",
                "rate",
                "observed_at",
                "source",
            }
            or any(not isinstance(item, str) for item in raw.values())
        ):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        key = (UUID(str(raw["listing_id"])), UUID(str(raw["source_record_id"])))
        if key in quotes:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        quotes[key] = raw
    for row in position_rows:
        listing = session.get(ListingModel, row.listing_id)
        if listing is None:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        reference = state.dependency(
            d.XrayDependencyKind.VALUATION,
            d.XraySubjectKind.SNAPSHOT_POSITION,
            row.id,
            d.XrayReferenceKind.SNAPSHOT_POSITION,
            row.id,
            snapshot.id,
            target=("valuation_run_id", calculation.id),
            fingerprint=digest((str(row.id), row.market_value, row.currency, row.provenance)),
        )
        references: tuple[UUID, ...] = (reference, calculation_ref)
        identifiers = row.provenance.get("source_record_ids", [])
        if (
            not isinstance(identifiers, list)
            or len(identifiers) > 256
            or any(not isinstance(item, str) for item in identifiers)
        ):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        records = tuple(UUID(item) for item in identifiers)
        observations = bounded_rows(
            session,
            select(PositionObservationModel)
            .where(
                PositionObservationModel.broker_account_id == account,
                PositionObservationModel.listing_id == row.listing_id,
                PositionObservationModel.source_record_id.in_(records),
                PositionObservationModel.observed_at <= snapshot.source_cutoff_at,
            )
            .order_by(PositionObservationModel.observed_at.desc(), PositionObservationModel.id),
            2,
        )
        if len(observations) > 1:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        original = money(
            row.market_value, row.currency, row.quality_state, row.value_origin, references
        )
        fx_refs: tuple[UUID, ...] = ()
        if observations:
            observed = observations[0]
            source = session.scalar(
                select(SourceRecordModel).where(
                    SourceRecordModel.id == observed.source_record_id,
                    SourceRecordModel.broker_account_id == account,
                    SourceRecordModel.observed_at <= snapshot.source_cutoff_at,
                )
            )
            if (
                source is None
                or source.id not in records
                or str(source.id) not in calculation.input_ids
            ):
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            source_ref = state.dependency(
                d.XrayDependencyKind.VALUATION,
                d.XraySubjectKind.SOURCE_RECORD,
                source.id,
                d.XrayReferenceKind.BROKER_SOURCE_RECORD,
                source.id,
                account,
                target=("broker_source_record_id", source.id),
                fingerprint=digest(source.payload_fingerprint),
            )
            references += (source_ref,)
            original = money(
                observed.provider_market_value,
                observed.valuation_currency,
                row.quality_state,
                "observed_provider",
                references,
            )
            if observed.valuation_currency != row.currency:
                raw = quotes.get((row.listing_id, source.id))
                if raw is not None:
                    fx_ref = state.dependency(
                        d.XrayDependencyKind.BROKER_FX,
                        d.XraySubjectKind.SOURCE_RECORD,
                        source.id,
                        d.XrayReferenceKind.BROKER_SOURCE_RECORD,
                        source.id,
                        account,
                        target=("broker_source_record_id", source.id),
                        fingerprint=digest(source.payload_fingerprint),
                    )
                    fx_refs = (fx_ref,)
                    broker_fx.append(
                        d.XrayBrokerFx(
                            f"position:{row.id}",
                            fx_ref,
                            calculation_ref,
                            source.id,
                            calculation.id,
                            row.listing_id,
                            CurrencyCode(str(raw["base_currency"])),
                            CurrencyCode(str(raw["quote_currency"])),
                            Decimal(str(raw["rate"])),
                            Instant.parse(str(raw["observed_at"])),
                            Instant(source.observed_at),
                            str(raw["source"]),
                            QualityState(row.quality_state),
                            None,
                        )
                    )
                elif row.market_value is not None:
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        positions.append(
            d.XrayPosition(
                d.PositionRoot(row.id, listing.instrument_id, row.listing_id),
                original,
                money(
                    row.market_value,
                    row.currency,
                    row.quality_state,
                    row.value_origin,
                    references + fx_refs,
                ),
                references,
                fx_refs,
            )
        )
    cash = tuple(
        d.XrayCash(
            d.CashRoot(row.id, CurrencyCode(row.currency)),
            money(
                row.amount,
                row.currency,
                row.quality_state,
                row.value_origin,
                (reference, calculation_ref),
            ),
            money(
                row.amount,
                row.currency,
                row.quality_state,
                row.value_origin,
                (reference, calculation_ref),
            ),
            (reference, calculation_ref),
            (),
        )
        for row in cash_rows
        for reference in (
            state.dependency(
                d.XrayDependencyKind.VALUATION,
                d.XraySubjectKind.SNAPSHOT_CASH,
                row.id,
                d.XrayReferenceKind.SNAPSHOT_CASH,
                row.id,
                snapshot.id,
                target=("valuation_run_id", calculation.id),
                fingerprint=digest((str(row.id), row.amount, row.currency, row.provenance)),
            ),
        )
    )
    reporting = (
        request.currency.reporting_currency
        if isinstance(request.currency, app.ExplicitCurrency)
        else CurrencyCode(snapshot.reporting_currency)
    )
    total = money(
        snapshot.portfolio_total,
        snapshot.reporting_currency,
        snapshot.quality_state,
        "derived_deterministic",
        (snapshot_ref, calculation_ref),
    )
    converted_positions, converted_cash, total, licensed_fx = convert_capture_values(
        service, session, state, tuple(positions), cash, total, reporting
    )
    catalog = capture_catalog(
        service, session, state, {row.root.instrument_id for row in converted_positions}
    )
    all_roots: tuple[d.XrayPosition | d.XrayCash, ...] = (*converted_positions, *converted_cash)
    coverage = d.XrayValuationCoverage(
        all(row.reporting_value.value is not None for row in all_roots),
        tuple(row.root.key for row in all_roots if row.reporting_value.value is not None),
        tuple(row.root.key for row in all_roots if row.reporting_value.value is None),
    )
    reconciliation = build_xray_reconciliation(converted_positions, converted_cash, total)
    value = d.XrayInput(
        owner,
        account,
        snapshot.id,
        digest((str(snapshot.id), calculation.output_fingerprint)),
        Instant(snapshot.valuation_at),
        Instant(request.source_cutoff_at),
        reporting,
        policy,
        converted_positions,
        converted_cash,
        total,
        coverage,
        reconciliation,
        catalog.definitions,
        catalog.mappings,
        catalog.constituents,
        catalog.identities,
        catalog.relationships,
        catalog.classifications,
        tuple(state.dependencies.values()),
        broker_fx=tuple(broker_fx),
        licensed_fx=licensed_fx,
    )
    return XrayCapturedInput(
        value, state.dependency_targets, calculation.id, encode_xray_input(value)
    )
