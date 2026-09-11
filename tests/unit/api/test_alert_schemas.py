"""All fixed alert predicates reject incompatible types and unrelated capabilities."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError
from trading212_api_contracts import alerts as wire

IDENTIFIER = "d2cf0661-0f22-4b4f-8c02-a334c4b0e442"
SECOND = "3d95df94-adca-41ae-bcb6-652d04b9f311"
DECIMAL = {"comparison": "gte", "threshold": "0.100000000000000001"}
INTEGER = {"comparison": "gt", "threshold": 2}
BOOLEAN = {"comparison": "eq", "threshold": True}
PREDICATES: tuple[dict[str, Any], ...] = (
    {
        "family": "target_drift",
        "metric": "portfolio_l1_drift",
        **DECIMAL,
        "target_version_id": IDENTIFIER,
        "frontier_depth": 1,
    },
    {
        "family": "group_drift",
        "metric": "group_absolute_drift",
        **DECIMAL,
        "target_version_id": IDENTIFIER,
        "group_node_id": SECOND,
    },
    {
        "family": "holding_drift",
        "metric": "holding_absolute_drift",
        **DECIMAL,
        "target_version_id": IDENTIFIER,
        "holding_id": SECOND,
    },
    {"family": "concentration", "metric": "direct_max_weight", **DECIMAL, "include_cash": False},
    {
        "family": "concentration",
        "metric": "direct_top_n_weight",
        **DECIMAL,
        "include_cash": True,
        "top_n": 17,
    },
    {"family": "concentration", "metric": "direct_hhi", **DECIMAL, "include_cash": False},
    {
        "family": "effective_company_concentration",
        "metric": "effective_entity_weight",
        **DECIMAL,
        "entity_id": IDENTIFIER,
    },
    {
        "family": "effective_company_concentration",
        "metric": "effective_top_n_weight",
        **DECIMAL,
        "top_n": 49,
    },
    {"family": "effective_company_concentration", "metric": "effective_hhi", **DECIMAL},
    {
        "family": "etf_overlap",
        "metric": "etf_pair_overlap",
        **DECIMAL,
        "left_fund_id": IDENTIFIER,
        "right_fund_id": SECOND,
    },
    {"family": "etf_overlap", "metric": "portfolio_duplicated_exposure", **DECIMAL},
    {"family": "cash_threshold", "metric": "cash_amount", **DECIMAL, "currency": "EUR"},
    {"family": "cash_threshold", "metric": "cash_weight", **DECIMAL},
    {
        "family": "stale_data",
        "metric": "source_age_seconds",
        **INTEGER,
        "source_family": "valuation",
    },
    {
        "family": "stale_data",
        "metric": "source_missing_sessions",
        **INTEGER,
        "source_family": "price",
        "source_id": IDENTIFIER,
        "calendar_version_id": SECOND,
    },
    {"family": "missing_coverage", "metric": "missing_count", **INTEGER, "domain": "fx"},
    {
        "family": "missing_coverage",
        "metric": "missing_fraction",
        **DECIMAL,
        "domain": "constituent",
    },
    {
        "family": "reconciliation_failure",
        "metric": "reconciliation_failed",
        **BOOLEAN,
        "discrepancy_severity": "error",
    },
    {"family": "reconciliation_failure", "metric": "reconciliation_discrepancy_count", **INTEGER},
    {
        "family": "provider_failure",
        "metric": "provider_failed",
        **BOOLEAN,
        "provider_id": IDENTIFIER,
        "window_seconds": 300,
    },
    {
        "family": "provider_failure",
        "metric": "provider_consecutive_failures",
        **INTEGER,
        "provider_id": IDENTIFIER,
        "window_seconds": 2678400,
    },
    {
        "family": "failed_refresh",
        "metric": "refresh_failed",
        "capability_family": "portfolio_positions",
    },
    {
        "family": "dividend_received",
        "metric": "positive_dividend",
        "minimum_net_amount": "0.01",
        "currency": "EUR",
    },
    {
        "family": "unusual_activity",
        "metric": "absolute_external_flow_amount",
        **DECIMAL,
        "window_seconds": 300,
        "activity_kind": "deposit",
        "currency": "EUR",
    },
    {
        "family": "unusual_activity",
        "metric": "activity_count",
        **INTEGER,
        "window_seconds": 300,
        "activity_kind": "buy",
    },
    {"family": "unusual_activity", "metric": "unclassified_activity", "window_seconds": 300},
    {
        "family": "report_outcome",
        "metric": "report_terminal",
        "report_type": "annual",
        "outcome": "either",
    },
)


def definition(predicate: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "Synthetic monitoring rule",
        "predicate": predicate,
        "severity": "warning",
        "schedule": {
            "kind": "interval",
            "anchor_at": "2026-09-10T12:00:00Z",
            "interval_seconds": 300,
        },
        "destination_ids": [],
    }


@pytest.mark.parametrize("predicate", PREDICATES, ids=lambda value: value["metric"])
def test_every_fixed_metric_has_a_closed_typed_wire_branch(predicate: dict[str, Any]) -> None:
    result = wire.CreateAlertRuleRequest.model_validate(
        {"account_id": IDENTIFIER, "definition": definition(predicate)}
    )
    assert result.definition.predicate.metric == predicate["metric"]
    assert result.definition.predicate.family == predicate["family"]
    if "threshold" in predicate:
        assert result.definition.predicate.model_dump()["threshold"] == predicate["threshold"]
    for extra in (
        {"expression": "synthetic-private-value"},
        {"owner_id": SECOND},
        {"path": "/private"},
    ):
        with pytest.raises(ValidationError) as error:
            wire.CreateAlertRuleRequest.model_validate(
                {"account_id": IDENTIFIER, "definition": definition({**predicate, **extra})}
            )
        assert "synthetic-private-value" not in str(error.value)
        assert "expression" not in str(error.value)


def test_exact_twenty_seven_metrics_and_fifteen_families_are_covered() -> None:
    assert len(PREDICATES) == 27
    assert {item["metric"] for item in PREDICATES} == set(get_args(wire.AlertMetric))
    assert len({item["family"] for item in PREDICATES}) == 15
    assert {item["family"] for item in PREDICATES} == set(get_args(wire.AlertFamily))


@pytest.mark.parametrize(
    "index,change",
    [
        (0, {"threshold": 0.1}),
        (0, {"threshold": "1e-3"}),
        (0, {"threshold": "0.0000000000000000001"}),
        (0, {"frontier_depth": True}),
        (0, {"frontier_depth": 9}),
        (3, {"top_n": 2}),
        (3, {"include_cash": "false"}),
        (4, {"top_n": 0}),
        (4, {"top_n": 51}),
        (4, {"top_n": True}),
        (7, {"entity_id": IDENTIFIER}),
        (8, {"family": "concentration"}),
        (9, {"right_fund_id": IDENTIFIER}),
        (10, {"left_fund_id": IDENTIFIER}),
        (11, {"currency": "eur"}),
        (12, {"currency": "EUR"}),
        (13, {"threshold": True}),
        (13, {"threshold": "2"}),
        (13, {"threshold": -1}),
        (13, {"source_family": "arbitrary"}),
        (13, {"calendar_version_id": SECOND}),
        (15, {"domain": "broker_url"}),
        (17, {"comparison": "gt"}),
        (17, {"threshold": 1}),
        (19, {"window_seconds": 299}),
        (20, {"window_seconds": 2678401}),
        (21, {"threshold": True}),
        (21, {"capability_family": "place_order"}),
        (22, {"minimum_net_amount": "0"}),
        (22, {"currency": None}),
        (23, {"activity_kind": "user_expression"}),
        (24, {"currency": "EUR"}),
        (25, {"comparison": "eq"}),
        (26, {"outcome": "running"}),
        (26, {"threshold": True}),
    ],
)
def test_metric_mismatches_and_ambiguous_numeric_types_are_rejected(
    index: int, change: dict[str, Any]
) -> None:
    adapter: TypeAdapter[wire.AlertPredicate] = TypeAdapter(wire.AlertPredicate)
    with pytest.raises(ValidationError):
        adapter.validate_python({**PREDICATES[index], **change})


def test_pair_order_is_canonical_and_schedule_fields_cannot_cross_variants() -> None:
    pair = wire.AlertPairOverlapPredicate.model_validate(PREDICATES[9])
    assert (pair.left_fund_id, pair.right_fund_id) == tuple(sorted((IDENTIFIER, SECOND)))
    for schedule in (
        {"kind": "daily_utc", "minute_utc": True},
        {"kind": "daily_utc", "minute_utc": 1440},
        {"kind": "daily_utc", "minute_utc": 0, "anchor_at": "2026-09-10T12:00:00Z"},
        {"kind": "interval", "anchor_at": "2026-09-10T12:00:00", "interval_seconds": 300},
        {"kind": "interval", "anchor_at": "2026-09-10T12:00:00Z", "interval_seconds": 86401},
    ):
        with pytest.raises(ValidationError):
            wire.AlertRuleDefinition.model_validate(
                {**definition(PREDICATES[0]), "schedule": schedule}
            )


def test_empty_external_destinations_remain_valid_but_duplicates_and_credentials_fail() -> None:
    body = definition(PREDICATES[0])
    assert wire.AlertRuleDefinition.model_validate(body).destination_ids == []
    for change in (
        {"destination_ids": [IDENTIFIER, IDENTIFIER]},
        {"webhook_url": "https://example.invalid"},
        {"cooldown_seconds": True},
        {"cooldown_seconds": 604801},
    ):
        with pytest.raises(ValidationError):
            wire.AlertRuleDefinition.model_validate({**body, **change})


def test_mcp_summary_requires_window_and_cannot_acquire_http_top_or_command_fields() -> None:
    payload = {
        "account_id": IDENTIFIER,
        "start_date": "2026-09-01",
        "end_date": "2026-09-10",
        "source_cutoff_at": "2026-09-10T12:00:00Z",
    }
    parsed = wire.McpAlertSummaryRequest.model_validate(payload)
    assert parsed.limit == 25 and parsed.state == "open"
    assert set(wire.McpAlertSummaryRequest.model_json_schema()["required"]) == set(payload)
    for change in (
        {"top_n": 25},
        {"rule_id": SECOND},
        {"destination": SECOND},
        {"limit": True},
        {"limit": "25"},
        {"end_date": "2026-08-01"},
    ):
        with pytest.raises(ValidationError):
            wire.McpAlertSummaryRequest.model_validate({**payload, **change})
    with pytest.raises(ValidationError):
        wire.AlertEventListQuery.model_validate(
            {"account_id": IDENTIFIER, "start_date": "2026-09-01"}
        )
