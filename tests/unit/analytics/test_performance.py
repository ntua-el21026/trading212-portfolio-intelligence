from decimal import Decimal

import pytest
from trading212_analytics import (
    DatedExternalFlow,
    SubperiodReturnInput,
    build_performance_summary,
    calculate_modified_dietz,
    calculate_time_weighted_return,
    calculate_xirr,
)
from trading212_domain import Coverage, Instant, Money, QualityState

from .factories import END, MID, START

pytestmark = pytest.mark.unit


def _coverage(*, complete: bool = True) -> Coverage:
    return Coverage(START, END, complete, () if complete else ("history_truncated",))


def test_xirr_solves_exact_one_year_no_flow_gain() -> None:
    result = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("110", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(),
    )
    assert result.value is not None
    assert result.value.value == Decimal("0.100000000000000000")
    assert result.annualized_value == result.value
    assert result.converged is True
    assert result.iterations is not None


def test_xirr_uses_external_flows_only_and_accepts_irregular_dates() -> None:
    result = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("220", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(DatedExternalFlow(Money.parse("100", "EUR"), MID),),
        coverage=_coverage(),
    )
    assert result.value is not None
    assert result.converged is True
    assert result.value.value > 0


def test_xirr_multiple_sign_changes_and_no_root_are_unavailable() -> None:
    ambiguous = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("200", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(
            DatedExternalFlow(
                Money.parse("-300", "EUR"),
                Instant.parse("2026-04-01T00:00:00Z"),
            ),
            DatedExternalFlow(
                Money.parse("250", "EUR"),
                Instant.parse("2026-09-01T00:00:00Z"),
            ),
        ),
        coverage=_coverage(),
    )
    no_root = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse(0, "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(),
    )
    assert ambiguous.value is None
    assert ambiguous.warnings[0].code == "xirr_ambiguous_roots"
    assert no_root.value is None
    assert no_root.warnings[0].code == "xirr_no_root"


def test_performance_metrics_are_coverage_and_quality_gated() -> None:
    partial = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("110", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(complete=False),
    )
    unreconciled = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("110", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(),
        ending_quality=QualityState.UNRECONCILED,
    )
    stale = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("110", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(),
        ending_quality=QualityState.STALE,
    )
    assert partial.value is None
    assert partial.quality_state is QualityState.PARTIAL
    assert unreconciled.value is None
    assert unreconciled.quality_state is QualityState.UNRECONCILED
    assert stale.value is not None
    assert stale.quality_state is QualityState.STALE


def test_modified_dietz_midperiod_deposit_and_withdrawal_are_hand_calculable() -> None:
    deposit = calculate_modified_dietz(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("220", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(DatedExternalFlow(Money.parse("100", "EUR"), MID),),
        coverage=_coverage(),
    )
    withdrawal = calculate_modified_dietz(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("60", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(DatedExternalFlow(Money.parse("-50", "EUR"), MID),),
        coverage=_coverage(),
    )
    assert deposit.value is not None
    assert deposit.value.value == Decimal("0.133333333333333333")
    assert withdrawal.value is not None
    assert withdrawal.value.value == Decimal("0.133333333333333333")


def test_modified_dietz_nonpositive_denominator_is_unavailable() -> None:
    result = calculate_modified_dietz(
        beginning_value=Money.parse(0, "EUR"),
        ending_value=Money.parse("10", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(),
    )
    assert result.value is None
    assert result.warnings[0].code == "modified_dietz_invalid_denominator"


def test_twr_links_complete_snapshot_subperiods_and_does_not_count_deposit_as_gain() -> None:
    result = calculate_time_weighted_return(
        subperiods=(
            SubperiodReturnInput(
                START,
                MID,
                Money.parse("100", "EUR"),
                Money.parse("110", "EUR"),
                Money.parse(0, "EUR"),
            ),
            SubperiodReturnInput(
                MID,
                END,
                Money.parse("110", "EUR"),
                Money.parse("176", "EUR"),
                Money.parse("55", "EUR"),
            ),
        ),
        coverage=_coverage(),
    )
    assert result.value is not None
    assert result.value.value == Decimal("0.210000000000000000")


def test_twr_missing_flow_or_valuation_gap_is_unavailable() -> None:
    missing_flow = calculate_time_weighted_return(
        subperiods=(
            SubperiodReturnInput(
                START,
                END,
                Money.parse("100", "EUR"),
                Money.parse("110", "EUR"),
                None,
            ),
        ),
        coverage=_coverage(),
    )
    gap_start = Instant.parse("2026-07-03T00:00:00Z")
    valuation_gap = calculate_time_weighted_return(
        subperiods=(
            SubperiodReturnInput(
                START,
                MID,
                Money.parse("100", "EUR"),
                Money.parse("110", "EUR"),
                Money.parse(0, "EUR"),
            ),
            SubperiodReturnInput(
                gap_start,
                END,
                Money.parse("110", "EUR"),
                Money.parse("120", "EUR"),
                Money.parse(0, "EUR"),
            ),
        ),
        coverage=_coverage(),
    )
    assert missing_flow.value is None
    assert "known_subperiod_external_flow" in missing_flow.missing_inputs
    assert valuation_gap.value is None
    assert "contiguous_subperiod_valuations" in valuation_gap.missing_inputs


def test_short_period_return_is_not_annualized_without_policy_override() -> None:
    short_end = Instant.parse("2026-01-31T00:00:00Z")
    result = calculate_modified_dietz(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("101", "EUR"),
        period_start=START,
        period_end=short_end,
        external_flows=(),
        coverage=Coverage(START, short_end, True),
    )
    assert result.value is not None
    assert result.annualized_value is None


def test_summary_propagates_worst_material_quality() -> None:
    fresh = calculate_xirr(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("110", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(),
    )
    partial = calculate_modified_dietz(
        beginning_value=Money.parse("100", "EUR"),
        ending_value=Money.parse("110", "EUR"),
        period_start=START,
        period_end=END,
        external_flows=(),
        coverage=_coverage(complete=False),
    )
    summary = build_performance_summary(
        xirr=fresh,
        time_weighted_return=None,
        modified_dietz=partial,
    )
    assert summary.quality_state is QualityState.PARTIAL
    assert summary.warnings == partial.warnings
