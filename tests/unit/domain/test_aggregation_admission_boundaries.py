"""Exact domain admission edges; these do not claim stored PostgreSQL saturation."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.aggregation import calculate_aggregation
from trading212_application.aggregation import CreateAggregateRun
from trading212_domain.aggregation import (
    AggregateActivityWindow,
    AggregateFxBinding,
    AggregateMember,
    AggregateReason,
)
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.values import CurrencyCode

from tests.unit.analytics.test_aggregation import EARLIER, NOW, activity, flow, holdings


def test_eighth_member_is_admitted_and_ninth_distinct_member_is_rejected() -> None:
    selected = holdings().selection
    members = tuple(
        AggregateMember(account_id=UUID(int=index), portfolio_snapshot_id=UUID(int=100 + index))
        for index in range(1, 10)
    )
    admitted = replace(selected, members=members[:8])
    assert len(admitted.members) == 8
    with pytest.raises(DomainError) as denied:
        replace(selected, members=members)
    assert denied.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert denied.value.field == "members"


def test_exact_256_unique_fx_request_pins_are_preserved_and_257_are_rejected() -> None:
    # This tests the command admission bound. Source/currency/account eligibility
    # remains a separate persisted-source predicate, rather than invented here.
    currencies = tuple(
        CurrencyCode(f"X{chr(65 + index // 26)}{chr(65 + index % 26)}") for index in range(32)
    )
    bindings = tuple(
        AggregateFxBinding(
            account_id=UUID(int=account),
            currency=currency,
            fx_observation_id=UUID(int=1000 + account * 32 + index),
        )
        for account in range(1, 9)
        for index, currency in enumerate(currencies)
    )
    request = CreateAggregateRun(
        selection_id=UUID(int=500),
        expected_revision=1,
        fx_bindings=bindings[::-1],
        idempotency_key="aggregation-boundary-fx",
        correlation_id="aggregation-domain-boundary",
    )
    assert len(request.fx_bindings) == 256
    assert set(request.fx_bindings) == set(bindings)
    extra = AggregateFxBinding(
        account_id=UUID(int=9), currency=CurrencyCode("ZZZ"), fx_observation_id=UUID(int=9000)
    )
    with pytest.raises(DomainError) as denied:
        replace(request, fx_bindings=(*bindings, extra))
    assert denied.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert denied.value.field == "fx"
    with pytest.raises(DomainError) as duplicate:
        replace(request, fx_bindings=(bindings[0], bindings[0]))
    assert duplicate.value.code is ErrorCode.VALIDATION_FAILED


def test_exact_3660_day_activity_window_is_admitted_and_one_microsecond_more_is_rejected() -> None:
    admitted = AggregateActivityWindow(start_at=NOW - timedelta(days=3660), end_at=NOW)
    assert admitted.end_at - admitted.start_at == timedelta(days=3660)
    with pytest.raises(DomainError) as denied:
        replace(admitted, start_at=admitted.start_at - timedelta(microseconds=1))
    assert denied.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert denied.value.field == "window"


def test_exact_10000_activity_candidates_are_preserved_and_overflow_is_rejected() -> None:
    original = flow(101, 1, "-50")
    candidates = tuple(
        replace(
            original,
            source_record_id=UUID(int=1000 + index),
            external_record_id=f"custody:activity:boundary-{index}",
        )
        for index in range(10001)
    )
    admitted = activity(candidates[:10000])
    assert len(admitted.candidates) == 10000
    assert admitted.candidates[-1].source_record_id == UUID(int=10999)
    with pytest.raises(DomainError) as denied:
        replace(admitted, candidates=candidates)
    assert denied.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert denied.value.field == "activity.candidates"


def test_32_native_currencies_keep_unknown_mass_and_33_are_rejected() -> None:
    original = holdings()
    first = original.components[0]
    currencies = (
        CurrencyCode("EUR"),
        *(CurrencyCode(f"X{chr(65 + index // 26)}{chr(65 + index % 26)}") for index in range(32)),
    )
    components = tuple(
        replace(
            first,
            component_id=UUID(int=1000 + index),
            kind="cash",
            listing_id=None,
            instrument_id=None,
            quantity=None,
            native_currency=currency,
            native_value=Decimal("1"),
            source_record_ids=(UUID(int=2000 + index),),
        )
        for index, currency in enumerate(currencies)
    )
    admitted = replace(original, components=components[:32], fx_uses=())
    actual = calculate_aggregation(admitted)
    assert len(actual.components) == 32
    assert actual.total.value is None and actual.total.known_value == Decimal("1")
    assert (actual.total.known_count, actual.total.total_count) == (1, 32)
    assert actual.total.reason is AggregateReason.FX_MISSING
    assert all(row.converted_value is None for row in actual.components[1:])
    with pytest.raises(DomainError) as denied:
        replace(admitted, components=components)
    assert denied.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert denied.value.field == "currencies"


def test_exact_10000_distinct_positions_are_admitted_without_truncating_input() -> None:
    original = holdings()
    first = original.components[0]
    components = tuple(
        replace(
            first,
            component_id=UUID(int=1000 + index),
            listing_id=UUID(int=20000 + index),
            source_record_ids=(UUID(int=40000 + index),),
        )
        for index in range(10001)
    )
    admitted = replace(original, components=components[:10000], fx_uses=())
    assert len(admitted.components) == 10000
    assert admitted.components[-1].component_id == UUID(int=10999)
    with pytest.raises(DomainError) as denied:
        replace(admitted, components=components)
    assert denied.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert denied.value.field == "holdings"


def test_activity_after_source_cutoff_is_rejected_without_reinterpreting_window() -> None:
    original = activity((flow(101, 1, "-50"),))
    assert original.window == AggregateActivityWindow(start_at=EARLIER, end_at=NOW)
    with pytest.raises(DomainError) as denied:
        replace(original, source_cutoff_at=NOW - timedelta(microseconds=1))
    assert denied.value.code is ErrorCode.VALIDATION_FAILED
