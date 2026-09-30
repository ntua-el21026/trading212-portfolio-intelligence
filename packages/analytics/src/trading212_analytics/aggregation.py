"""Exact saved-value aggregation with explicit FX and independent flow proof."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from decimal import Decimal
from typing import Literal
from uuid import UUID

from trading212_domain.aggregation import AggregateMoney, AggregateReason
from trading212_domain.aggregation_codec import aggregation_record_digest
from trading212_domain.aggregation_inputs import (
    AggregateActivityCandidate,
    AggregateActivityInput,
    AggregateHoldingsInput,
)
from trading212_domain.aggregation_results import (
    AggregateAccountTotal,
    AggregateActivityResult,
    AggregateComponent,
    AggregateFlowCurrencyTotal,
    AggregateFlowLeg,
    AggregateHolding,
    AggregateHoldingsResult,
    AggregateTransferMatch,
)
from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.values import CurrencyCode

from ._premium_numeric import ZERO, arithmetic, q18
from .quality import combine_quality


def _checkpoint(check: Callable[[], None] | None) -> None:
    if check is not None:
        check()


def _money(rows: tuple[AggregateComponent, ...], currency: CurrencyCode) -> AggregateMoney:
    with arithmetic():
        known = sum((x.converted_value for x in rows if x.converted_value is not None), ZERO)
    count = sum(x.converted_value is not None for x in rows)
    complete = count == len(rows)
    quality = combine_quality(x.quality for x in rows)
    if not complete:
        quality = combine_quality((quality, QualityState.PARTIAL))
    reason = (
        None
        if complete
        else (
            AggregateReason.VALUE_UNAVAILABLE
            if any(x.reason == AggregateReason.VALUE_UNAVAILABLE for x in rows)
            else AggregateReason.FX_MISSING
        )
    )
    return AggregateMoney(
        currency=currency,
        value=known if complete else None,
        known_value=known,
        known_count=count,
        total_count=len(rows),
        quality=quality,
        reason=reason,
    )


def calculate_aggregation(
    value: AggregateHoldingsInput, *, check_deadline: Callable[[], None] | None = None
) -> AggregateHoldingsResult:
    if type(value) is not AggregateHoldingsInput:
        fail_validation("Exact saved aggregation inputs are required.")
    _checkpoint(check_deadline)
    input_digest = aggregation_record_digest(value)
    _checkpoint(check_deadline)
    currency = value.selection.reporting_currency
    quotes = {(x.account_id, x.source_currency): x for x in value.fx_uses}
    snapshots = {x.account_id: x for x in value.snapshots}
    components: list[AggregateComponent] = []
    unrounded = ZERO
    for index, native in enumerate(value.components):
        if index % 64 == 0:
            _checkpoint(check_deadline)
        quote = quotes.get((native.account_id, native.native_currency))
        reason = None
        converted: Decimal | None
        with arithmetic():
            if native.native_value is None:
                converted = None
                reason = AggregateReason.VALUE_UNAVAILABLE
            elif native.native_currency == currency:
                converted = native.native_value
                unrounded += converted
            elif quote is None or quote.original_rate is None:
                converted = None
                reason = AggregateReason.FX_MISSING
            else:
                raw = (
                    native.native_value / quote.original_rate
                    if quote.inverted
                    else native.native_value * quote.original_rate
                )
                converted = q18(raw)
                unrounded += raw
        quality = combine_quality(
            (
                native.quality,
                snapshots[native.account_id].quality,
                *(() if quote is None else (quote.quality,)),
            )
        )
        if converted is None:
            quality = combine_quality((quality, QualityState.PARTIAL))
        components.append(
            AggregateComponent(
                native=native,
                reporting_currency=currency,
                converted_value=converted,
                fx_observation_id=quote.fx_observation_id if quote else None,
                inverted=quote.inverted if quote else False,
                quality=quality,
                reason=reason,
            )
        )
    rows = tuple(components)
    by_account: dict[UUID, list[AggregateComponent]] = defaultdict(list)
    by_instrument: dict[UUID, list[AggregateComponent]] = defaultdict(list)
    for row in rows:
        by_account[row.native.account_id].append(row)
        if row.native.instrument_id is not None:
            by_instrument[row.native.instrument_id].append(row)
    accounts = tuple(
        AggregateAccountTotal(
            account_id=x.account_id, money=_money(tuple(by_account[x.account_id]), currency)
        )
        for x in value.snapshots
    )
    holdings: list[AggregateHolding] = []
    for instrument_id in sorted(by_instrument):
        _checkpoint(check_deadline)
        group = tuple(by_instrument[instrument_id])
        with arithmetic():
            quantity = sum(
                (x.native.quantity for x in group if x.native.quantity is not None), ZERO
            )
        member_rows = tuple(
            AggregateAccountTotal(
                account_id=x.account_id,
                money=_money(
                    tuple(row for row in group if row.native.account_id == x.account_id), currency
                ),
            )
            for x in value.snapshots
            if any(row.native.account_id == x.account_id for row in group)
        )
        holdings.append(
            AggregateHolding(
                instrument_id=instrument_id,
                quantity=quantity,
                money=_money(group, currency),
                account_totals=member_rows,
            )
        )
    total = _money(rows, currency)
    with arithmetic():
        residual = total.known_value - q18(unrounded) if total.value is not None else None
    result = AggregateHoldingsResult(
        input_digest=input_digest,
        reporting_currency=currency,
        source_cutoff_at=value.selection.source_cutoff_at,
        snapshots=value.snapshots,
        components=rows,
        holdings=tuple(holdings),
        accounts=accounts,
        securities=_money(tuple(x for x in rows if x.native.kind == "position"), currency),
        cash=_money(tuple(x for x in rows if x.native.kind == "cash"), currency),
        total=total,
        rounding_residual=residual,
    )
    _checkpoint(check_deadline)
    aggregation_record_digest(result)
    _checkpoint(check_deadline)
    return result


def _fee_bound(
    row: AggregateActivityCandidate, selected: dict[UUID, AggregateActivityCandidate]
) -> bool:
    proof = row.transfer
    if proof is None or proof.fee_record_id is None:
        return False
    fee = selected.get(proof.fee_record_id)
    return (
        fee is not None
        and fee.kind == "fee"
        and fee.account_id == row.account_id
        and fee.amount == proof.fee_amount
        and fee.currency == proof.fee_currency
    )


def _matching_principal(
    left: AggregateActivityCandidate,
    right: AggregateActivityCandidate,
    selected: dict[UUID, AggregateActivityCandidate],
) -> bool:
    a, b = left.transfer, right.transfer
    if a is None or b is None or (a.principal < 0) == (b.principal < 0):
        return False
    with arithmetic():
        if a.currency == b.currency:
            return a.principal + b.principal == 0
        if not _fee_bound(left, selected) or not _fee_bound(right, selected):
            return False
        if (a.fx_rate, a.fx_base_currency, a.fx_quote_currency) != (
            b.fx_rate,
            b.fx_base_currency,
            b.fx_quote_currency,
        ) or a.fx_rate is None:
            return False
        if (a.currency, b.currency) == (a.fx_base_currency, a.fx_quote_currency):
            return q18(a.principal.copy_abs() * a.fx_rate) == b.principal.copy_abs()
        if (b.currency, a.currency) == (a.fx_base_currency, a.fx_quote_currency):
            return q18(b.principal.copy_abs() * a.fx_rate) == a.principal.copy_abs()
        return False


def calculate_aggregate_activity(
    value: AggregateActivityInput, *, check_deadline: Callable[[], None] | None = None
) -> AggregateActivityResult:
    if type(value) is not AggregateActivityInput:
        fail_validation("Exact saved activity inputs are required.")
    _checkpoint(check_deadline)
    digest = aggregation_record_digest(value)
    _checkpoint(check_deadline)
    rows = tuple(
        x
        for x in value.candidates
        if x.selected and value.window.start_at <= x.occurred_at < value.window.end_at
    )
    selected = {x.source_record_id: x for x in rows}
    groups: dict[tuple[str, UUID, UUID], list[AggregateActivityCandidate]] = defaultdict(list)
    for row in rows:
        if row.transfer is not None and row.transfer.counterparty_account_id in value.account_ids:
            lo, hi = sorted((row.account_id, row.transfer.counterparty_account_id))
            groups[(row.transfer.transfer_reference, lo, hi)].append(row)
    fee_claims = Counter(
        x.transfer.fee_record_id
        for x in rows
        if x.transfer is not None and x.transfer.fee_record_id is not None
    )
    matched: dict[UUID, UUID] = {}
    ambiguous: set[UUID] = set()
    incomplete: set[UUID] = set()
    matches: list[AggregateTransferMatch] = []
    for key in sorted(groups):
        _checkpoint(check_deadline)
        candidates = groups[key]
        if len(candidates) == 1:
            continue
        if len(candidates) != 2 or candidates[0].account_id == candidates[1].account_id:
            ambiguous.update(x.source_record_id for x in candidates)
            continue
        left, right = candidates
        a, b = left.transfer, right.transfer
        if a is None or b is None:
            fail_validation("Transfer group lost its original proof.")
        if (
            (
                a.currency != b.currency
                and any(x is None or fee_claims[x] != 1 for x in (a.fee_record_id, b.fee_record_id))
            )
            or a.counterparty_account_id != right.account_id
            or b.counterparty_account_id != left.account_id
            or not _matching_principal(left, right, selected)
        ):
            incomplete.update(x.source_record_id for x in candidates)
            continue
        outgoing, incoming = (left, right) if a.principal < 0 else (right, left)
        out, inc = outgoing.transfer, incoming.transfer
        if out is None or inc is None:
            fail_validation("Matched transfer lost its original proof.")
        matched[left.source_record_id] = right.source_record_id
        matched[right.source_record_id] = left.source_record_id
        cross = out.currency != inc.currency
        matches.append(
            AggregateTransferMatch(
                outgoing_record_id=outgoing.source_record_id,
                incoming_record_id=incoming.source_record_id,
                outgoing_account_id=outgoing.account_id,
                incoming_account_id=incoming.account_id,
                transfer_reference=out.transfer_reference,
                outgoing_principal=out.principal,
                outgoing_currency=out.currency,
                incoming_principal=inc.principal,
                incoming_currency=inc.currency,
                fx_rate=out.fx_rate if cross else None,
                fx_base_currency=out.fx_base_currency if cross else None,
                fx_quote_currency=out.fx_quote_currency if cross else None,
                fee_record_ids=tuple(
                    x for x in (out.fee_record_id, inc.fee_record_id) if x is not None
                )
                if cross
                else (),
            )
        )
    legs: list[AggregateFlowLeg] = []
    reasons: set[AggregateReason] = set()
    external: dict[CurrencyCode, Decimal] = defaultdict(lambda: ZERO)
    fees: dict[CurrencyCode, Decimal] = defaultdict(lambda: ZERO)
    for index, row in enumerate(rows):
        if index % 64 == 0:
            _checkpoint(check_deadline)
        classification: Literal[
            "external",
            "internal",
            "fee",
            "matched_transfer",
            "unmatched_transfer",
            "ambiguous_transfer",
            "unknown",
        ]
        reason = None
        if row.source_record_id in matched:
            classification = "matched_transfer"
        elif row.source_record_id in ambiguous:
            classification, reason = "ambiguous_transfer", AggregateReason.AMBIGUOUS_TRANSFER
        elif row.kind == "transfer":
            classification = "unmatched_transfer"
            reason = (
                AggregateReason.TRANSFER_PROOF_INCOMPLETE
                if row.source_record_id in incomplete
                else AggregateReason.UNMATCHED_TRANSFER
            )
        elif row.kind == "unknown" or row.amount is None:
            classification, reason = "unknown", AggregateReason.UNKNOWN_ACTIVITY
        else:
            classification = row.kind
        if reason is not None:
            reasons.add(reason)
        legs.append(
            AggregateFlowLeg(
                source_record_id=row.source_record_id,
                account_id=row.account_id,
                occurred_at=row.occurred_at,
                amount=row.amount,
                currency=row.currency,
                classification=classification,
                counterpart_record_id=matched.get(row.source_record_id),
                reason=reason,
            )
        )
        with arithmetic():
            if row.currency is not None and row.amount is not None:
                if classification == "external":
                    external[row.currency] += row.amount
                elif classification == "fee":
                    fees[row.currency] += row.amount
    for account in value.account_ids:
        # Original complete transaction-coverage fragments may form a contiguous
        # union. Order/dividend coverage never claims cash transaction coverage.
        covered_until = value.window.start_at
        for fragment in sorted(
            (
                x
                for x in value.coverage
                if x.account_id == account
                and x.capability == "historical_transactions"
                and x.complete
            ),
            key=lambda x: (x.start_at, x.end_at, x.coverage_id),
        ):
            _checkpoint(check_deadline)
            if fragment.start_at > covered_until:
                break
            covered_until = max(covered_until, fragment.end_at)
        if covered_until < value.window.end_at:
            reasons.add(AggregateReason.COVERAGE_INCOMPLETE)
    if any(x.selection_reason == AggregateReason.AMBIGUOUS_REVISION for x in value.candidates):
        reasons.add(AggregateReason.AMBIGUOUS_REVISION)
    result = AggregateActivityResult(
        input_digest=digest,
        holdings_input_digest=value.holdings_input_digest,
        window=value.window,
        legs=tuple(legs),
        matches=tuple(matches),
        currency_totals=tuple(
            AggregateFlowCurrencyTotal(currency=x, external_net=external[x], fees=fees[x])
            for x in sorted(set(external) | set(fees), key=str)
        ),
        complete=not reasons,
        reasons=tuple(sorted(reasons)),
        candidate_count=len(value.candidates),
        selected_count=len(rows),
    )
    _checkpoint(check_deadline)
    aggregation_record_digest(result)
    _checkpoint(check_deadline)
    return result
