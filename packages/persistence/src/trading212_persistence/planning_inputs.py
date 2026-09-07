"""Capture authorized normalized snapshots without reading current service projections."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.planning import PlanningServiceError, PlanningServiceErrorCode
from trading212_application.planning_jobs import PlanJobFailureCode, PlanJobInputError
from trading212_domain import planning as d
from trading212_domain import targets as t
from trading212_domain.enums import QualityState
from trading212_domain.serialization import canonical_json
from trading212_domain.values import CurrencyCode, Money

from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CalculationRunModel,
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .target_models import (
    TargetHoldingModel,
    TargetNodeModel,
    TargetVersionModel,
    VirtualPortfolioModel,
)
from .target_service import PostgresTargetService


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def unavailable() -> PlanningServiceError:
    return PlanningServiceError(
        PlanningServiceErrorCode.NOT_FOUND, "The requested resource was not found."
    )


def bounded[T](items: list[T], limit: int) -> list[T]:
    if len(items) > limit:
        raise PlanningServiceError(
            PlanningServiceErrorCode.RESULT_TOO_LARGE,
            "The planning input exceeds its supported bound.",
        )
    return items


def capture_input(
    session: Session,
    *,
    owner: UUID,
    account: UUID,
    portfolio_id: UUID,
    target_id: UUID,
    snapshot_id: UUID,
    options: d.PlanningOptions,
    targets: PostgresTargetService,
) -> d.PlanningInput:
    account_owner = session.scalar(
        select(BrokerConnectionModel.owner_id)
        .join(BrokerAccountModel)
        .where(BrokerAccountModel.id == account)
    )
    portfolio = session.get(VirtualPortfolioModel, portfolio_id)
    version = session.get(TargetVersionModel, target_id)
    snapshot = session.get(PortfolioSnapshotModel, snapshot_id)
    if (
        account_owner != owner
        or portfolio is None
        or portfolio.owner_id != owner
        or portfolio.broker_account_id != account
        or version is None
        or version.owner_id != owner
        or version.virtual_portfolio_id != portfolio.id
        or snapshot is None
        or snapshot.broker_account_id != account
    ):
        raise unavailable()
    if version.published_at is None or version.content_digest is None:
        raise PlanningServiceError(
            PlanningServiceErrorCode.IMMUTABLE_VERSION, "A published target version is required."
        )
    if (
        options.contribution.currency.value != version.reporting_currency
        or snapshot.reporting_currency != version.reporting_currency
    ):
        raise PlanningServiceError(
            PlanningServiceErrorCode.CURRENCY_MISMATCH, "The reporting currencies do not match."
        )
    calculation = session.get(CalculationRunModel, snapshot.calculation_run_id)
    if calculation is None or calculation.broker_account_id != account:
        raise unavailable()
    content = targets._content(session, version)
    nodes = list(
        session.scalars(
            select(TargetNodeModel)
            .where(TargetNodeModel.target_version_id == target_id)
            .order_by(TargetNodeModel.key)
        )
    )
    holdings = {
        h.node_id: h
        for h in session.scalars(
            select(TargetHoldingModel).where(TargetHoldingModel.target_version_id == target_id)
        )
    }
    identities = tuple(
        d.PlanningNodeIdentity(
            str(n.id), n.key, str(holdings[n.id].id) if n.id in holdings else None
        )
        for n in nodes
    )
    positions = bounded(
        list(
            session.scalars(
                select(SnapshotPositionModel)
                .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                .order_by(SnapshotPositionModel.listing_id)
                .limit(4097)
            )
        ),
        4096,
    )
    cash = bounded(
        list(
            session.scalars(
                select(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == snapshot.id)
                .order_by(SnapshotCashModel.currency)
                .limit(257)
            )
        ),
        256,
    )
    instrument_ids = {h.instrument_id for h in holdings.values() if h.instrument_id is not None}
    position_listings = {
        listing.id: listing
        for listing in session.scalars(
            select(ListingModel).where(ListingModel.id.in_([p.listing_id for p in positions]))
        )
    }
    # Only target instruments need funding choices; unclassified observed instruments
    # retain their independent listing/instrument identities in valuation positions.
    instruments = bounded(
        list(
            session.scalars(
                select(InstrumentModel)
                .where(InstrumentModel.id.in_(instrument_ids))
                .order_by(InstrumentModel.id)
                .limit(1025)
            )
        ),
        1024,
    )
    listings = bounded(
        list(
            session.scalars(
                select(ListingModel)
                .where(ListingModel.instrument_id.in_(instrument_ids))
                .order_by(ListingModel.id)
                .limit(4097)
            )
        ),
        4096,
    )
    catalog = t.TargetCatalog(
        tuple(t.TargetInstrumentReference(x.id) for x in instruments),
        tuple(
            t.TargetListingReference(
                x.id, x.instrument_id, x.status == "active" and x.valid_to is None
            )
            for x in listings
        ),
    )
    sources: list[d.PlanningSource] = []
    source_ids = bounded(calculation.input_ids, 8190)
    records = {
        r.id: r
        for r in session.scalars(
            select(SourceRecordModel).where(SourceRecordModel.id.in_([UUID(x) for x in source_ids]))
        )
    }
    if len(records) != len(set(source_ids)) or any(
        r.broker_account_id != account for r in records.values()
    ):
        raise unavailable()
    sources.extend(
        d.PlanningSource(
            "provider_observation",
            str(record.id),
            record.payload_fingerprint,
            record.schema_version,
            record.source_updated_at or record.observed_at,
            record.observed_at,
        )
        for record in sorted(records.values(), key=lambda r: str(r.id))
    )
    options_raw = calculation.options if isinstance(calculation.options, dict) else {}
    quotes = options_raw.get("fx_quotes", [])
    rates: dict[str, d.PlanningFxRate] = {}
    if not isinstance(quotes, list) or len(quotes) > 4096:
        raise unavailable()
    for quote in quotes:
        if not isinstance(quote, dict) or not all(
            isinstance(quote.get(k), str)
            for k in ("listing_id", "source_record_id", "base_currency", "quote_currency", "rate")
        ):
            raise unavailable()
        record_id = UUID(str(quote["source_record_id"]))
        fx_record = records.get(record_id)
        if fx_record is None:
            fx_record = session.get(SourceRecordModel, record_id)
        if fx_record is None or fx_record.broker_account_id != account:
            raise unavailable()
        source = d.PlanningSource(
            "provider_fx_observation",
            str(fx_record.id),
            fx_record.payload_fingerprint,
            fx_record.schema_version,
            datetime.fromisoformat(str(quote["observed_at"]).replace("Z", "+00:00"))
            if isinstance(quote.get("observed_at"), str)
            else fx_record.source_updated_at or fx_record.observed_at,
            fx_record.observed_at,
        )
        sources.append(source)
        rates[str(quote["listing_id"])] = d.PlanningFxRate(
            source,
            CurrencyCode(str(quote["base_currency"])),
            CurrencyCode(str(quote["quote_currency"])),
            Decimal(str(quote["rate"])),
        )
    valued: list[d.ValuationPosition] = []
    for row in positions:
        listing = position_listings.get(row.listing_id)
        if listing is None:
            raise unavailable()
        money = (
            None
            if row.market_value is None
            else Money(row.market_value, CurrencyCode(row.currency))
        )
        # Materialized values may already be converted. Their own currency is authoritative.
        fx = rates.get(str(row.listing_id)) if row.currency != snapshot.reporting_currency else None
        valued.append(
            d.ValuationPosition(
                str(row.listing_id),
                str(listing.instrument_id),
                money,
                QualityState(row.quality_state),
                fx,
            )
        )
    valued_cash = tuple(
        d.ValuationCash(
            Money(row.amount, CurrencyCode(row.currency)), QualityState(row.quality_state)
        )
        for row in cash
    )
    valuation_digest = digest(
        {
            "snapshot_id": snapshot.id,
            "valuation_at": snapshot.valuation_at,
            "source_cutoff_at": snapshot.source_cutoff_at,
            "currency": snapshot.reporting_currency,
            "positions": tuple(valued),
            "cash": valued_cash,
            "total": snapshot.portfolio_total,
            "quality": snapshot.quality_state,
            "coverage": snapshot.coverage,
            "calculation_digest": calculation.output_fingerprint,
        }
    )
    sources.extend(
        (
            d.PlanningSource(
                "portfolio_snapshot",
                str(snapshot.id),
                valuation_digest,
                snapshot.calculation_version,
                snapshot.valuation_at,
                snapshot.created_at,
            ),
            d.PlanningSource(
                "calculation_run",
                str(calculation.id),
                calculation.output_fingerprint,
                calculation.version,
                calculation.valuation_at,
                calculation.calculated_at,
            ),
        )
    )
    coverage = snapshot.coverage if isinstance(snapshot.coverage, dict) else {}
    complete = coverage.get("is_complete", coverage.get("complete", False)) is True
    missing = tuple(calculation.missing_inputs)
    reconciled = snapshot.quality_state != "unreconciled" and not any(
        "reconcil" in x for x in missing
    )
    valuation = d.ValuationInput(
        str(snapshot.id),
        str(account),
        CurrencyCode(snapshot.reporting_currency),
        snapshot.valuation_at,
        snapshot.source_cutoff_at,
        valuation_digest,
        tuple(valued),
        valued_cash,
        None
        if snapshot.portfolio_total is None
        else Money(snapshot.portfolio_total, CurrencyCode(snapshot.reporting_currency)),
        QualityState(snapshot.quality_state),
        complete,
        reconciled,
        missing,
        tuple(bounded(list({(s.kind, s.id): s for s in sources}.values()), 8191)),
    )
    return d.PlanningInput(
        valuation,
        str(portfolio.id),
        str(version.id),
        version.content_digest,
        version.effective_at,
        version.published_at,
        content,
        identities,
        catalog,
        options,
    )


def verify_references(session: Session, *, owner: UUID, value: d.PlanningInput) -> None:
    """Reauthorize immutable economic references; never reload latest values or FX."""
    account = UUID(value.valuation.account_id)
    actual_owner = session.scalar(
        select(BrokerConnectionModel.owner_id)
        .join(BrokerAccountModel)
        .where(BrokerAccountModel.id == account)
    )
    if actual_owner != owner:
        raise PlanJobInputError(PlanJobFailureCode.ACCESS_DENIED)
    version = session.get(TargetVersionModel, UUID(value.target_version_id))
    snapshot = session.get(PortfolioSnapshotModel, UUID(value.valuation.snapshot_id))
    if (
        version is None
        or snapshot is None
        or version.owner_id != owner
        or snapshot.broker_account_id != account
    ):
        raise PlanJobInputError(PlanJobFailureCode.INPUT_UNAVAILABLE)
    if (
        version.content_digest != value.target_content_digest
        or version.published_at != value.target_published_at
        or version.effective_at != value.target_effective_at
    ):
        raise PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED)
    source_records = {
        row.id: row
        for row in session.scalars(
            select(SourceRecordModel).where(
                SourceRecordModel.id.in_(
                    {
                        UUID(source.id)
                        for source in value.valuation.sources
                        if source.kind in {"provider_observation", "provider_fx_observation"}
                    }
                )
            )
        )
    }
    for source in value.valuation.sources:
        if source.kind in {"provider_observation", "provider_fx_observation"}:
            record = source_records.get(UUID(source.id))
            if record is None or record.broker_account_id != account:
                raise PlanJobInputError(PlanJobFailureCode.INPUT_UNAVAILABLE)
            if (
                record.payload_fingerprint != source.content_digest
                or (
                    source.kind == "provider_observation"
                    and (record.source_updated_at or record.observed_at) != source.effective_at
                )
                or record.observed_at != source.first_observed_at
            ):
                raise PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED)
        elif source.kind == "calculation_run":
            calculation = session.get(CalculationRunModel, UUID(source.id))
            if (
                calculation is None
                or calculation.broker_account_id != account
                or calculation.output_fingerprint != source.content_digest
            ):
                raise PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED)
