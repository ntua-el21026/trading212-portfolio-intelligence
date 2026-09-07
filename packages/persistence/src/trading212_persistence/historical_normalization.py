"""Normalize bounded immutable broker facts without consulting mutable activity projections."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal, cast

from trading212_domain import historical as d
from trading212_domain.enums import QualityState
from trading212_domain.values import CurrencyCode, Money, exact_decimal, require_utc

from .models import SourceRecordModel, SourceRecordOccurrenceModel
from .source_models import MarketDataInstrumentModel


def obj(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def number(value: object) -> Decimal | None:
    # Canonical ingestion tags exact numbers to preserve native precision in JSONB.
    if isinstance(value, dict) and set(value) == {"$decimal"}:
        value = value["$decimal"]
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        return None
    try:
        return exact_decimal(value, field="retained_value")
    except ValueError:
        return None


def instant(value: object, fallback: datetime) -> datetime:
    if isinstance(value, dict) and set(value) in ({"$datetime"}, {"$date"}):
        value = next(iter(value.values()))
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None and len(value) == 10:
                parsed = parsed.replace(tzinfo=UTC)
            return require_utc(parsed)
        except ValueError:
            pass
    return fallback


def key(*parts: object) -> str:
    return hashlib.sha256(":".join(str(x) for x in parts).encode()).hexdigest()


def metric(
    value: Money | None, coverage: d.HistoricalCoverageKey, reason: d.HistoricalReason
) -> d.HistoricalMoneyMetric:
    return d.HistoricalMoneyMetric(
        value=value,
        availability=d.MetricAvailability.UNAVAILABLE
        if value is None
        else d.MetricAvailability.AVAILABLE,
        reason_code=reason if value is None else None,
        quality=QualityState.PARTIAL if value is None else QualityState.FRESH,
        coverage_key=coverage,
        origin=d.HistoricalOrigin.PROVIDER,
    )


def normalize_record(
    record: SourceRecordModel,
    occurrence: SourceRecordOccurrenceModel | None,
    mappings: tuple[MarketDataInstrumentModel, ...],
) -> d.HistoricalEvent | None:
    body = obj(record.sanitized_payload)
    identity = d.HistoricalEventIdentity(
        economic_key=key(record.capability, record.provider_record_id or record.id),
        revision_id=str(record.id),
        source_record_id=str(record.id),
        source_occurrence_id=None if occurrence is None else str(occurrence.id),
        economic_at=record.source_updated_at or record.observed_at,
        first_observed_at=record.observed_at,
    )

    # Retain mapping candidates for historical selection independently of current listings.
    def mapping_for(ticker: object) -> MarketDataInstrumentModel | None:
        matches = [
            x
            for x in mappings
            if x.provider_key == ticker and x.state == "resolved" and x.listing_id is not None
        ]
        if not matches or len({(x.instrument_id, x.listing_id) for x in matches}) != 1:
            return None
        eligible = [x for x in matches if x.created_at <= record.observed_at]
        return max(eligible or matches, key=lambda x: (x.created_at, x.valid_from, str(x.id)))

    def unknown(
        category: Literal[
            "unclassified", "unmatched_transfer", "unmatched_execution", "unmatched_dividend"
        ],
        amount: Money | None = None,
    ) -> d.HistoricalUnknownActivity:
        return d.HistoricalUnknownActivity(
            identity=identity,
            category=category,
            known_amount=amount,
            affected_coverage=(
                d.HistoricalCoverageKey.EVENTS,
                d.HistoricalCoverageKey.CASH,
                d.HistoricalCoverageKey.QUANTITY,
            ),
        )

    if record.capability == "historical_orders":
        fill, order = obj(body.get("fill")), obj(body.get("order"))
        if not fill:
            return None
        wallet = obj(fill.get("walletImpact"))
        identity = replace(
            identity,
            economic_key=key("fill", order.get("id"), fill.get("id")),
            economic_at=instant(fill.get("timestamp"), identity.economic_at),
        )
        quantity, price, net = (
            number(fill.get("quantity")),
            number(fill.get("price")),
            number(wallet.get("netValue")),
        )
        mapping = mapping_for(order.get("ticker"))
        side = str(order.get("side", "")).lower()
        if (
            mapping is None
            or quantity is None
            or price is None
            or net is None
            or side not in {"buy", "sell"}
        ):
            return unknown("unmatched_execution")
        currency = obj(order.get("instrument")).get("currency") or order.get("currency")
        if not isinstance(currency, str) or not isinstance(wallet.get("currency"), str):
            return unknown("unmatched_execution")
        native = CurrencyCode(currency)
        cash_currency = CurrencyCode(cast(str, wallet["currency"]))
        taxes = number(wallet.get("taxes"))
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            gross = abs(quantity) * price
            fee_amount = None
            if native == cash_currency and taxes is not None and taxes >= 0:
                candidate_fee = (abs(net) - gross if side == "buy" else gross - abs(net)) - taxes
                if candidate_fee >= 0:
                    fee_amount = Money(candidate_fee, native)
        assert mapping.instrument_id is not None and mapping.listing_id is not None
        return d.HistoricalExecution(
            identity=identity,
            order_key=str(order.get("id")),
            fill_key=str(fill.get("id")),
            instrument_id=str(mapping.instrument_id),
            listing_id=str(mapping.listing_id),
            mapping_id=str(mapping.id),
            side=cast(Literal["buy", "sell"], side),
            quantity=abs(quantity),
            native_price=Money(price, native),
            gross_value=Money(gross, native),
            cash_impact=Money(-abs(net) if side == "buy" else abs(net), cash_currency),
            fees=replace(
                metric(fee_amount, d.HistoricalCoverageKey.CASH, d.HistoricalReason.FEE_UNKNOWN),
                origin=d.HistoricalOrigin.DERIVED,
            ),
            taxes=metric(
                None if taxes is None else Money(taxes, cash_currency),
                d.HistoricalCoverageKey.CASH,
                d.HistoricalReason.WITHHOLDING_UNKNOWN,
            ),
        )
    if record.capability == "historical_transactions":
        identity = replace(
            identity, economic_at=instant(body.get("dateTime"), identity.economic_at)
        )
        amount = number(body.get("amount"))
        currency = body.get("currency")
        if amount is None or not isinstance(currency, str):
            return unknown("unclassified")
        money = Money(amount, CurrencyCode(currency))
        kind = str(body.get("type", "")).upper()
        external = {"DEPOSIT": "deposit", "WITHDRAW": "withdrawal", "WITHDRAWAL": "withdrawal"}
        if kind in external:
            classification = cast(Literal["deposit", "withdrawal"], external[kind])
            return d.HistoricalExternalFlow(
                identity=identity,
                kind=classification,
                signed_amount=Money(
                    abs(amount) if classification == "deposit" else -abs(amount), money.currency
                ),
                scope_proof="account_boundary",
            )
        effects = {
            "FEE": "fee",
            "TAX": "tax",
            "INTEREST": "interest",
            "INTERNAL_TRANSFER": "internal_transfer",
            "FX_CONVERSION": "fx_conversion",
        }
        if kind in effects:
            effect = cast(
                Literal["fee", "tax", "interest", "internal_transfer", "fx_conversion"],
                effects[kind],
            )
            signed = -abs(amount) if effect in {"fee", "tax"} else amount
            return d.HistoricalCashEffect(
                identity=identity, effect_kind=effect, signed_amount=Money(signed, money.currency)
            )
        return unknown("unmatched_transfer" if "TRANSFER" in kind else "unclassified", money)
    if record.capability == "historical_dividends":
        identity = replace(identity, economic_at=instant(body.get("paidOn"), identity.economic_at))
        amount, quantity, per_share = (
            number(body.get("amount")),
            number(body.get("quantity")),
            number(body.get("grossAmountPerShare")),
        )
        currency = body.get("currency")
        if amount is None or not isinstance(currency, str):
            return unknown("unmatched_dividend")
        dividend_net = Money(amount, CurrencyCode(currency))
        dividend_currency = body.get("tickerCurrency") or obj(body.get("instrument")).get(
            "currency"
        )
        mapping = mapping_for(body.get("ticker"))
        dividend_gross = None
        withholding = None
        if quantity is not None and per_share is not None and isinstance(dividend_currency, str):
            with localcontext() as context:
                context.prec = 80
                context.rounding = ROUND_HALF_EVEN
                dividend_gross = Money(quantity * per_share, CurrencyCode(dividend_currency))
                if dividend_gross.currency == dividend_net.currency:
                    withholding = Money(
                        dividend_gross.amount - dividend_net.amount, dividend_net.currency
                    )
        return d.HistoricalDividend(
            identity=identity,
            dividend_key=key(body.get("reference")),
            instrument_id=None if mapping is None else str(mapping.instrument_id),
            listing_id=None if mapping is None else str(mapping.listing_id),
            net=dividend_net,
            gross=metric(
                dividend_gross,
                d.HistoricalCoverageKey.PRIOR_INCOME,
                d.HistoricalReason.GROSS_UNKNOWN,
            ),
            withholding=metric(
                withholding,
                d.HistoricalCoverageKey.PRIOR_INCOME,
                d.HistoricalReason.WITHHOLDING_UNKNOWN,
            ),
            payment_convention="payment_date_utc_start",
        )
    return None
