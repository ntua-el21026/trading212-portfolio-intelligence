"""Byte-derived fixture sizing; only the next real publication supplies proof."""

from __future__ import annotations


def select_final_geometry(first: dict[str, int], second: dict[str, int]) -> dict[str, int | str]:
    maximum, maximum_holdings = 33_554_432, 9000
    assert first["holdings"] == 512 and second["holdings"] == 1024
    for record in (first, second):
        for field in ("holdings", "result_bytes", "combined_bytes", "input_bytes"):
            assert type(record[field]) is int and record[field] > 0
        assert record["result_bytes"] <= maximum and record["input_bytes"] <= maximum
        assert record["combined_bytes"] >= record["result_bytes"] + record["input_bytes"]
    assert second["combined_bytes"] <= maximum
    span = second["holdings"] - first["holdings"]
    result_delta = second["result_bytes"] - first["result_bytes"]
    combined_delta = second["combined_bytes"] - first["combined_bytes"]
    input_delta = second["input_bytes"] - first["input_bytes"]
    assert result_delta > 0 and combined_delta > 0 and input_delta > 0
    # Upper component costs and lower combined cost are conservative within the
    # observed linear fit. Revision framing still needs actual publication proof.
    result_step = (result_delta + span - 1) // span
    input_step = (input_delta + span - 1) // span
    combined_step = combined_delta // span
    assert combined_step > 0
    required_delta = max(1, (maximum - second["combined_bytes"]) // combined_step + 1)
    allowed_delta = min(
        (maximum - second["result_bytes"]) // result_step,
        (maximum - second["input_bytes"]) // input_step,
        maximum_holdings - second["holdings"],
    )
    assert required_delta <= allowed_delta, (
        "No legal forecast interval; stop before another publication."
    )
    # Maximize the smaller predicted result headroom and combined-cap excess.
    balance = (2 * maximum - second["result_bytes"] - second["combined_bytes"]) // (
        result_step + combined_step
    )
    candidates = {
        max(required_delta, min(allowed_delta, balance)),
        max(required_delta, min(allowed_delta, balance + 1)),
    }

    def slack(delta: int) -> int:
        return min(
            maximum - second["result_bytes"] - delta * result_step,
            second["combined_bytes"] + delta * combined_step - maximum,
        )

    delta = max(candidates, key=lambda value: (slack(value), -value))
    count = second["holdings"] + delta
    assert 1024 < count <= maximum_holdings
    assert count + 1 <= 10_000
    assert 512 + 1024 + count <= 100_000
    predicted_result = second["result_bytes"] + delta * result_step
    predicted_input = second["input_bytes"] + delta * input_step
    predicted_combined = second["combined_bytes"] + delta * combined_step
    assert predicted_result <= maximum and predicted_input <= maximum < predicted_combined
    return {
        "holdings": count,
        "feasible_min_holdings": 1024 + required_delta,
        "feasible_max_holdings": 1024 + allowed_delta,
        "result_bytes_per_extra_holding_upper_fit": result_step,
        "input_bytes_per_extra_holding_upper_fit": input_step,
        "combined_bytes_per_extra_holding_lower_fit": combined_step,
        "predicted_result_upper_fit_bytes": predicted_result,
        "predicted_input_upper_fit_bytes": predicted_input,
        "predicted_combined_lower_fit_bytes": predicted_combined,
        "predicted_result_headroom_bytes": maximum - predicted_result,
        "predicted_combined_excess_bytes": predicted_combined - maximum,
        "qualification": (
            "sizing_forecast_only; final normal publication and unchanged assertions decide"
        ),
    }
