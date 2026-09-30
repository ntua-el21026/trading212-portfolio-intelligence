"""Six frozen aggregate REST operations; exact whole-row financial variants."""

from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from .historical import HistoricalPageLimit, HistoricalSchema
from .sources import SourceQuality
from .targets import AwareInstant, CurrencyString, Cursor, DecimalString, Digest, UUIDString

AggregateReason = Literal[
    "value_unavailable",
    "fx_missing",
    "not_requested",
    "coverage_incomplete",
    "unmatched_transfer",
    "ambiguous_transfer",
    "transfer_proof_incomplete",
    "ambiguous_revision",
    "unknown_activity",
    "zero_total",
]
AggregateView = Literal["holdings", "components", "accounts", "transfers"]
AggregateCount = Annotated[StrictInt, Field(ge=0, le=2147483647)]
AggregateRevision = Annotated[StrictInt, Field(ge=1, le=2147483647)]
AggregateName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=120, pattern=r"^[^\x00]*$")
]
AggregateText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=256, pattern=r"^[^\x00]*$")
]
AggregateOrigin = Literal[
    "observed_provider", "normalized_provider", "derived_deterministic", "estimated", "unavailable"
]


class AggregateSchema(HistoricalSchema):
    pass


class AggregateMember(AggregateSchema):
    account_id: UUIDString
    portfolio_snapshot_id: UUIDString


class AggregateSelectionContent(AggregateSchema):
    name: AggregateName
    members: Annotated[list[AggregateMember], Field(min_length=1, max_length=8)]
    reporting_currency: CurrencyString
    source_cutoff_at: AwareInstant
    economic_identity_policy: Literal["canonical_instrument_v1"] = "canonical_instrument_v1"

    @model_validator(mode="after")
    def distinct_members(self) -> Self:
        if (
            not self.name.strip()
            or len({x.account_id for x in self.members}) != len(self.members)
            or len({x.portfolio_snapshot_id for x in self.members}) != len(self.members)
        ):
            raise ValueError(
                "Aggregate members must identify distinct accounts and saved snapshots."
            )
        return self


class CreateAggregateSelectionRequest(AggregateSchema):
    content: AggregateSelectionContent


class AggregateFxBinding(AggregateSchema):
    account_id: UUIDString
    currency: CurrencyString
    fx_observation_id: UUIDString


class AggregateActivityWindow(AggregateSchema):
    start_at: AwareInstant
    end_at: AwareInstant

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if not self.start_at < self.end_at <= self.start_at + timedelta(days=3660):
            raise ValueError("Aggregate activity window is invalid.")
        return self


class CreateAggregateRunRequest(AggregateSchema):
    fx_bindings: Annotated[list[AggregateFxBinding], Field(max_length=256)] = Field(
        default_factory=list
    )
    activity_window: AggregateActivityWindow | None = None

    @model_validator(mode="after")
    def distinct_fx(self) -> Self:
        if len({(x.account_id, x.currency) for x in self.fx_bindings}) != len(self.fx_bindings):
            raise ValueError(
                "Only one explicit FX observation is allowed for each account currency."
            )
        return self


class AggregatePageQuery(AggregateSchema):
    limit: HistoricalPageLimit = 25
    cursor: Cursor | None = None


class AggregateRunQuery(AggregatePageQuery):
    view: AggregateView = "holdings"


class AggregateMoney(AggregateSchema):
    currency: CurrencyString
    value: DecimalString | None
    known_value: DecimalString
    known_count: AggregateCount
    total_count: AggregateCount
    quality: SourceQuality
    reason: AggregateReason | None
    origin: Literal["derived_deterministic"] = "derived_deterministic"

    @model_validator(mode="after")
    def complete_money(self) -> Self:
        complete = self.known_count == self.total_count
        if (
            self.known_count > self.total_count
            or complete != (self.value is not None)
            or complete != (self.reason is None)
            or (self.value is not None and Decimal(self.value) != Decimal(self.known_value))
        ):
            raise ValueError("Aggregate money availability differs from complete component counts.")
        if not complete and self.quality not in ("partial", "unreconciled", "failed"):
            raise ValueError("Unavailable aggregate money cannot claim complete quality.")
        return self


class AggregateSnapshotPin(AggregateSchema):
    account_id: UUIDString
    portfolio_snapshot_id: UUIDString
    calculation_run_id: UUIDString
    calculation_version: AggregateText
    valuation_at: AwareInstant
    source_cutoff_at: AwareInstant
    reporting_currency: CurrencyString
    quality: SourceQuality
    content_digest: Digest

    @model_validator(mode="after")
    def ordered_knowledge(self) -> Self:
        if self.source_cutoff_at > self.valuation_at:
            raise ValueError("Saved snapshot cutoff exceeds valuation.")
        return self


class AggregateNativeComponent(AggregateSchema):
    component_id: UUIDString
    account_id: UUIDString
    portfolio_snapshot_id: UUIDString
    kind: Literal["position", "cash"]
    listing_id: UUIDString | None
    instrument_id: UUIDString | None
    quantity: DecimalString | None
    native_currency: CurrencyString
    native_value: DecimalString | None
    quality: SourceQuality
    origin: AggregateOrigin
    source_record_ids: Annotated[list[UUIDString], Field(max_length=10000)]

    @model_validator(mode="after")
    def native_identity(self) -> Self:
        values = (self.listing_id, self.instrument_id, self.quantity)
        if (
            (self.kind == "position" and any(x is None for x in values))
            or (self.kind == "cash" and any(x is not None for x in values))
            or len(set(self.source_record_ids)) != len(self.source_record_ids)
        ):
            raise ValueError("Aggregate component identity is invalid.")
        if self.native_value is None and self.origin != "unavailable":
            raise ValueError("Missing native money requires unavailable origin.")
        return self


class AggregateComponent(AggregateSchema):
    native: AggregateNativeComponent
    reporting_currency: CurrencyString
    converted_value: DecimalString | None
    fx_observation_id: UUIDString | None
    inverted: StrictBool
    quality: SourceQuality
    reason: AggregateReason | None

    @model_validator(mode="after")
    def exact_conversion_identity(self) -> Self:
        if (self.converted_value is None) != (self.reason is not None):
            raise ValueError("Aggregate conversion availability requires its reason.")
        if self.native.native_value is None and self.converted_value is not None:
            raise ValueError("Missing native amount cannot become a known conversion.")
        if self.native.native_currency == self.reporting_currency:
            if (
                self.fx_observation_id is not None
                or self.inverted
                or self.converted_value != self.native.native_value
            ):
                raise ValueError("Same-currency aggregate amount must remain exact.")
        elif self.converted_value is not None and self.fx_observation_id is None:
            raise ValueError("Aggregate conversion requires its original observation ID.")
        return self


class AggregateAccountTotal(AggregateSchema):
    account_id: UUIDString
    money: AggregateMoney


class AggregateHolding(AggregateSchema):
    instrument_id: UUIDString
    quantity: DecimalString
    money: AggregateMoney
    account_totals: Annotated[list[AggregateAccountTotal], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def distinct_accounts(self) -> Self:
        if len({x.account_id for x in self.account_totals}) != len(self.account_totals) or any(
            x.money.currency != self.money.currency for x in self.account_totals
        ):
            raise ValueError("Aggregate holding account partition differs.")
        return self


class AggregateFlowLeg(AggregateSchema):
    source_record_id: UUIDString
    account_id: UUIDString
    occurred_at: AwareInstant
    amount: DecimalString | None
    currency: CurrencyString | None
    classification: Literal[
        "external",
        "internal",
        "fee",
        "matched_transfer",
        "unmatched_transfer",
        "ambiguous_transfer",
        "unknown",
    ]
    counterpart_record_id: UUIDString | None
    reason: AggregateReason | None

    @model_validator(mode="after")
    def flow_availability(self) -> Self:
        if (
            (self.amount is None) != (self.currency is None)
            or (self.classification == "matched_transfer")
            != (self.counterpart_record_id is not None)
            or (self.classification in ("unmatched_transfer", "ambiguous_transfer", "unknown"))
            != (self.reason is not None)
        ):
            raise ValueError("Aggregate flow proof/availability differs.")
        return self


class AggregateTransferMatch(AggregateSchema):
    outgoing_record_id: UUIDString
    incoming_record_id: UUIDString
    outgoing_account_id: UUIDString
    incoming_account_id: UUIDString
    transfer_reference: AggregateText
    outgoing_principal: DecimalString
    outgoing_currency: CurrencyString
    incoming_principal: DecimalString
    incoming_currency: CurrencyString
    fx_rate: DecimalString | None
    fx_base_currency: CurrencyString | None
    fx_quote_currency: CurrencyString | None
    fee_record_ids: Annotated[list[UUIDString], Field(max_length=2)]

    @model_validator(mode="after")
    def original_transfer_proof(self) -> Self:
        cross = self.outgoing_currency != self.incoming_currency
        values = (self.fx_rate, self.fx_base_currency, self.fx_quote_currency)
        if (
            Decimal(self.outgoing_principal) >= 0
            or Decimal(self.incoming_principal) <= 0
            or self.outgoing_account_id == self.incoming_account_id
            or self.outgoing_record_id == self.incoming_record_id
            or len(set(self.fee_record_ids)) != len(self.fee_record_ids)
        ):
            raise ValueError("Aggregate transfer principal or identity differs.")
        if cross and (any(x is None for x in values) or len(self.fee_record_ids) != 2):
            raise ValueError("Cross-currency transfer requires actual FX and both fee witnesses.")
        if not cross and any(x is not None for x in values):
            raise ValueError("Same-currency transfer cannot invent FX.")
        return self


class AggregateFlowCurrencyTotal(AggregateSchema):
    currency: CurrencyString
    external_net: DecimalString
    fees: DecimalString


class AggregateHoldingsContext(AggregateSchema):
    input_digest: Digest
    result_digest: Digest
    reporting_currency: CurrencyString
    source_cutoff_at: AwareInstant
    snapshots: Annotated[list[AggregateSnapshotPin], Field(min_length=1, max_length=8)]
    securities: AggregateMoney
    cash: AggregateMoney
    total: AggregateMoney
    rounding_residual: DecimalString | None
    method: Literal["account_aggregation_v1"] = "account_aggregation_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"


class AggregateHoldingPage(AggregateSchema):
    view: Literal["holdings"]
    context: AggregateHoldingsContext
    items: Annotated[list[AggregateHolding], Field(max_length=100)]
    total: AggregateCount
    next_cursor: Cursor | None


class AggregateComponentPage(AggregateSchema):
    view: Literal["components"]
    context: AggregateHoldingsContext
    items: Annotated[list[AggregateComponent], Field(max_length=100)]
    total: AggregateCount
    next_cursor: Cursor | None


class AggregateAccountPage(AggregateSchema):
    view: Literal["accounts"]
    context: AggregateHoldingsContext
    items: Annotated[list[AggregateAccountTotal], Field(max_length=8)]
    total: Annotated[StrictInt, Field(ge=0, le=8)]
    next_cursor: Cursor | None


class AggregateTransferRow(AggregateSchema):
    leg: AggregateFlowLeg
    match: AggregateTransferMatch | None


class AggregateTransferPage(AggregateSchema):
    view: Literal["transfers"]
    holdings_input_digest: Digest
    input_digest: Digest | None
    result_digest: Digest | None
    window: AggregateActivityWindow | None
    items: Annotated[list[AggregateTransferRow], Field(max_length=100)]
    currency_totals: Annotated[list[AggregateFlowCurrencyTotal], Field(max_length=32)]
    complete: StrictBool
    reasons: Annotated[list[AggregateReason], Field(max_length=11)]
    candidate_count: Annotated[StrictInt, Field(ge=0, le=10000)]
    selected_count: Annotated[StrictInt, Field(ge=0, le=10000)]
    total: Annotated[StrictInt, Field(ge=0, le=10000)]
    next_cursor: Cursor | None


class AggregateSelectionResponse(AggregateSchema):
    selection_id: UUIDString
    content: AggregateSelectionContent
    content_digest: Digest
    revision: AggregateRevision
    created_at: AwareInstant


class AggregateRunReceipt(AggregateSchema):
    run_id: UUIDString
    selection_id: UUIDString
    selection_revision: Annotated[StrictInt, Field(ge=2, le=2147483647)]
    holdings_input_digest: Digest
    holdings_result_digest: Digest
    activity_input_digest: Digest | None
    activity_result_digest: Digest | None
    activity_requested: StrictBool
    state: Literal["succeeded", "expired"]
    created_at: AwareInstant
    expires_at: AwareInstant

    @model_validator(mode="after")
    def atomic_receipt(self) -> Self:
        if (
            (self.activity_input_digest is not None) != self.activity_requested
            or (self.activity_result_digest is not None) != self.activity_requested
            or not self.created_at < self.expires_at <= self.created_at + timedelta(days=30)
        ):
            raise ValueError("Aggregate receipt is incomplete or has an invalid retained lifetime.")
        return self


AggregateFinancialPage = Annotated[
    AggregateHoldingPage | AggregateComponentPage | AggregateAccountPage | AggregateTransferPage,
    Field(discriminator="view"),
]


class AggregateRunResponse(AggregateSchema):
    run: AggregateRunReceipt
    page: AggregateFinancialPage | None
    view_digest: Digest

    @model_validator(mode="after")
    def authorized_result(self) -> Self:
        if (self.run.state == "expired") != (self.page is None):
            raise ValueError("Expired aggregate receipt cannot expose retained financial rows.")
        if self.page is not None and len(self.page.items) > self.page.total:
            raise ValueError("Aggregate whole-row page exceeds total.")
        return self


class AggregatePageResponse[Item](AggregateSchema):
    items: Annotated[list[Item], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: AggregateCount

    @model_validator(mode="after")
    def bounded_page(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("Aggregate collection page bounds differ.")
        return self
