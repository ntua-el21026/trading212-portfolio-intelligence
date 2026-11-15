"""Independent integer byte forecasts never substitute for real boundary proof."""

from __future__ import annotations

import pytest

from tests.integration.retained_xray_geometry import select_final_geometry

pytestmark = pytest.mark.unit

_MAX = 33_554_432


def _sample() -> tuple[dict[str, int], dict[str, int]]:
    # Independently chosen exact rates: result10,000/input1,000/combined12,000B.
    return (
        {
            "holdings": 512,
            "result_bytes": 5_120_000,
            "input_bytes": 512_000,
            "combined_bytes": 6_144_000,
        },
        {
            "holdings": 1024,
            "result_bytes": 10_240_000,
            "input_bytes": 1_024_000,
            "combined_bytes": 12_288_000,
        },
    )


def test_selection_balances_independently_calculated_byte_slack() -> None:
    first, second = _sample()
    actual = select_final_geometry(first, second)
    # Legal interval2797..3355. At3050 the smaller slack is3,045,568B;
    # adjacent3051 gives3,044,432B. The independent integer optimum is3050.
    assert actual["holdings"] == 3050
    assert actual["feasible_min_holdings"] == 2797
    assert actual["feasible_max_holdings"] == 3355
    assert actual["predicted_result_upper_fit_bytes"] == 30_500_000
    assert actual["predicted_input_upper_fit_bytes"] == 3_050_000
    assert actual["predicted_combined_lower_fit_bytes"] == 36_600_000
    assert actual["predicted_result_headroom_bytes"] == 3_054_432
    assert actual["predicted_combined_excess_bytes"] == 3_045_568
    assert "sizing_forecast_only" in str(actual["qualification"])
    assert (first, second) == _sample()


def test_balanced_equal_slack_tie_chooses_the_smaller_genuine_workload() -> None:
    first = {
        "holdings": 512,
        "result_bytes": 5_120_000,
        "input_bytes": 512,
        "combined_bytes": 7_178_864,
    }
    second = {
        "holdings": 1024,
        "result_bytes": 10_240_000,
        "input_bytes": 1024,
        "combined_bytes": 12_298_864,
    }
    # Exact balance is3252.5 holdings.3252 and3253 both have1,024,432B minimum
    # slack; choose3252 without changing any final actual-publication predicate.
    actual = select_final_geometry(first, second)
    assert actual["holdings"] == 3252
    assert actual["predicted_result_headroom_bytes"] == 1_034_432
    assert actual["predicted_combined_excess_bytes"] == 1_024_432


@pytest.mark.parametrize("record_index", (0, 1))
@pytest.mark.parametrize("field", ("result_bytes", "input_bytes"))
def test_actual_component_over_cap_stops_before_sizing(record_index: int, field: str) -> None:
    records = _sample()
    records[record_index][field] = _MAX + 1
    with pytest.raises(AssertionError):
        select_final_geometry(*records)


def test_absent_legal_interval_is_an_explicit_failure() -> None:
    first = {
        "holdings": 512,
        "result_bytes": 1_000_000,
        "input_bytes": 512,
        "combined_bytes": 31_000_000,
    }
    second = {
        "holdings": 1024,
        "result_bytes": 32_000_000,
        "input_bytes": 1024,
        "combined_bytes": 32_100_000,
    }
    with pytest.raises(AssertionError, match="No legal forecast interval"):
        select_final_geometry(first, second)


def test_existing_nine_thousand_holding_bound_clamps_the_legal_optimum() -> None:
    first = {
        "holdings": 512,
        "result_bytes": 512_000,
        "input_bytes": 51_200,
        "combined_bytes": 2_304_000,
    }
    second = {
        "holdings": 1024,
        "result_bytes": 1_024_000,
        "input_bytes": 102_400,
        "combined_bytes": 4_608_000,
    }
    actual = select_final_geometry(first, second)
    assert actual["holdings"] == 9000
    assert actual["feasible_max_holdings"] == 9000
    assert actual["predicted_result_upper_fit_bytes"] == 9_000_000
    assert actual["predicted_combined_lower_fit_bytes"] == 40_500_000


def test_no_geometry_inside_existing_holding_bound_stops() -> None:
    first = {
        "holdings": 512,
        "result_bytes": 512_000,
        "input_bytes": 51_200,
        "combined_bytes": 1_536_000,
    }
    second = {
        "holdings": 1024,
        "result_bytes": 1_024_000,
        "input_bytes": 102_400,
        "combined_bytes": 3_072_000,
    }
    with pytest.raises(AssertionError, match="No legal forecast interval"):
        select_final_geometry(first, second)


def test_input_component_capacity_limits_the_predicted_interval() -> None:
    first = {
        "holdings": 512,
        "result_bytes": 512,
        "input_bytes": 30_000_000,
        "combined_bytes": 30_000_512,
    }
    second = {
        "holdings": 1024,
        "result_bytes": 1024,
        "input_bytes": 31_000_000,
        "combined_bytes": 31_001_024,
    }
    actual = select_final_geometry(first, second)
    assert actual["holdings"] == 2331
    assert actual["feasible_max_holdings"] == 2331
    assert actual["predicted_input_upper_fit_bytes"] == 33_553_878
    assert actual["predicted_combined_lower_fit_bytes"] == 33_554_902


@pytest.mark.parametrize("field", ("result_bytes", "input_bytes", "combined_bytes"))
def test_nonincreasing_measured_growth_does_not_trigger_another_publication(field: str) -> None:
    first, second = _sample()
    second[field] = first[field]
    with pytest.raises(AssertionError):
        select_final_geometry(first, second)
