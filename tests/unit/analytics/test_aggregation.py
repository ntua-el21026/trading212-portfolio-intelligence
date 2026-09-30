"""Independent exact-value oracles, never another call to the production calculator."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, localcontext
from uuid import UUID

import pytest
from trading212_analytics.aggregation import calculate_aggregate_activity, calculate_aggregation
from trading212_domain.aggregation import (
    AggregateActivityWindow,
    AggregateMember,
    AggregateReason,
    AggregateSelectionContent,
)
from trading212_domain.aggregation_codec import (
    aggregation_holdings_result_from_json,
    aggregation_record_bytes,
    aggregation_record_digest,
)
from trading212_domain.aggregation_inputs import (
    AggregateActivityCandidate,
    AggregateActivityCoverage,
    AggregateActivityInput,
    AggregateFxUse,
    AggregateHoldingsInput,
    AggregateNativeComponent,
    AggregateSnapshotPin,
    AggregateTransferAttestation,
)
from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode

NOW = datetime(2026, 9, 15, 10, tzinfo=UTC)
EARLIER = datetime(2026, 9, 14, 10, tzinfo=UTC)
EUR, USD = CurrencyCode("EUR"), CurrencyCode("USD")


def uid(value: int) -> UUID:
    return UUID(int=value)


def holdings(*, missing: bool = False) -> AggregateHoldingsInput:
    members = tuple(
        AggregateMember(account_id=uid(a), portfolio_snapshot_id=uid(a + 10)) for a in (1, 2)
    )
    pins = tuple(
        AggregateSnapshotPin(
            account_id=x.account_id,
            portfolio_snapshot_id=x.portfolio_snapshot_id,
            calculation_run_id=uid(n + 20),
            calculation_version="portfolio_snapshot/1.0.0",
            valuation_at=NOW,
            source_cutoff_at=NOW,
            reporting_currency=USD,
            quality=QualityState.FRESH,
            content_digest=str(n) * 64,
        )
        for n, x in enumerate(members, 1)
    )
    components = tuple(
        AggregateNativeComponent(
            component_id=uid(n + 30),
            account_id=x.account_id,
            portfolio_snapshot_id=x.portfolio_snapshot_id,
            kind="position",
            listing_id=uid(n + 40),
            instrument_id=uid(50),
            quantity=Decimal("1"),
            native_currency=USD,
            native_value=Decimal("1"),
            quality=QualityState.FRESH,
            origin=ValueOrigin.OBSERVED_PROVIDER,
            source_record_ids=(uid(n + 60),),
        )
        for n, x in enumerate(members, 1)
    )
    fx = tuple(
        AggregateFxUse(
            account_id=x.account_id,
            source_currency=USD,
            target_currency=EUR,
            fx_snapshot_id=uid(70),
            fx_observation_id=uid(71),
            provider_id=uid(73),
            license_version_id=uid(72),
            snapshot_digest="a" * 64,
            base_currency=EUR,
            quote_currency=USD,
            original_rate=Decimal("3"),
            inverted=True,
            effective_at=EARLIER,
            first_known_at=EARLIER,
            quality=QualityState.FRESH,
        )
        for x in members[: 1 if missing else 2]
    )
    return AggregateHoldingsInput(
        owner_id=uid(90),
        selection=AggregateSelectionContent(
            name="Two custody accounts",
            members=members,
            reporting_currency=EUR,
            source_cutoff_at=NOW,
        ),
        snapshots=pins,
        components=components,
        fx_uses=fx,
    )


def test_canonical_economic_join_adds_two_accounts_and_discloses_q18_residual() -> None:
    value = calculate_aggregation(holdings())
    assert len(value.holdings) == 1
    assert value.holdings[0].instrument_id == uid(50)
    assert value.holdings[0].quantity == Decimal("2")
    assert [x.converted_value for x in value.components] == [Decimal("0.333333333333333333")] * 2
    assert value.total.value == Decimal("0.666666666666666666")
    assert value.rounding_residual == Decimal("-0.000000000000000001")
    assert [x.money.value for x in value.accounts] == [Decimal("0.333333333333333333")] * 2
    assert (
        aggregation_holdings_result_from_json(
            aggregation_record_bytes(value), expected_digest=aggregation_record_digest(value)
        )
        == value
    )


def test_missing_fx_keeps_native_rows_and_available_account_without_fabricating_total() -> None:
    result = calculate_aggregation(holdings(missing=True))
    assert result.total.value is None
    assert result.total.known_value == Decimal("0.333333333333333333")
    assert (result.total.known_count, result.total.total_count) == (1, 2)
    assert result.total.reason == AggregateReason.FX_MISSING
    assert result.components[1].native.native_value == Decimal("1")
    assert result.components[1].converted_value is None
    assert result.rounding_residual is None
    assert result.accounts[0].money.value is not None
    assert result.accounts[1].money.value is None


def test_hostile_ambient_decimal_context_cannot_change_publication() -> None:
    source = holdings()
    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        actual = calculate_aggregation(source)
    assert actual.total.value == Decimal("0.666666666666666666")


def test_equal_provider_labels_are_not_economic_identity() -> None:
    source = holdings()
    second = replace(source.components[1], instrument_id=uid(51))
    result = calculate_aggregation(replace(source, components=(source.components[0], second)))
    assert len(result.holdings) == 2


def test_duplicate_account_snapshot_or_economic_component_is_rejected() -> None:
    source = holdings()
    with pytest.raises(DomainError):
        replace(
            source.selection, members=(source.selection.members[0], source.selection.members[0])
        )
    with pytest.raises(DomainError):
        replace(
            source,
            components=(source.components[0], replace(source.components[0], component_id=uid(999))),
        )
    with pytest.raises(DomainError):
        replace(source.fx_uses[0], target_currency=USD)


def test_corrupted_normalized_totals_cannot_be_canonicalized() -> None:
    result = calculate_aggregation(holdings())
    with pytest.raises(DomainError):
        replace(result, total=replace(result.total, value=Decimal("4"), known_value=Decimal("4")))


def flow(
    record: int,
    account: int,
    principal: str,
    *,
    proof: bool = True,
    counterparty: int | None = None,
) -> AggregateActivityCandidate:
    amount = Decimal(principal)
    return AggregateActivityCandidate(
        source_record_id=uid(record),
        account_id=uid(account),
        provider="synthetic",
        external_record_id=f"custody:activity:{record}",
        schema_version="synthetic-custody-v1:historical_transactions",
        payload_digest="f" * 64,
        source_updated_at=EARLIER,
        first_observed_at=EARLIER,
        occurred_at=EARLIER,
        kind="transfer",
        amount=amount,
        currency=EUR,
        selected=True,
        selection_reason=None,
        transfer=AggregateTransferAttestation(
            counterparty_account_id=uid(counterparty or (2 if account == 1 else 1)),
            transfer_reference="original-transfer-123",
            principal=amount,
            currency=EUR,
            fx_rate=None,
            fx_base_currency=None,
            fx_quote_currency=None,
            fee_record_id=None,
            fee_amount=None,
            fee_currency=None,
        )
        if proof
        else None,
    )


def activity(rows: tuple[AggregateActivityCandidate, ...]) -> AggregateActivityInput:
    return AggregateActivityInput(
        holdings_input_digest="a" * 64,
        window=AggregateActivityWindow(start_at=EARLIER, end_at=NOW),
        account_ids=(uid(1), uid(2)),
        source_cutoff_at=NOW,
        candidates=rows,
        coverage=tuple(
            AggregateActivityCoverage(
                account_id=uid(a),
                ingestion_run_id=uid(a + 80),
                coverage_id=uid(a + 180),
                historical_evidence_id=uid(a + 280),
                evidence_digest="e" * 64,
                capability="historical_transactions",
                start_at=EARLIER,
                end_at=NOW,
                first_observed_at=NOW,
                complete=True,
            )
            for a in (1, 2)
        ),
    )


def test_mutual_original_transfer_matches_and_never_becomes_external_deposit() -> None:
    result = calculate_aggregate_activity(activity((flow(101, 1, "-50"), flow(102, 2, "50"))))
    assert result.complete
    assert len(result.matches) == 1
    assert result.matches[0].outgoing_record_id == uid(101)
    assert result.matches[0].incoming_record_id == uid(102)
    assert all(x.classification == "matched_transfer" for x in result.legs)
    assert result.currency_totals == ()


def test_same_dates_amounts_without_original_counterparty_evidence_stay_unmatched() -> None:
    result = calculate_aggregate_activity(
        activity((flow(101, 1, "-50", proof=False), flow(102, 2, "50", proof=False)))
    )
    assert not result.complete
    assert result.matches == ()
    assert result.reasons == (AggregateReason.UNMATCHED_TRANSFER,)


def test_competing_original_counterparts_are_ambiguous() -> None:
    result = calculate_aggregate_activity(
        activity((flow(101, 1, "-50"), flow(102, 2, "50"), flow(103, 2, "50")))
    )
    assert result.matches == ()
    assert result.reasons == (AggregateReason.AMBIGUOUS_TRANSFER,)


def test_unknown_coverage_and_revision_never_become_zero_flow() -> None:
    row = replace(
        flow(101, 1, "-50"), selected=False, selection_reason=AggregateReason.AMBIGUOUS_REVISION
    )
    result = calculate_aggregate_activity(replace(activity((row,)), coverage=()))
    assert not result.complete
    assert set(result.reasons) == {
        AggregateReason.AMBIGUOUS_REVISION,
        AggregateReason.COVERAGE_INCOMPLETE,
    }


def test_deadline_is_checked_before_and_after_serialization_and_during_work() -> None:
    calls = 0

    def stop() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise TimeoutError("bounded aggregation deadline")

    with pytest.raises(TimeoutError):
        calculate_aggregation(holdings(), check_deadline=stop)
    assert calls == 3


def test_cross_currency_transfer_requires_actual_fees_and_preserves_fee_costs() -> None:
    out = flow(101, 1, "-100")
    inc = flow(102, 2, "120")
    assert out.transfer is not None and inc.transfer is not None
    out_proof = replace(
        out.transfer,
        fx_rate=Decimal("1.2"),
        fx_base_currency=EUR,
        fx_quote_currency=USD,
        fee_record_id=uid(103),
        fee_amount=Decimal("-2"),
        fee_currency=EUR,
    )
    inc_proof = replace(
        inc.transfer,
        currency=USD,
        fx_rate=Decimal("1.2"),
        fx_base_currency=EUR,
        fx_quote_currency=USD,
        fee_record_id=uid(104),
        fee_amount=Decimal("0"),
        fee_currency=USD,
    )
    out = replace(out, transfer=out_proof)
    inc = replace(flow(102, 2, "120"), currency=USD, transfer=inc_proof)
    without_fees = calculate_aggregate_activity(activity((out, inc)))
    assert without_fees.matches == ()
    assert not without_fees.complete
    fee1 = replace(flow(103, 1, "-2", proof=False), kind="fee")
    fee2 = replace(flow(104, 2, "0", proof=False), kind="fee", currency=USD)
    result = calculate_aggregate_activity(activity((out, inc, fee1, fee2)))
    assert len(result.matches) == 1
    assert result.complete
    assert result.matches[0].fx_rate == Decimal("1.2")
    assert result.matches[0].fee_record_ids == (uid(103), uid(104))
    assert {str(x.currency): x.fees for x in result.currency_totals} == {
        "EUR": Decimal("-2"),
        "USD": Decimal("0"),
    }


def test_supplied_missing_observation_remains_missing_with_actual_source_identity() -> None:
    from trading212_domain.sources import ObservationState

    source = holdings()
    missing = replace(source.fx_uses[1], original_rate=None, state=ObservationState.MISSING)
    result = calculate_aggregation(replace(source, fx_uses=(source.fx_uses[0], missing)))
    assert result.total.value is None
    assert result.components[1].fx_observation_id == missing.fx_observation_id
    assert result.components[1].reason == AggregateReason.FX_MISSING


def test_matched_pair_does_not_imply_whole_window_coverage() -> None:
    source = activity((flow(101, 1, "-50"), flow(102, 2, "50")))
    for fragments in (
        (),
        (source.coverage[0], replace(source.coverage[1], complete=False)),
        (source.coverage[0], replace(source.coverage[1], capability="historical_orders")),
    ):
        result = calculate_aggregate_activity(replace(source, coverage=fragments))
        assert len(result.matches) == 1
        assert not result.complete
        assert result.reasons == (AggregateReason.COVERAGE_INCOMPLETE,)


def test_actual_coverage_fragments_join_only_without_gap() -> None:
    source = activity((flow(101, 1, "-50"), flow(102, 2, "50")))
    split = EARLIER + timedelta(hours=12)
    first = replace(source.coverage[1], end_at=split)
    second = replace(source.coverage[1], coverage_id=uid(1000), start_at=split)
    assert calculate_aggregate_activity(
        replace(source, coverage=(source.coverage[0], first, second))
    ).complete
    gapped = replace(second, start_at=split + timedelta(seconds=1))
    assert not calculate_aggregate_activity(
        replace(source, coverage=(source.coverage[0], first, gapped))
    ).complete


def test_single_retained_transfer_is_unmatched_without_invented_ambiguity() -> None:
    result = calculate_aggregate_activity(activity((flow(101, 1, "-50"),)))
    assert result.reasons == (AggregateReason.UNMATCHED_TRANSFER,)
    assert result.matches == ()
