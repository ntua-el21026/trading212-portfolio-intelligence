"""Constant-quantity price/FX decomposition, alternative partitions and residuals."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from trading212_domain import CurrencyCode, Money
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.sources import PriceBasis

from ._decimal import persisted_decimal
from ._historical_benchmark import benchmark_wealth
from ._historical_core import (
    ONE,
    ZERO,
    HistoricalEngine,
    amount,
    dividend_parts,
    known,
    money_metric,
    ratio_metric,
)
from ._historical_income import group_for
from ._historical_performance import converted_event, event_total, period_events, period_returns

EffectKind = Literal["price", "income", "fees", "taxes", "fx", "interaction", "cash_fx"]
EFFECTS: tuple[EffectKind, ...] = (
    "price",
    "income",
    "fees",
    "taxes",
    "fx",
    "interaction",
    "cash_fx",
)


def partition(
    engine: HistoricalEngine,
    listing: str | None,
    currency: CurrencyCode,
    at: datetime,
    grouping: d.HistoricalGrouping,
) -> tuple[str, str, bool]:
    if listing is None:
        return f"cash:{currency}", f"Cash {currency}", False
    if listing not in engine.instruments:
        return "unresolved", "Unresolved", True
    instrument = engine.instruments[listing]
    if grouping is d.HistoricalGrouping.HOLDING:
        return listing, listing, False
    if grouping is d.HistoricalGrouping.CURRENCY:
        return str(currency), str(currency), False
    if grouping is d.HistoricalGrouping.GROUP:
        return group_for(engine, listing, at)
    evidence = [
        item
        for item in engine.value.classification_evidence
        if item.instrument_id == instrument.instrument_id
        and item.dimension == grouping.value
        and item.valid_from <= at
        and (item.valid_to is None or at < item.valid_to)
        and item.first_observed_at <= engine.cutoff(at)
    ]
    if not evidence:
        engine.warnings.add(d.HistoricalReason.CLASSIFICATION_MISSING)
        return "unresolved", "Unresolved", True
    latest = max(item.valid_from for item in evidence)
    candidates = [item for item in evidence if item.valid_from == latest]
    if len({(item.taxonomy, item.taxonomy_version, item.category) for item in candidates}) != 1:
        return "unresolved", "Unresolved", True
    chosen = min(candidates, key=lambda item: item.id)
    engine.evidence(
        chosen.id,
        "classification",
        at,
        r.HistoricalUseConsumer(
            kind="holding", listing_id=listing, instrument_id=instrument.instrument_id
        ),
        "classification",
    )
    return f"{chosen.taxonomy}:{chosen.category}", chosen.category, False


def attribution(
    engine: HistoricalEngine, options: r.AttributionOptions
) -> r.AttributionCalculation:
    start, end = engine.window.start_at, engine.window.end_at
    events = period_events(engine, start, end)
    instants = {start, end, *(event.identity.economic_at for event in events)}
    instants.update(
        session.close_at
        for calendar in engine.value.calendars
        for session in calendar.sessions
        if start < session.close_at < end
    )
    instants.update(
        observation.effective_at
        for snapshot in engine.value.action_snapshots
        for observation in snapshot.observations
        if start < observation.effective_at < end
        and snapshot.provenance.first_observed_at <= engine.cutoff(end)
    )
    ordered = tuple(sorted(instants))
    initial, final = engine.valuation(start), engine.valuation(end)
    flow = amount(event_total(engine, events, "flow"))
    gain = (
        final.total - initial.total - flow
        if final.total is not None
        and initial.total is not None
        and flow is not None
        and not initial.partial
        and not final.partial
        else None
    )
    returns = period_returns(engine, start, end)
    portfolio_return = returns.twr if options.method is d.AttributionMethod.TWR else returns.dietz
    denominator = returns.denominator
    rows_amount: dict[str, dict[EffectKind, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: ZERO)
    )
    rows_return: dict[str, dict[EffectKind, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: ZERO)
    )
    labels: dict[str, tuple[str, bool, str | None, CurrencyCode]] = {}
    unknown_effects: set[EffectKind] = set()
    segments: list[
        tuple[
            datetime,
            datetime,
            dict[tuple[str, EffectKind], Decimal],
            Decimal | None,
            Decimal | None,
        ]
    ] = []
    for left, right in pairwise(ordered):
        opening, closing = engine.valuation(left, after=True), engine.valuation(right)
        effects: dict[tuple[str, EffectKind], Decimal] = defaultdict(lambda: ZERO)
        for listing, quantity in opening.state.quantities.items():
            if quantity == 0:
                continue
            instrument = engine.instruments[listing]
            identity, label, unresolved = partition(
                engine, listing, instrument.native_currency, left, options.grouping
            )
            labels[identity] = (
                label,
                unresolved,
                listing if options.grouping is d.HistoricalGrouping.HOLDING else None,
                instrument.native_currency,
            )
            p0, p1 = opening.native_prices.get(listing), closing.native_prices.get(listing)
            f0, f1 = (
                opening.rates.get(instrument.native_currency),
                closing.rates.get(instrument.native_currency),
            )
            # Fill prices provide actual price boundaries for the affected listing.
            for at, is_start in ((left, True), (right, False)):
                execution_prices = {
                    item.native_price.amount
                    for item in events
                    if isinstance(item, d.HistoricalExecution)
                    and item.listing_id == listing
                    and item.identity.economic_at == at
                }
                if len(execution_prices) == 1:
                    if is_start:
                        p0 = next(iter(execution_prices))
                    else:
                        p1 = next(iter(execution_prices))
                elif len(execution_prices) > 1:
                    p0 = p1 = None
            if None in (p0, p1, f0, f1):
                engine.warnings.add(d.HistoricalReason.VALUATION_MISSING)
                unknown_effects.update(("price", "fx", "interaction"))
                continue
            assert p0 is not None and p1 is not None and f0 is not None and f1 is not None
            effects[(identity, "price")] += quantity * (p1 - p0) * f0
            effects[(identity, "fx")] += quantity * p0 * (f1 - f0)
            effects[(identity, "interaction")] += quantity * (p1 - p0) * (f1 - f0)
        for currency, cash in opening.state.cash.items():
            f0, f1 = opening.rates.get(currency), closing.rates.get(currency)
            identity, label, unresolved = partition(engine, None, currency, left, options.grouping)
            labels[identity] = (label, unresolved, None, currency)
            if f0 is not None and f1 is not None:
                effects[(identity, "cash_fx")] += cash * (f1 - f0)
            elif cash != 0:
                unknown_effects.add("cash_fx")
        # Internal economic effects at the left boundary belong to this segment once.
        for event in events:
            if event.identity.economic_at != left:
                continue
            event_listing = (
                event.listing_id
                if isinstance(event, (d.HistoricalDividend, d.HistoricalExecution))
                else None
            )
            event_currency = (
                event.net.currency
                if isinstance(event, d.HistoricalDividend)
                else event.cash_impact.currency
                if isinstance(event, d.HistoricalExecution)
                else event.signed_amount.currency
                if isinstance(event, d.HistoricalCashEffect)
                else engine.currency
            )
            identity, label, unresolved = (
                ("unresolved", "Unresolved", True)
                if isinstance(event, d.HistoricalDividend) and event_listing is None
                else partition(engine, event_listing, event_currency, left, options.grouping)
            )
            labels[identity] = (
                label,
                unresolved,
                event_listing
                if options.grouping is d.HistoricalGrouping.HOLDING
                and event_listing in engine.instruments
                else None,
                event_currency,
            )
            values: list[tuple[EffectKind, Money | None, int]] = []
            if isinstance(event, d.HistoricalDividend):
                gross, tax = dividend_parts(engine, event)
                if gross is not None and tax is not None:
                    values = [("income", gross, 1), ("taxes", tax, -1)]
                else:
                    values = [("income", event.net, 1)]
                    unknown_effects.add("taxes")
            elif isinstance(event, d.HistoricalExecution):
                values = [("fees", known(event.fees), -1), ("taxes", known(event.taxes), -1)]
            elif isinstance(event, d.HistoricalCashEffect):
                effect: EffectKind | None = (
                    "fees"
                    if event.effect_kind == "fee"
                    else "taxes"
                    if event.effect_kind == "tax"
                    else "income"
                    if event.effect_kind == "interest"
                    else None
                )
                if effect is not None:
                    values = [(effect, event.signed_amount, 1)]
            for effect, native, sign in values:
                converted = converted_event(engine, event, native) if native is not None else None
                if converted is None:
                    unknown_effects.add(effect)
                else:
                    effects[(identity, effect)] += sign * converted
        interval = period_returns(engine, left, right, xirr=False).twr.value
        pre_value = engine.valuation(left)
        opening_flow = sum(
            (
                converted_event(engine, event) or ZERO
                for event in events
                if isinstance(event, d.HistoricalExternalFlow)
                and event.identity.economic_at == left
            ),
            ZERO,
        )
        raw_denominator = pre_value.total + opening_flow if pre_value.total is not None else None
        segment_denominator = (
            raw_denominator
            if raw_denominator is not None and raw_denominator > 0 and not pre_value.partial
            else None
        )
        segments.append((left, right, dict(effects), interval, segment_denominator))
        for (identity, effect), value in effects.items():
            rows_amount[identity][effect] += value
    link: Decimal | None = ONE
    twr_valid = portfolio_return.value is not None
    for _left, _right, effects, interval, segment_denominator in reversed(segments):
        if options.method is d.AttributionMethod.TWR:
            if interval is None or segment_denominator is None or link is None:
                link = None
                twr_valid = False
            else:
                for (identity, effect), value in effects.items():
                    rows_return[identity][effect] += value / segment_denominator * link
                link *= ONE + interval
        elif denominator is not None:
            for (identity, effect), value in effects.items():
                rows_return[identity][effect] += value / denominator
    return_valid = (
        twr_valid
        if options.method is d.AttributionMethod.TWR
        else denominator is not None and portfolio_return.value is not None
    )

    def effect_record(
        effect: EffectKind, value: Decimal, contribution: Decimal
    ) -> r.AttributionEffect:
        return r.AttributionEffect(
            kind=effect,
            amount=money_metric(
                value,
                engine.currency,
                partial=effect in unknown_effects,
                reason=d.HistoricalReason.PARTIAL_COVERAGE,
            ),
            return_contribution=ratio_metric(
                contribution if return_valid else None,
                partial=effect in unknown_effects,
                reason=d.HistoricalReason.PARTIAL_COVERAGE,
            ),
        )

    components: list[r.AttributionComponent] = []
    for identity in sorted(rows_amount):
        component_effects = tuple(
            effect_record(
                effect,
                rows_amount[identity].get(effect, ZERO),
                rows_return[identity].get(effect, ZERO),
            )
            for effect in EFFECTS
        )
        label, unresolved, row_listing, currency = labels[identity]
        components.append(
            r.AttributionComponent(
                key=identity,
                label=label,
                instrument_id=engine.instruments[row_listing].instrument_id
                if row_listing
                else None,
                listing_id=row_listing,
                group_key=identity
                if options.grouping is d.HistoricalGrouping.GROUP
                and not unresolved
                and not identity.startswith("cash:")
                else None,
                currency=currency
                if options.grouping is d.HistoricalGrouping.CURRENCY or identity.startswith("cash:")
                else None,
                amount=money_metric(sum(rows_amount[identity].values(), ZERO), engine.currency),
                return_contribution=ratio_metric(
                    sum(rows_return[identity].values(), ZERO) if return_valid else None
                ),
                effects=component_effects,
                unresolved=unresolved,
            )
        )
    all_effects = tuple(
        effect_record(
            effect,
            sum((values.get(effect, ZERO) for values in rows_amount.values()), ZERO),
            sum((values.get(effect, ZERO) for values in rows_return.values()), ZERO),
        )
        for effect in EFFECTS
    )
    attributed_raw = sum((sum(values.values(), ZERO) for values in rows_amount.values()), ZERO)
    attributed_displayed = sum(
        (item.amount.value.amount for item in components if item.amount.value is not None), ZERO
    )
    uncovered = gain - attributed_raw if gain is not None else None
    quantization = (
        persisted_decimal(gain) - attributed_displayed - persisted_decimal(uncovered)
        if gain is not None and uncovered is not None
        else None
    )
    residual = (
        persisted_decimal(uncovered) + quantization
        if uncovered is not None and quantization is not None
        else None
    )
    attributed_return = (
        sum(
            (
                item.return_contribution.value
                for item in components
                if item.return_contribution.value is not None
            ),
            ZERO,
        )
        if return_valid
        else None
    )
    residual_return = (
        portfolio_return.value - attributed_return
        if portfolio_return.value is not None and attributed_return is not None
        else None
    )
    cash_drag = (
        _cash_drag(engine, ordered, segments, options.method, denominator)
        if engine.value.benchmark_input
        else None
    )
    summary = r.AttributionMetrics(
        investment_gain=money_metric(gain, engine.currency),
        attributed_amount=money_metric(attributed_displayed, engine.currency),
        residual=money_metric(residual, engine.currency),
        uncovered_residual=money_metric(uncovered, engine.currency),
        quantization_residual=money_metric(quantization, engine.currency),
        portfolio_return=portfolio_return,
        attributed_return=ratio_metric(attributed_return),
        residual_return=ratio_metric(residual_return),
        dietz_denominator=money_metric(
            denominator, engine.currency, reason=d.HistoricalReason.NONPOSITIVE_DENOMINATOR
        ),
        cash_drag=ratio_metric(cash_drag, reason=d.HistoricalReason.CASH_COUNTERFACTUAL),
        brinson_allocation=ratio_metric(None, reason=d.HistoricalReason.BRINSON_INPUTS),
        brinson_selection=ratio_metric(None, reason=d.HistoricalReason.BRINSON_INPUTS),
    )
    return r.AttributionCalculation(
        context=engine.context(
            "attribution_bridge_v1",
            available=gain is not None,
            partial=uncovered != 0 or bool(unknown_effects),
        ),
        options=options,
        summary=summary,
        rows=tuple(components),
        effects=all_effects,
        source_uses=engine.ordered_uses(),
        conversions=engine.ordered_conversions(),
    )


def _cash_drag(
    engine: HistoricalEngine,
    instants: tuple[datetime, ...],
    segments: list[
        tuple[
            datetime,
            datetime,
            dict[tuple[str, EffectKind], Decimal],
            Decimal | None,
            Decimal | None,
        ]
    ],
    method: d.AttributionMethod,
    dietz_denominator: Decimal | None,
) -> Decimal | None:
    if (
        engine.value.benchmark_input is None
        or engine.value.benchmark_input.content.return_basis is not PriceBasis.TOTAL_RETURN
    ):
        return None
    wealth, _ = benchmark_wealth(engine, instants)
    result, link = ZERO, ONE
    for left, right, effects, interval, denominator in reversed(segments):
        opening = engine.valuation(left, after=True)
        b0, b1 = wealth[left], wealth[right]
        if (
            opening.cash is None
            or opening.partial
            or denominator is None
            or interval is None
            or b0 is None
            or b1 is None
            or b0 <= 0
        ):
            return None
        cash_fx = sum(
            (value for (_, effect), value in effects.items() if effect == "cash_fx"), ZERO
        )
        interest = ZERO
        for event in period_events(engine, left, right):
            if isinstance(event, d.HistoricalCashEffect) and event.effect_kind == "interest":
                converted = converted_event(engine, event)
                if converted is None:
                    return None
                interest += converted
        counterfactual_amount = cash_fx + interest - opening.cash * (b1 / b0 - ONE)
        if method is d.AttributionMethod.MODIFIED_DIETZ:
            if dietz_denominator is None or dietz_denominator <= 0:
                return None
            result += counterfactual_amount / dietz_denominator
        else:
            result += counterfactual_amount / denominator * link
            link *= ONE + interval
    return result
