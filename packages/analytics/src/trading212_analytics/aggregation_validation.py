"""Bind a retained result to its exact inputs without calling the calculator or a provider."""

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from trading212_domain.aggregation import AggregateReason
from trading212_domain.aggregation_codec import aggregation_record_digest
from trading212_domain.aggregation_inputs import AggregateActivityInput, AggregateHoldingsInput
from trading212_domain.aggregation_results import AggregateActivityResult, AggregateHoldingsResult
from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation

from ._premium_numeric import ZERO, arithmetic, q18
from .quality import combine_quality


def validate_holdings_binding(
    source: AggregateHoldingsInput,
    result: AggregateHoldingsResult,
    *,
    check_deadline: Callable[[], None],
) -> None:
    check_deadline()
    if (
        result.input_digest != aggregation_record_digest(source)
        or result.snapshots != source.snapshots
        or result.reporting_currency != source.selection.reporting_currency
        or result.source_cutoff_at != source.selection.source_cutoff_at
        or tuple(x.native for x in result.components) != source.components
    ):
        fail_validation("Aggregate result differs from its complete saved input partition.")
    quotes = {(x.account_id, x.source_currency): x for x in source.fx_uses}
    pins = {x.account_id: x for x in source.snapshots}
    raw_total = ZERO
    for index, row in enumerate(result.components):
        if index % 64 == 0:
            check_deadline()
        native = row.native
        quote = quotes.get((native.account_id, native.native_currency))
        if (row.fx_observation_id, row.inverted) != (
            None if quote is None else quote.fx_observation_id,
            False if quote is None else quote.inverted,
        ):
            fail_validation("Aggregate conversion substituted the original FX proof.")
        expected: Decimal | None
        reason = None
        with arithmetic():
            if native.native_value is None:
                expected = None
                reason = AggregateReason.VALUE_UNAVAILABLE
            elif native.native_currency == result.reporting_currency:
                expected = native.native_value
                raw_total += expected
            elif quote is None or quote.original_rate is None:
                expected = None
                reason = AggregateReason.FX_MISSING
            else:
                raw = (
                    native.native_value / quote.original_rate
                    if quote.inverted
                    else native.native_value * quote.original_rate
                )
                expected = q18(raw)
                raw_total += raw
        quality = combine_quality(
            (
                native.quality,
                pins[native.account_id].quality,
                *(() if quote is None else (quote.quality,)),
                *(() if expected is not None else (QualityState.PARTIAL,)),
            )
        )
        if (row.converted_value, row.reason, row.quality) != (expected, reason, quality):
            fail_validation(
                "Aggregate component changes an original value, Q18 boundary, reason or quality."
            )
    with arithmetic():
        residual = None if result.total.value is None else result.total.known_value - q18(raw_total)
    if result.rounding_residual != residual:
        fail_validation("Aggregate conversion residual differs from exact original FX arithmetic.")
    check_deadline()


def validate_activity_binding(
    source: AggregateActivityInput,
    result: AggregateActivityResult,
    *,
    check_deadline: Callable[[], None],
) -> None:
    check_deadline()
    if (
        result.input_digest != aggregation_record_digest(source)
        or result.holdings_input_digest != source.holdings_input_digest
        or result.window != source.window
        or result.candidate_count != len(source.candidates)
    ):
        fail_validation("Aggregate activity result changes its complete original input.")
    chosen = tuple(
        x
        for x in source.candidates
        if x.selected and source.window.start_at <= x.occurred_at < source.window.end_at
    )
    if tuple(x.source_record_id for x in result.legs) != tuple(x.source_record_id for x in chosen):
        fail_validation("Aggregate activity omitted or substituted an original selected leg.")
    by_id = {x.source_record_id: x for x in chosen}
    for row, original in zip(result.legs, chosen, strict=True):
        if (row.account_id, row.amount, row.currency, row.occurred_at) != (
            original.account_id,
            original.amount,
            original.currency,
            original.occurred_at,
        ):
            fail_validation("Aggregate flow altered original account, principal, currency or date.")
        if (
            row.classification in ("external", "internal", "fee")
            and row.classification != original.kind
        ):
            fail_validation("Aggregate flow classification differs from original evidence.")
        if original.kind == "transfer" and row.classification not in (
            "matched_transfer",
            "unmatched_transfer",
            "ambiguous_transfer",
        ):
            fail_validation("An original transfer cannot become an external deposit.")
    used_fees: set[UUID] = set()
    for match in result.matches:
        check_deadline()
        outgoing, incoming = by_id[match.outgoing_record_id], by_id[match.incoming_record_id]
        a, b = outgoing.transfer, incoming.transfer
        if (
            a is None
            or b is None
            or a.counterparty_account_id != incoming.account_id
            or b.counterparty_account_id != outgoing.account_id
            or a.transfer_reference != b.transfer_reference
            or a.transfer_reference != match.transfer_reference
        ):
            fail_validation("Aggregate transfer omitted original mutual counterparty proof.")
        competing = tuple(
            x
            for x in chosen
            if x.transfer is not None
            and x.transfer.transfer_reference == a.transfer_reference
            and {x.account_id, x.transfer.counterparty_account_id}
            == {outgoing.account_id, incoming.account_id}
        )
        if len(competing) != 2:
            fail_validation(
                "Aggregate transfer silently selected among ambiguous original counterparts."
            )
        cross = a.currency != b.currency
        if cross:
            if (
                (a.fx_rate, a.fx_base_currency, a.fx_quote_currency)
                != (b.fx_rate, b.fx_base_currency, b.fx_quote_currency)
                or (a.fx_rate, a.fx_base_currency, a.fx_quote_currency)
                != (match.fx_rate, match.fx_base_currency, match.fx_quote_currency)
                or a.fx_rate is None
            ):
                fail_validation("Aggregate transfer changes original cross-currency FX evidence.")
            for candidate, proof in ((outgoing, a), (incoming, b)):
                fee = by_id.get(proof.fee_record_id) if proof.fee_record_id is not None else None
                if (
                    fee is None
                    or fee.kind != "fee"
                    or fee.account_id != candidate.account_id
                    or (fee.amount, fee.currency) != (proof.fee_amount, proof.fee_currency)
                    or fee.source_record_id in used_fees
                ):
                    fail_validation("Aggregate transfer changes or reuses an original fee record.")
                used_fees.add(fee.source_record_id)
            if match.fee_record_ids != (a.fee_record_id, b.fee_record_id):
                fail_validation("Aggregate transfer fee identity inventory differs.")
            with arithmetic():
                converted = (
                    q18(a.principal.copy_abs() * a.fx_rate)
                    if a.currency == a.fx_base_currency
                    else q18(b.principal.copy_abs() * a.fx_rate)
                )
            expected = (
                b.principal.copy_abs()
                if a.currency == a.fx_base_currency
                else a.principal.copy_abs()
            )
            if converted != expected:
                fail_validation("Aggregate transfer principals do not match original FX.")
    if (
        any(x.selection_reason == AggregateReason.AMBIGUOUS_REVISION for x in source.candidates)
        and AggregateReason.AMBIGUOUS_REVISION not in result.reasons
    ):
        fail_validation("Aggregate activity suppresses original revision ambiguity.")
    for account in source.account_ids:
        end = source.window.start_at
        for fragment in sorted(
            (
                x
                for x in source.coverage
                if x.account_id == account
                and x.capability == "historical_transactions"
                and x.complete
            ),
            key=lambda x: (x.start_at, x.end_at, x.coverage_id),
        ):
            if fragment.start_at > end:
                break
            end = max(end, fragment.end_at)
        if end < source.window.end_at and AggregateReason.COVERAGE_INCOMPLETE not in result.reasons:
            fail_validation("Aggregate activity claims unproven original window coverage.")
    check_deadline()
