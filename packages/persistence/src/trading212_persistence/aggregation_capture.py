"""Capture exact saved canonical positions/cash and explicitly selected FX observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import aggregation as app
from trading212_domain.aggregation import AggregateFxBinding, AggregateSelectionContent
from trading212_domain.aggregation_inputs import (
    AggregateFxUse,
    AggregateHoldingsInput,
    AggregateNativeComponent,
    AggregateSnapshotPin,
)
from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.sources import ObservationState
from trading212_domain.values import CurrencyCode

from .aggregation_authorization import AggregateAuthorization
from .aggregation_sources import AggregateSourceAuthority, authorize_aggregate_sources
from .models import (
    CalculationRunModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .source_models import FxObservationModel, FxSnapshotModel


@dataclass(frozen=True, slots=True)
class CapturedAggregateHoldings:
    value: AggregateHoldingsInput
    authority: AggregateSourceAuthority


def _sources(value: object) -> tuple[UUID, ...]:
    if type(value) is not dict or set(value) != {"source_record_ids", "mapping_version", "origin"}:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    identifiers = value["source_record_ids"]
    if (
        type(identifiers) is not list
        or len(identifiers) > 10000
        or any(type(x) is not str for x in identifiers)
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    try:
        result = tuple(UUID(x) for x in identifiers)
    except ValueError:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE) from None
    if len(set(result)) != len(result):
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    return tuple(sorted(result))


def capture_holdings(
    session: Session,
    auth: AggregateAuthorization,
    selection: AggregateSelectionContent,
    bindings: tuple[AggregateFxBinding, ...],
    *,
    now: datetime,
    check_deadline: Callable[[], None],
) -> CapturedAggregateHoldings:
    check_deadline()
    if auth.account_ids != tuple(x.account_id for x in selection.members):
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    ids = tuple(x.portfolio_snapshot_id for x in selection.members)
    headers = session.execute(
        select(PortfolioSnapshotModel, CalculationRunModel.output_fingerprint)
        .join(
            CalculationRunModel, CalculationRunModel.id == PortfolioSnapshotModel.calculation_run_id
        )
        .where(
            PortfolioSnapshotModel.id.in_(ids),
            PortfolioSnapshotModel.broker_account_id.in_(auth.account_ids),
        )
        .with_for_update(read=True, of=PortfolioSnapshotModel)
    ).all()
    if len(headers) != len(ids):
        raise app.AggregateServiceError(app.AggregateErrorCode.NOT_FOUND)
    by_id = {row[0].id: row for row in headers}
    pins = []
    for member in selection.members:
        header, fingerprint = by_id[member.portfolio_snapshot_id]
        if (
            header.broker_account_id != member.account_id
            or header.source_cutoff_at > selection.source_cutoff_at
        ):
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        pins.append(
            AggregateSnapshotPin(
                account_id=member.account_id,
                portfolio_snapshot_id=header.id,
                calculation_run_id=header.calculation_run_id,
                calculation_version=header.calculation_version,
                valuation_at=header.valuation_at,
                source_cutoff_at=header.source_cutoff_at,
                reporting_currency=CurrencyCode(header.reporting_currency),
                quality=QualityState(header.quality_state),
                content_digest=fingerprint,
            )
        )
    selected_observations = session.execute(
        select(FxObservationModel.id, FxObservationModel.snapshot_id).where(
            FxObservationModel.owner_id == auth.owner_id,
            FxObservationModel.id.in_(x.fx_observation_id for x in bindings),
        )
    ).all()
    if {x[0] for x in selected_observations} != {x.fx_observation_id for x in bindings}:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    authority = authorize_aggregate_sources(
        session,
        auth,
        fx_ids=tuple(sorted({x[1] for x in selected_observations})),
        evidence_ids=(),
        cutoff=selection.source_cutoff_at,
        now=now,
    )
    check_deadline()
    positions = session.execute(
        select(SnapshotPositionModel, ListingModel.instrument_id)
        .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
        .where(SnapshotPositionModel.snapshot_id.in_(ids))
        .order_by(SnapshotPositionModel.snapshot_id, SnapshotPositionModel.id)
        .limit(10001)
    ).all()
    cash = tuple(
        session.scalars(
            select(SnapshotCashModel)
            .where(SnapshotCashModel.snapshot_id.in_(ids))
            .order_by(SnapshotCashModel.snapshot_id, SnapshotCashModel.id)
            .limit(257)
        )
    )
    if len(positions) > 10000 or len(cash) > 256:
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    components = []
    member_by_snapshot = {x.portfolio_snapshot_id: x.account_id for x in selection.members}
    for index, (row, instrument) in enumerate(positions):
        if index % 64 == 0:
            check_deadline()
        components.append(
            AggregateNativeComponent(
                component_id=row.id,
                account_id=member_by_snapshot[row.snapshot_id],
                portfolio_snapshot_id=row.snapshot_id,
                kind="position",
                listing_id=row.listing_id,
                instrument_id=instrument,
                quantity=row.quantity,
                native_currency=CurrencyCode(row.currency),
                native_value=row.market_value,
                quality=QualityState(row.quality_state),
                origin=ValueOrigin(row.value_origin),
                source_record_ids=_sources(row.provenance),
            )
        )
    components.extend(
        AggregateNativeComponent(
            component_id=row.id,
            account_id=member_by_snapshot[row.snapshot_id],
            portfolio_snapshot_id=row.snapshot_id,
            kind="cash",
            listing_id=None,
            instrument_id=None,
            quantity=None,
            native_currency=CurrencyCode(row.currency),
            native_value=row.amount,
            quality=QualityState(row.quality_state),
            origin=ValueOrigin(row.value_origin),
            source_record_ids=_sources(row.provenance),
        )
        for row in cash
    )
    source_ids = {x for row in components for x in row.source_record_ids}
    if len(source_ids) > 10000:
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    records = session.execute(
        select(
            SourceRecordModel.id,
            SourceRecordModel.broker_account_id,
            SourceRecordModel.provider,
            SourceRecordModel.capability,
            SourceRecordModel.provider_record_id,
        ).where(
            SourceRecordModel.id.in_(source_ids),
            SourceRecordModel.broker_account_id.in_(auth.account_ids),
        )
    ).all()
    source_accounts = {row[0]: row[1] for row in records}
    if len(source_accounts) != len(source_ids) or any(
        source_accounts.get(source) != row.account_id
        for row in components
        for source in row.source_record_ids
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    economic_sources = {row[0]: (row[1], row[2], row[3], row[4] or str(row[0])) for row in records}
    seen_economics: set[tuple[UUID, str, str, str]] = set()
    for component in components:
        if not component.source_record_ids:
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        for source_id in component.source_record_ids:
            economic = economic_sources[source_id]
            if component.kind == "position" and economic in seen_economics:
                # A repeated account/provider/external observation is not another
                # economic position. Canonical ingestion normally prevents this;
                # conflicting saved projection rows must fail closed here too.
                raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
            if component.kind == "position":
                seen_economics.add(economic)
    quotes = session.execute(
        select(FxObservationModel, FxSnapshotModel)
        .join(
            FxSnapshotModel,
            (FxSnapshotModel.owner_id == FxObservationModel.owner_id)
            & (FxSnapshotModel.id == FxObservationModel.snapshot_id),
        )
        .where(
            FxObservationModel.owner_id == auth.owner_id,
            FxObservationModel.id.in_(x.fx_observation_id for x in bindings),
        )
    ).all()
    quote_by_id = {row[0].id: row for row in quotes}
    uses = []
    for binding in bindings:
        if (
            binding.account_id not in auth.account_ids
            or binding.fx_observation_id not in quote_by_id
        ):
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        observation, snapshot = quote_by_id[binding.fx_observation_id]
        inverted = (observation.quote, observation.base) == (
            str(binding.currency),
            str(selection.reporting_currency),
        )
        uses.append(
            AggregateFxUse(
                account_id=binding.account_id,
                source_currency=binding.currency,
                target_currency=selection.reporting_currency,
                fx_snapshot_id=snapshot.id,
                fx_observation_id=observation.id,
                provider_id=snapshot.provider_id,
                license_version_id=snapshot.license_version_id,
                snapshot_digest=snapshot.content_digest,
                base_currency=CurrencyCode(observation.base),
                quote_currency=CurrencyCode(observation.quote),
                original_rate=observation.rate,
                inverted=inverted,
                effective_at=observation.effective_at,
                first_known_at=snapshot.first_observed_at,
                quality=QualityState(snapshot.quality),
                state=ObservationState(observation.state),
            )
        )
    order = {x.account_id: index for index, x in enumerate(selection.members)}
    result = AggregateHoldingsInput(
        owner_id=auth.owner_id,
        selection=selection,
        snapshots=tuple(pins),
        components=tuple(
            sorted(components, key=lambda x: (order[x.account_id], x.kind, x.component_id))
        ),
        fx_uses=tuple(sorted(uses, key=lambda x: (order[x.account_id], str(x.source_currency)))),
    )
    check_deadline()
    return CapturedAggregateHoldings(result, authority)
