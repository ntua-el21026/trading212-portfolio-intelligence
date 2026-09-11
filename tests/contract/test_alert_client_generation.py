"""The 13 alert operations and finite predicates stay closed across generation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from trading212_api_contracts import alerts as wire
from trading212_api_contracts.typescript import render_alert_client
from trading212_domain import alerts as domain

pytestmark = pytest.mark.contract


def contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text()),
    )


def test_thirteen_alert_operations_generate_exact_bounded_client() -> None:
    value = contract()
    operations = {
        operation["operationId"]
        for methods in value["paths"].values()
        for operation in methods.values()
        if "alerts" in operation.get("tags", [])
    }
    assert operations == {
        "create_alert_rule",
        "create_alert_rule_version",
        "get_alert_rule",
        "list_alert_rules",
        "activate_alert_rule",
        "pause_alert_rule",
        "archive_alert_rule",
        "get_alert_event",
        "list_alert_events",
        "acknowledge_alert_event",
        "resolve_alert_event",
        "get_alert_summary",
        "list_notification_destinations",
    }
    rendered = render_alert_client(value)
    assert rendered == render_alert_client(copy.deepcopy(value))
    assert all(f"async {operation}(" in rendered for operation in operations)
    assert 'z.discriminatedUnion("metric"' in rendered
    assert 'z.discriminatedUnion("kind"' in rendered
    assert "z.unknown(" not in rendered and "z.any(" not in rendered
    assert "comparison_basis" not in rendered and "owner_id" not in rendered


@pytest.mark.parametrize(
    "name",
    [
        "AlertFamily",
        "AlertMetric",
        "AlertSeverity",
        "AlertLifecycle",
        "AlertComparison",
        "AlertQualityPolicy",
        "AlertSourceFamily",
        "AlertEvaluationOutcome",
        "AlertExecutionIntent",
        "AlertReason",
        "AlertOrigin",
        "AlertCanonicalFamily",
        "AlertInputRole",
    ],
)
def test_alert_finite_vocabulary_matches_shared_domain(name: str) -> None:
    assert set(get_args(getattr(wire, name))) == {value.value for value in getattr(domain, name)}


@pytest.mark.parametrize("change", ["path", "method", "operation", "added"])
def test_unknown_alert_operation_generation_fails_closed(change: str) -> None:
    value = contract()
    path = "/api/v1/alert-rules"
    if change == "path":
        value["paths"][path + "/arbitrary"] = value["paths"].pop(path)
    elif change == "method":
        value["paths"][path]["delete"] = value["paths"][path].pop("post")
    elif change == "operation":
        value["paths"][path]["post"]["operationId"] = "execute_rule"
    else:
        value["paths"][path]["delete"] = copy.deepcopy(value["paths"][path]["post"])
    with pytest.raises(ValueError):
        render_alert_client(value)
