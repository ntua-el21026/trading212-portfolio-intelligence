"""Independent malformed wire examples for projection inputs and retained public pages."""

from copy import deepcopy
from decimal import Context, Inexact, Rounded, localcontext
from typing import Any

import pytest
from pydantic import ValidationError
from trading212_api_contracts.projection_inputs import (
    AssumptionVersionContent,
    CreateProjectionRunRequest,
    ProjectionDatedSchedule,
)
from trading212_api_contracts.projection_results import (
    ProjectionGoalEstimateView,
    ProjectionPointPage,
    ProjectionResultPage,
)
from trading212_api_contracts.projections import (
    GoalAnalysisResponse,
    ProjectionOperationalRunResponse,
    ProjectionRunResponse,
)

pytestmark = pytest.mark.unit
ACCOUNT = "00000000-0000-0000-0000-000000000001"
ASSUMPTION = "00000000-0000-0000-0000-000000000002"
RUN = "00000000-0000-0000-0000-000000000003"
RESULT = "00000000-0000-0000-0000-000000000004"
GOAL = "00000000-0000-0000-0000-000000000005"


def money(amount: str = "0") -> dict[str, str]:
    return {"amount": amount, "currency": "EUR"}


def quantiles(amount: str = "0") -> dict[str, Any]:
    return {
        "probabilities": ["0.05", "0.25", "0.5", "0.75", "0.95"],
        "values": [money(amount) for _ in range(5)],
    }


def assumptions() -> dict[str, Any]:
    return {
        "assets": [
            {"key": "cash", "annual_mean_log_return": "0", "annual_volatility": "0", "weight": "1"}
        ],
        "correlation": [["1"]],
        "reporting_currency": "EUR",
    }


def request() -> dict[str, Any]:
    return {
        "assumption_version_id": ASSUMPTION,
        "initial_basis": {
            "kind": "modeled_value",
            "modeled_value": money("100"),
            "modeled_anchor_date": "2025-01-31",
        },
        "schedule": {"base_monthly": money()},
        "seed": 0,
        "months": 1,
        "paths": 2,
        "retained_months": [0, 1],
        "allocation": [{"key": "cash", "weight": "1"}],
    }


def result_page() -> dict[str, Any]:
    selection = request()
    selection["initial"] = selection.pop("initial_basis")
    selection["account_id"] = ACCOUNT
    context: dict[str, Any] = {
        "account_id": ACCOUNT,
        "run_id": RUN,
        "result_id": RESULT,
        "capture_digest": "a" * 64,
        "numerical_input_digest": "b" * 64,
        "saved_result_digest": "c" * 64,
        "assumption_version_digest": "d" * 64,
        "goal_version_digest": None,
        "selection": selection,
        "assumptions": assumptions(),
        "anchor_date": "2025-01-31",
        "terminal_date": "2025-02-28",
        "snapshot_valuation_at": None,
        "source_cutoff_at": None,
        "calculated_at": "2026-09-15T12:00:00Z",
        "reporting_currency": "EUR",
        "quality": "estimated",
        "source_evidence": {"items": [], "omitted_count": 0},
        "warnings": {"items": ["sampling_uncertainty"], "omitted_count": 0},
        "numerical_zero_pivots": [],
    }
    distributions = [
        {
            "month": month,
            "on": on,
            "nominal_mean": money("100"),
            "real_mean": money("100"),
            "nominal": quantiles("100"),
            "real": quantiles("100"),
            "funding_failed_paths": 0,
        }
        for month, on in ((0, "2025-01-31"), (1, "2025-02-28"))
    ]
    histogram = {
        "observed_minimum": money("100"),
        "observed_maximum": money("100"),
        "bins": [
            {"lower": money("100"), "upper": money("100"), "upper_inclusive": True, "count": 2}
        ],
    }
    flows: dict[str, Any] = {
        name: {"mean": money(), "quantiles": quantiles()}
        for name in (
            "contributions",
            "withdrawals_requested",
            "withdrawals_funded",
            "unpaid_withdrawals",
            "investment_effect",
            "fees",
            "tax_drag",
        )
    }
    flows.update(funding_failed_paths=0, unpaid_positive_below_quantum_paths=0)
    variant = {
        "variant": "baseline",
        "distributions": distributions,
        "nominal_histogram": histogram,
        "real_histogram": deepcopy(histogram),
        "cash_flows": flows,
        "goal": None,
    }
    point: dict[str, Any] = {
        name: money()
        for name in (
            "contributions",
            "withdrawals_requested",
            "withdrawals_funded",
            "unpaid_withdrawals",
            "investment_effect",
            "fees",
            "tax_drag",
            "wealth_residual",
            "allocation_residual",
            "withdrawal_residual",
        )
    }
    point.update(
        month=0,
        nominal=money("100"),
        real=money("100"),
        assets=[{"key": "cash", "value": money("100")}],
        funding_failed=False,
        unpaid_positive_below_quantum=False,
    )
    row = {
        "ordinal": 0,
        "variant": "baseline",
        "path_index": 0,
        "point_index": 0,
        "path_point_count": 2,
        "first_unpaid_month": None,
        "on": "2025-01-31",
        "point": point,
    }
    return {
        "context": context,
        "variants": [variant],
        "points": {
            "items": [row],
            "point_limit": 1,
            "next_cursor": "signed_cursor",
            "total": 4,
            "start_ordinal": 0,
        },
        "content_digest": "e" * 64,
    }


def operational() -> dict[str, Any]:
    return {
        "id": RUN,
        "account_id": ACCOUNT,
        "assumption_version_id": ASSUMPTION,
        "goal_version_id": None,
        "job_id": RESULT,
        "capture_digest": "a" * 64,
        "numerical_input_digest": "b" * 64,
        "state": "queued",
        "result_availability": "pending",
        "created_at": "2026-09-15T12:00:00Z",
        "expires_at": "2026-09-16T12:00:00Z",
        "completed_at": None,
        "failure_code": None,
        "result": None,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", True),
        ("seed", 2**32),
        ("paths", 0),
        ("months", 601),
        ("owner_id", ACCOUNT),
        ("retained_months", [0]),
        ("retained_months", [0, 1, 1]),
    ],
)
def test_request_bounds_reject_implicit_or_hostile_inputs(field: str, value: Any) -> None:
    raw = request()
    raw[field] = value
    with pytest.raises(ValidationError):
        CreateProjectionRunRequest.model_validate(raw)


def test_observed_basis_rejects_client_valuation_and_model_requires_date() -> None:
    raw = request()
    raw["initial_basis"] = {
        "kind": "observed_snapshot",
        "snapshot_id": RESULT,
        "modeled_value": money("999"),
    }
    with pytest.raises(ValidationError):
        CreateProjectionRunRequest.model_validate(raw)
    raw["initial_basis"] = {"kind": "modeled_value", "modeled_value": money("999")}
    with pytest.raises(ValidationError):
        CreateProjectionRunRequest.model_validate(raw)


@pytest.mark.parametrize("bad", [0.1, 1, True, "1e-8", "0.0000000000000000001", "-0.1"])
def test_money_wire_never_coerces_float_exponent_or_negative_value(bad: Any) -> None:
    raw = request()
    raw["schedule"]["base_monthly"]["amount"] = bad
    with pytest.raises(ValidationError):
        CreateProjectionRunRequest.model_validate(raw)


def test_assets_and_axes_canonicalize_together_under_hostile_context() -> None:
    raw = assumptions()
    raw["assets"] = [
        {"key": key, "annual_mean_log_return": "0", "annual_volatility": "0", "weight": weight}
        for key, weight in (("z", "0.2"), ("a", "0.3"), ("b", "0.5"))
    ]
    raw["correlation"] = [["1", "0.1", "0.2"], ["0.1", "1", "0.3"], ["0.2", "0.3", "1"]]
    with localcontext(Context(prec=2, traps=[Inexact, Rounded])):
        parsed = AssumptionVersionContent.model_validate(raw)
    assert [asset.key for asset in parsed.assets] == ["a", "b", "z"]
    assert parsed.correlation == [["1", "0.3", "0.1"], ["0.3", "1", "0.2"], ["0.1", "0.2", "1"]]


def test_combined_schedule_limit_and_exact_entry_identity() -> None:
    entries = [
        {"key": f"lump-{index}", "on": "2025-01-31", "kind": "lump_sum", "value": money("1")}
        for index in range(128)
    ]
    raw: dict[str, Any] = {
        "base_monthly": money(),
        "entries": entries,
        "paused_dates": ["2025-01-31"],
    }
    with pytest.raises(ValidationError):
        ProjectionDatedSchedule.model_validate(raw)
    raw["paused_dates"] = []
    entries[1]["key"] = entries[0]["key"]
    with pytest.raises(ValidationError):
        ProjectionDatedSchedule.model_validate(raw)


def test_sensitivity_work_and_currency_are_not_silently_reduced() -> None:
    raw = request()
    raw.update(
        months=600,
        paths=600,
        retained_months=[0, 600],
        sensitivity={"contribution_delta": money(), "annual_mean_log_delta": "0.01"},
    )
    with pytest.raises(ValidationError):
        CreateProjectionRunRequest.model_validate(raw)
    raw = request()
    raw["schedule"]["base_monthly"]["currency"] = "USD"
    with pytest.raises(ValidationError):
        CreateProjectionRunRequest.model_validate(raw)


def test_complete_saved_point_has_explicit_identity_and_funding_financials() -> None:
    with localcontext(Context(prec=2, traps=[Inexact, Rounded])):
        page = ProjectionResultPage.model_validate(result_page())
    row = page.points.items[0]
    assert row.point.nominal.amount == "100" and row.point.nominal.currency == "EUR"
    assert (row.variant, row.path_index, row.point_index, row.path_point_count) == (
        "baseline",
        0,
        0,
        2,
    )
    assert page.points.next_cursor and page.points.total == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("ordinal", 1),
        ("variant", "mean_log_delta"),
        ("path_index", 1),
        ("point_index", 1),
        ("path_point_count", 3),
        ("on", "2025-02-01"),
    ],
)
def test_foreign_or_mislabeled_retained_point_rejects(field: str, value: Any) -> None:
    raw = result_page()
    raw["points"]["items"][0][field] = value
    with pytest.raises(ValidationError):
        ProjectionResultPage.model_validate(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("next_cursor", None),
        ("total", 0),
        ("start_ordinal", 1),
        ("items", []),
        ("point_limit", True),
    ],
)
def test_incomplete_page_never_becomes_complete_result(field: str, value: Any) -> None:
    raw = result_page()["points"]
    raw[field] = value
    with pytest.raises(ValidationError):
        ProjectionPointPage.model_validate(raw)


def test_dropped_funding_flag_changed_currency_and_false_residual_reject() -> None:
    for change in ("funding", "currency", "residual"):
        raw = result_page()
        point = raw["points"]["items"][0]["point"]
        if change == "funding":
            point["unpaid_withdrawals"] = money("1")
        elif change == "currency":
            point["real"]["currency"] = "USD"
        else:
            point["allocation_residual"] = money("0.1")
        with pytest.raises(ValidationError):
            ProjectionResultPage.model_validate(raw)


def test_fresh_estimate_or_incomplete_histogram_rejects() -> None:
    raw = result_page()
    raw["context"]["quality"] = "fresh"
    with pytest.raises(ValidationError):
        ProjectionResultPage.model_validate(raw)
    raw = result_page()
    raw["variants"][0]["nominal_histogram"]["bins"][0]["count"] = 1
    with pytest.raises(ValidationError):
        ProjectionResultPage.model_validate(raw)


def test_operational_state_and_private_result_are_separate() -> None:
    raw = operational()
    raw["failure_code"] = "lease_expired"
    assert ProjectionOperationalRunResponse.model_validate(raw).state == "queued"
    raw.update(
        state="succeeded",
        completed_at="2026-09-15T12:01:00Z",
        failure_code=None,
        result_availability="available",
        result=result_page(),
    )
    assert ProjectionRunResponse.model_validate(raw).result is not None
    with pytest.raises(ValidationError):
        ProjectionOperationalRunResponse.model_validate(raw)
    raw["capture_digest"] = "f" * 64
    with pytest.raises(ValidationError):
        ProjectionRunResponse.model_validate(raw)


def test_explicit_no_goal_and_expired_result_do_not_fabricate_finance() -> None:
    raw: dict[str, Any] = {
        "account_id": ACCOUNT,
        "run_id": RUN,
        "goal_version_id": None,
        "state": "succeeded",
        "result_availability": "available",
        "availability": "unavailable",
        "reason": "no_goal_pinned",
        "context": None,
        "variants": [],
        "content_digest": "e" * 64,
    }
    assert GoalAnalysisResponse.model_validate(raw).context is None
    raw.update(goal_version_id=GOAL, result_availability="expired", reason="run_expired")
    assert GoalAnalysisResponse.model_validate(raw).state == "succeeded"
    raw["context"] = result_page()["context"]
    with pytest.raises(ValidationError):
        GoalAnalysisResponse.model_validate(raw)


def test_goal_probability_requires_counts_and_never_auto_accepts() -> None:
    raw: dict[str, Any] = {
        "goal_version_id": GOAL,
        "basis": "nominal",
        "target": money("100"),
        "paths": 2,
        "successes": 1,
        "probability": "0.5",
        "interval_low": "0.09",
        "interval_high": "0.91",
        "probability_objective": "0.4",
        "objective_met": True,
        "mean_shortfall": money("5"),
        "shortfalls": quantiles(),
        "funding_failed_paths": 0,
    }
    assert ProjectionGoalEstimateView.model_validate(raw).automatic_goal_acceptance is False
    for field, value in (
        ("probability", "0.6"),
        ("objective_met", False),
        ("automatic_goal_acceptance", True),
        ("funding_failed_paths", 2),
    ):
        malformed = deepcopy(raw)
        malformed[field] = value
        with pytest.raises(ValidationError):
            ProjectionGoalEstimateView.model_validate(malformed)


def test_estimated_context_cannot_upgrade_partial_source_quality() -> None:
    raw = result_page()
    raw["context"]["source_evidence"] = {
        "items": [
            {
                "role": "calibration",
                "subject_id": ASSUMPTION,
                "content_digest": "f" * 64,
                "quality": "partial",
                "source_reference_ids": {"items": [], "omitted_count": 0},
            }
        ],
        "omitted_count": 0,
    }
    with pytest.raises(ValidationError):
        ProjectionResultPage.model_validate(raw)
    raw["context"]["quality"] = "partial"
    assert ProjectionResultPage.model_validate(raw).context.quality == "partial"
