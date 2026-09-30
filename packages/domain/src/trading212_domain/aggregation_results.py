"""Published Q18 aggregation projections with independent holdings/activity availability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal
from uuid import UUID

from .aggregation import (
    AggregateActivityWindow,
    AggregateMoney,
    AggregateReason,
    AggregateRecord,
    aggregate_bound,
    aggregate_unique,
)
from .aggregation_inputs import (
    AggregateNativeComponent,
    AggregateSnapshotPin,
)
from .enums import QualityState
from .errors import fail_validation
from .values import CurrencyCode


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(Context(prec=96, rounding=ROUND_HALF_EVEN)):
        return sum(values, Decimal(0))


_QUALITY = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.PARTIAL: 3,
    QualityState.UNRECONCILED: 4,
    QualityState.FAILED: 5,
}


def _check_money(money: AggregateMoney, rows: tuple[AggregateComponent, ...]) -> None:
    known = tuple(x.converted_value for x in rows if x.converted_value is not None)
    if (
        money.known_value != _sum(known)
        or money.known_count != len(known)
        or money.total_count != len(rows)
    ):
        fail_validation("Aggregation normalized monetary totals differ from complete components.")
    if any(
        x.reporting_currency != money.currency or _QUALITY[x.quality] > _QUALITY[money.quality]
        for x in rows
    ):
        fail_validation("Aggregation money currency or quality improves its original components.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateComponent(AggregateRecord):
    native: AggregateNativeComponent
    reporting_currency: CurrencyCode
    converted_value: Decimal | None
    fx_observation_id: UUID | None
    inverted: bool
    quality: QualityState
    reason: AggregateReason | None

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (self.converted_value is None) != (self.reason is not None):
            fail_validation("Component availability requires an exact reason.")
        if self.native.native_value is None and self.converted_value is not None:
            fail_validation("A missing native amount cannot become a known conversion.")
        if self.native.native_currency == self.reporting_currency and (
            self.fx_observation_id is not None
            or self.inverted
            or self.converted_value != self.native.native_value
        ):
            fail_validation("Same-currency identity must preserve the original native amount.")
        if (
            self.converted_value is not None
            and self.native.native_currency != self.reporting_currency
            and self.fx_observation_id is None
        ):
            fail_validation("A cross-currency amount needs its actual FX observation.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateAccountTotal(AggregateRecord):
    account_id: UUID
    money: AggregateMoney


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateHolding(AggregateRecord):
    instrument_id: UUID
    quantity: Decimal
    money: AggregateMoney
    account_totals: tuple[AggregateAccountTotal, ...]

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        aggregate_bound(1 <= len(self.account_totals) <= 8, "holding.accounts")
        aggregate_unique(tuple(x.account_id for x in self.account_totals), "holding.accounts")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateHoldingsResult(AggregateRecord):
    input_digest: str
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    snapshots: tuple[AggregateSnapshotPin, ...]
    components: tuple[AggregateComponent, ...]
    holdings: tuple[AggregateHolding, ...]
    accounts: tuple[AggregateAccountTotal, ...]
    securities: AggregateMoney
    cash: AggregateMoney
    total: AggregateMoney
    rounding_residual: Decimal | None
    method: Literal["account_aggregation_v1"] = "account_aggregation_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        aggregate_bound(1 <= len(self.snapshots) <= 8, "snapshots")
        aggregate_bound(len(self.components) <= 10256, "components")
        aggregate_bound(len(self.holdings) <= 10000, "holdings")
        aggregate_unique(tuple(x.native.component_id for x in self.components), "components")
        aggregate_unique(tuple(x.account_id for x in self.snapshots), "snapshot.accounts")
        pins = {x.account_id: x for x in self.snapshots}
        for row in self.components:
            pin = pins.get(row.native.account_id)
            if (
                pin is None
                or row.native.portfolio_snapshot_id != pin.portfolio_snapshot_id
                or row.reporting_currency != self.reporting_currency
                or _QUALITY[row.quality] < max(_QUALITY[row.native.quality], _QUALITY[pin.quality])
            ):
                fail_validation("Component projection differs from its saved snapshot or quality.")
        aggregate_unique(tuple(x.instrument_id for x in self.holdings), "holdings")
        if tuple(x.account_id for x in self.accounts) != tuple(
            x.account_id for x in self.snapshots
        ):
            fail_validation("Account total inventory differs from saved snapshots.")
        if (self.rounding_residual is None) != (self.total.value is None):
            fail_validation("A complete conversion residual needs complete monetary coverage.")
        for money in (
            self.securities,
            self.cash,
            self.total,
            *(x.money for x in self.accounts),
            *(x.money for x in self.holdings),
        ):
            if money.currency != self.reporting_currency:
                fail_validation("Aggregate money currencies differ.")
        _check_money(self.total, self.components)
        _check_money(
            self.securities, tuple(x for x in self.components if x.native.kind == "position")
        )
        _check_money(self.cash, tuple(x for x in self.components if x.native.kind == "cash"))
        if {x.native.account_id for x in self.components} - {x.account_id for x in self.snapshots}:
            fail_validation("A component names an unselected account.")
        for account in self.accounts:
            _check_money(
                account.money,
                tuple(x for x in self.components if x.native.account_id == account.account_id),
            )
        grouped: dict[UUID, list[AggregateComponent]] = {}
        for row in self.components:
            if row.native.instrument_id is not None:
                grouped.setdefault(row.native.instrument_id, []).append(row)
        if tuple(x.instrument_id for x in self.holdings) != tuple(sorted(grouped)):
            fail_validation("Canonical holding identity/order differs from original components.")
        for holding in self.holdings:
            rows = tuple(grouped[holding.instrument_id])
            _check_money(holding.money, rows)
            if holding.quantity != _sum(
                tuple(x.native.quantity for x in rows if x.native.quantity is not None)
            ):
                fail_validation("Canonical holding quantity differs from original components.")
            wanted = tuple(
                x.account_id
                for x in self.snapshots
                if any(row.native.account_id == x.account_id for row in rows)
            )
            if tuple(x.account_id for x in holding.account_totals) != wanted:
                fail_validation("Holding account partition differs from selected members.")
            for account in holding.account_totals:
                _check_money(
                    account.money,
                    tuple(x for x in rows if x.native.account_id == account.account_id),
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateFlowLeg(AggregateRecord):
    source_record_id: UUID
    account_id: UUID
    occurred_at: datetime
    amount: Decimal | None
    currency: CurrencyCode | None
    classification: Literal[
        "external",
        "internal",
        "fee",
        "matched_transfer",
        "unmatched_transfer",
        "ambiguous_transfer",
        "unknown",
    ]
    counterpart_record_id: UUID | None
    reason: AggregateReason | None

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (self.amount is None) != (self.currency is None):
            fail_validation("A flow amount requires its currency.")
        if (self.classification == "matched_transfer") != (self.counterpart_record_id is not None):
            fail_validation("Matched transfer must bind its exact opposite retained leg.")
        degraded = self.classification in ("unmatched_transfer", "ambiguous_transfer", "unknown")
        if degraded != (self.reason is not None):
            fail_validation("Degraded flow coverage requires an explicit reason.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateTransferMatch(AggregateRecord):
    outgoing_record_id: UUID
    incoming_record_id: UUID
    outgoing_account_id: UUID
    incoming_account_id: UUID
    transfer_reference: str
    outgoing_principal: Decimal
    outgoing_currency: CurrencyCode
    incoming_principal: Decimal
    incoming_currency: CurrencyCode
    fx_rate: Decimal | None
    fx_base_currency: CurrencyCode | None
    fx_quote_currency: CurrencyCode | None
    fee_record_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        if (
            self.outgoing_principal >= 0
            or self.incoming_principal <= 0
            or self.outgoing_account_id == self.incoming_account_id
            or self.outgoing_record_id == self.incoming_record_id
        ):
            fail_validation("Transfer matching needs opposite distinct-account principals.")
        aggregate_unique(self.fee_record_ids, "transfer.fees")
        aggregate_bound(len(self.fee_record_ids) <= 2, "transfer.fees")
        cross = self.outgoing_currency != self.incoming_currency
        if cross != all(
            x is not None for x in (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
        ):
            fail_validation("Cross-currency transfer proof requires exact original FX.")
        if cross and len(self.fee_record_ids) != 2:
            fail_validation("Cross-currency transfer proof requires both original fee witnesses.")
        if not cross and (
            any(
                x is not None for x in (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
            )
            or _sum((self.outgoing_principal, self.incoming_principal)) != 0
        ):
            fail_validation("Same-currency transfer principals must cancel exactly without FX.")
        if cross and (
            self.fx_rate is None
            or self.fx_rate <= 0
            or {self.fx_base_currency, self.fx_quote_currency}
            != {self.outgoing_currency, self.incoming_currency}
        ):
            fail_validation("Cross-currency transfer proof has a different original pair.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateFlowCurrencyTotal(AggregateRecord):
    currency: CurrencyCode
    external_net: Decimal
    fees: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateActivityResult(AggregateRecord):
    input_digest: str
    holdings_input_digest: str
    window: AggregateActivityWindow
    legs: tuple[AggregateFlowLeg, ...]
    matches: tuple[AggregateTransferMatch, ...]
    currency_totals: tuple[AggregateFlowCurrencyTotal, ...]
    complete: bool
    reasons: tuple[AggregateReason, ...]
    candidate_count: int
    selected_count: int
    method: Literal["account_aggregation_v1"] = "account_aggregation_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"

    def __post_init__(self) -> None:
        AggregateRecord.__post_init__(self)
        aggregate_bound(self.candidate_count <= 10000, "activity.candidates")
        if (
            self.selected_count != len(self.legs)
            or self.selected_count > self.candidate_count
            or self.complete != (not self.reasons)
        ):
            fail_validation("Activity coverage/counts differ from original candidate selection.")
        aggregate_unique(tuple(x.source_record_id for x in self.legs), "activity.legs")
        aggregate_unique(tuple(x.currency for x in self.currency_totals), "activity.currencies")
        aggregate_unique(self.reasons, "activity.reasons")
        legs = {x.source_record_id: x for x in self.legs}
        paired: set[UUID] = set()
        for match in self.matches:
            outgoing, incoming = (
                legs.get(match.outgoing_record_id),
                legs.get(match.incoming_record_id),
            )
            if (
                outgoing is None
                or incoming is None
                or {match.outgoing_record_id, match.incoming_record_id} & paired
            ):
                fail_validation("Transfer pair is absent or repeated in the exact flow partition.")
            for leg, other, account, principal, currency in (
                (
                    outgoing,
                    incoming,
                    match.outgoing_account_id,
                    match.outgoing_principal,
                    match.outgoing_currency,
                ),
                (
                    incoming,
                    outgoing,
                    match.incoming_account_id,
                    match.incoming_principal,
                    match.incoming_currency,
                ),
            ):
                if (
                    leg.classification != "matched_transfer"
                    or leg.counterpart_record_id != other.source_record_id
                    or (leg.account_id, leg.amount, leg.currency) != (account, principal, currency)
                ):
                    fail_validation("Matched flow does not preserve its original pair principal.")
            for fee_id in match.fee_record_ids:
                fee = legs.get(fee_id)
                if (
                    fee is None
                    or fee.classification != "fee"
                    or fee.account_id not in (outgoing.account_id, incoming.account_id)
                ):
                    fail_validation(
                        "Transfer fee is absent from its account's retained flow partition."
                    )
            paired.update((match.outgoing_record_id, match.incoming_record_id))
        if paired != {
            x.source_record_id for x in self.legs if x.classification == "matched_transfer"
        }:
            fail_validation("Matched flow inventory differs from retained transfer proof.")
        currencies = sorted(
            {
                x.currency
                for x in self.legs
                if x.classification in ("external", "fee") and x.currency is not None
            },
            key=str,
        )
        if tuple(x.currency for x in self.currency_totals) != tuple(currencies):
            fail_validation("External flow currency inventory differs from its original legs.")
        for row in self.currency_totals:
            for classification, actual in (("external", row.external_net), ("fee", row.fees)):
                wanted = _sum(
                    tuple(
                        x.amount
                        for x in self.legs
                        if x.classification == classification
                        and x.currency == row.currency
                        and x.amount is not None
                    )
                )
                if actual != wanted:
                    fail_validation("External flow totals differ from exact original amounts.")
        if any(x.reason is not None and x.reason not in self.reasons for x in self.legs):
            fail_validation("Activity summary omits a retained leg's unavailable reason.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateHoldingsSummary(AggregateRecord):
    input_digest: str
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    snapshots: tuple[AggregateSnapshotPin, ...]
    securities: AggregateMoney
    cash: AggregateMoney
    total: AggregateMoney
    rounding_residual: Decimal | None
    component_count: int
    holding_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregateActivitySummary(AggregateRecord):
    input_digest: str
    holdings_input_digest: str
    window: AggregateActivityWindow
    currency_totals: tuple[AggregateFlowCurrencyTotal, ...]
    complete: bool
    reasons: tuple[AggregateReason, ...]
    candidate_count: int
    selected_count: int
    match_count: int
