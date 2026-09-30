"""Exact saved snapshot/FX/activity inputs admitted by current owner authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from .aggregation import (
    MAX_AGGREGATE_ACTIVITY,
    MAX_AGGREGATE_CURRENCIES,
    MAX_AGGREGATE_FX_BINDINGS,
    MAX_AGGREGATE_HOLDINGS,
    AggregateActivityWindow,
    AggregateReason,
    AggregateRecord,
    AggregateSelectionContent,
    aggregate_bound,
    aggregate_unique,
)
from .enums import QualityState, ValueOrigin
from .errors import fail_validation
from .sources import ObservationState
from .values import CurrencyCode


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateSnapshotPin(AggregateRecord):
    account_id: UUID
    portfolio_snapshot_id: UUID
    calculation_run_id: UUID
    calculation_version: str
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    quality: QualityState
    content_digest: str

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if self.source_cutoff_at > self.valuation_at:
            fail_validation("Snapshot cutoff exceeds valuation.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateNativeComponent(AggregateRecord):
    component_id: UUID
    account_id: UUID
    portfolio_snapshot_id: UUID
    kind: Literal["position", "cash"]
    listing_id: UUID | None
    instrument_id: UUID | None
    quantity: Decimal | None
    native_currency: CurrencyCode
    native_value: Decimal | None
    quality: QualityState
    origin: ValueOrigin
    source_record_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        position = self.kind == "position"
        if position != all(
            x is not None for x in (self.listing_id, self.instrument_id, self.quantity)
        ):
            fail_validation("Position identity and quantity are required together.")
        if not position and any(
            x is not None for x in (self.listing_id, self.instrument_id, self.quantity)
        ):
            fail_validation("Cash cannot claim a listing or instrument quantity.")
        aggregate_unique(self.source_record_ids, "component.sources")
        aggregate_bound(len(self.source_record_ids) <= MAX_AGGREGATE_ACTIVITY, "component.sources")
        if self.native_value is None and self.origin != ValueOrigin.UNAVAILABLE:
            fail_validation("Unavailable native value requires unavailable origin.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateFxUse(AggregateRecord):
    account_id: UUID
    source_currency: CurrencyCode
    target_currency: CurrencyCode
    fx_snapshot_id: UUID
    fx_observation_id: UUID
    provider_id: UUID
    license_version_id: UUID
    snapshot_digest: str
    base_currency: CurrencyCode
    quote_currency: CurrencyCode
    original_rate: Decimal | None
    inverted: bool
    effective_at: datetime
    first_known_at: datetime
    quality: QualityState
    state: ObservationState = ObservationState.AVAILABLE

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        pair = (self.source_currency, self.target_currency)
        original = (self.base_currency, self.quote_currency)
        if (
            ((self.original_rate is not None) != (self.state == ObservationState.AVAILABLE))
            or (self.original_rate is not None and self.original_rate <= 0)
            or pair[0] == pair[1]
            or (original != (pair[::-1] if self.inverted else pair))
        ):
            fail_validation("An exact positive direct or inverse FX observation is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateHoldingsInput(AggregateRecord):
    owner_id: UUID
    selection: AggregateSelectionContent
    snapshots: tuple[AggregateSnapshotPin, ...]
    components: tuple[AggregateNativeComponent, ...]
    fx_uses: tuple[AggregateFxUse, ...]

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        wanted = tuple((x.account_id, x.portfolio_snapshot_id) for x in self.selection.members)
        if tuple((x.account_id, x.portfolio_snapshot_id) for x in self.snapshots) != wanted:
            fail_validation("Saved snapshot pins differ from the ordered selection.")
        pins = {x.account_id: x for x in self.snapshots}
        if any(x.source_cutoff_at > self.selection.source_cutoff_at for x in self.snapshots):
            fail_validation("A saved snapshot contains knowledge after the aggregate cutoff.")
        aggregate_bound(
            sum(x.kind == "position" for x in self.components) <= MAX_AGGREGATE_HOLDINGS, "holdings"
        )
        aggregate_bound(len(self.components) <= MAX_AGGREGATE_HOLDINGS + 256, "components")
        aggregate_unique(tuple(x.component_id for x in self.components), "components")
        aggregate_unique(
            tuple(
                (x.account_id, x.kind, x.listing_id if x.kind == "position" else x.native_currency)
                for x in self.components
            ),
            "components.economics",
        )
        for row in self.components:
            if (
                row.account_id not in pins
                or row.portfolio_snapshot_id != pins[row.account_id].portfolio_snapshot_id
            ):
                fail_validation("A component belongs to a different saved snapshot.")
        currencies = {x.native_currency for x in self.components} | {
            self.selection.reporting_currency
        }
        aggregate_bound(len(currencies) <= MAX_AGGREGATE_CURRENCIES, "currencies")
        aggregate_bound(len(self.fx_uses) <= MAX_AGGREGATE_FX_BINDINGS, "fx")
        aggregate_unique(tuple((x.account_id, x.source_currency) for x in self.fx_uses), "fx")
        for use in self.fx_uses:
            if (
                use.account_id not in pins
                or use.target_currency != self.selection.reporting_currency
                or (
                    use.source_currency
                    not in {
                        x.native_currency for x in self.components if x.account_id == use.account_id
                    }
                )
                or use.effective_at > pins[use.account_id].valuation_at
                or use.first_known_at > self.selection.source_cutoff_at
            ):
                fail_validation("FX proof differs from its selected member or cutoff.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateTransferAttestation(AggregateRecord):
    """Only an exact retained provider schema may supply this complete original witness."""

    counterparty_account_id: UUID
    transfer_reference: str
    principal: Decimal
    currency: CurrencyCode
    fx_rate: Decimal | None
    fx_base_currency: CurrencyCode | None
    fx_quote_currency: CurrencyCode | None
    fee_record_id: UUID | None
    fee_amount: Decimal | None
    fee_currency: CurrencyCode | None
    fee_record_key: str | None = None

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if self.principal == 0:
            fail_validation("Transfer principal must be nonzero.")
        if len(self.transfer_reference) > 128:
            fail_validation("Transfer reference exceeds its bound.")
        if any(
            x is not None for x in (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
        ) and not all(
            x is not None for x in (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
        ):
            fail_validation("Transfer FX witness must be complete.")
        if self.fx_rate is not None and (
            self.fx_rate <= 0 or self.fx_base_currency == self.fx_quote_currency
        ):
            fail_validation("Transfer FX pair or rate is invalid.")
        fee_present = any(
            x is not None
            for x in (self.fee_record_key, self.fee_record_id, self.fee_amount, self.fee_currency)
        )
        if fee_present and (
            self.fee_amount is None
            or self.fee_currency is None
            or (self.fee_record_key is None and self.fee_record_id is None)
        ):
            fail_validation("Transfer fee witness must preserve its original identity and amount.")
        if self.fee_amount is not None and self.fee_amount > 0:
            fail_validation("A charged transfer fee cannot be positive cash income.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateActivityCandidate(AggregateRecord):
    source_record_id: UUID
    account_id: UUID
    provider: Literal["trading212", "synthetic"]
    external_record_id: str | None
    schema_version: str
    payload_digest: str
    source_updated_at: datetime | None
    first_observed_at: datetime
    occurred_at: datetime
    kind: Literal["external", "internal", "transfer", "fee", "unknown"]
    amount: Decimal | None
    currency: CurrencyCode | None
    selected: bool
    selection_reason: AggregateReason | None
    transfer: AggregateTransferAttestation | None

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (self.amount is None) != (self.currency is None):
            fail_validation("Activity amount requires its original currency.")
        if (self.selected and self.selection_reason is not None) or self.selection_reason not in (
            None,
            AggregateReason.AMBIGUOUS_REVISION,
        ):
            fail_validation("An unselected activity revision reason is invalid.")
        if self.transfer is not None and (
            self.provider != "synthetic"
            or self.schema_version != "synthetic-custody-v1:historical_transactions"
            or self.kind != "transfer"
            or self.transfer.counterparty_account_id == self.account_id
            or self.amount != self.transfer.principal
            or self.currency != self.transfer.currency
        ):
            fail_validation("Transfer attestation differs from its exact original native record.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateActivityCoverage(AggregateRecord):
    account_id: UUID
    ingestion_run_id: UUID
    coverage_id: UUID
    historical_evidence_id: UUID
    evidence_digest: str
    capability: Literal["historical_orders", "historical_transactions", "historical_dividends"]
    start_at: datetime
    end_at: datetime
    first_observed_at: datetime
    complete: bool

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if not self.start_at <= self.end_at <= self.first_observed_at:
            fail_validation("Activity coverage window or original knowledge time is invalid.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateRevisionWitness(AggregateRecord):
    evidence_id: UUID
    owner_id: UUID
    account_id: UUID
    principal_id: UUID
    new_source_record_id: UUID
    superseded_source_record_id: UUID
    authority: Literal["owner_attestation", "provider_evidence"]
    evidence_key: str
    economic_key: str
    first_observed_at: datetime
    content_digest: str

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (
            self.new_source_record_id == self.superseded_source_record_id
            or len(self.evidence_key) > 120
        ):
            fail_validation("Activity revision witness has invalid immutable identities.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateActivityInput(AggregateRecord):
    holdings_input_digest: str
    window: AggregateActivityWindow
    account_ids: tuple[UUID, ...]
    source_cutoff_at: datetime
    candidates: tuple[AggregateActivityCandidate, ...]
    coverage: tuple[AggregateActivityCoverage, ...]
    revisions: tuple[AggregateRevisionWitness, ...] = ()

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        aggregate_bound(1 <= len(self.account_ids) <= 8, "activity.accounts")
        aggregate_unique(self.account_ids, "activity.accounts")
        aggregate_bound(len(self.candidates) <= MAX_AGGREGATE_ACTIVITY, "activity.candidates")
        aggregate_unique(tuple(x.source_record_id for x in self.candidates), "activity.records")
        aggregate_unique(tuple(x.coverage_id for x in self.coverage), "activity.coverage")
        aggregate_unique(tuple(x.evidence_id for x in self.revisions), "activity.revisions")
        aggregate_bound(len(self.coverage) <= MAX_AGGREGATE_ACTIVITY, "activity.coverage")
        aggregate_bound(len(self.revisions) <= MAX_AGGREGATE_ACTIVITY, "activity.revisions")
        if self.window.end_at > self.source_cutoff_at:
            fail_validation("Activity window exceeds the aggregate cutoff.")
        for row in self.candidates:
            if (
                row.account_id not in self.account_ids
                or row.first_observed_at > self.source_cutoff_at
                or (
                    row.source_updated_at is not None
                    and row.source_updated_at > self.source_cutoff_at
                )
            ):
                fail_validation("Activity candidate differs from account or cutoff.")
        for coverage in self.coverage:
            if (
                coverage.account_id not in self.account_ids
                or coverage.first_observed_at > self.source_cutoff_at
            ):
                fail_validation("Activity coverage differs from account or cutoff.")

        candidates = {x.source_record_id: x for x in self.candidates}
        for witness in self.revisions:
            new = candidates.get(witness.new_source_record_id)
            old = candidates.get(witness.superseded_source_record_id)
            if (
                new is None
                or old is None
                or new.account_id != witness.account_id
                or old.account_id != witness.account_id
                or witness.first_observed_at > self.source_cutoff_at
            ):
                fail_validation(
                    "Activity revision witness is not bound to complete retained candidates."
                )
