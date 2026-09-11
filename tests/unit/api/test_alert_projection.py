"""Public projections preserve typed rules/results while withholding private operands."""

from dataclasses import replace

import pytest
from pydantic import ValidationError
from trading212_api.alert_schemas import alert_definition
from trading212_api_contracts import alerts as wire
from trading212_application import alerts as app
from trading212_application.alert_projection import alert_content
from trading212_domain import alerts as domain

from tests.unit.analytics.alert_factories import capture
from tests.unit.api.alert_factories import evaluation, rule


@pytest.mark.parametrize("metric", list(domain.AlertMetric))
def test_every_native_definition_round_trips_the_closed_public_predicate(
    metric: domain.AlertMetric,
) -> None:
    definition = capture(metric).version.definition
    parsed = wire.AlertRuleDefinition.model_validate(alert_content(definition))
    assert alert_definition(parsed) == definition
    assert "comparison_basis" not in parsed.model_dump_json()


def test_evaluation_retains_rule_hash_context_and_safe_expiry_identity() -> None:
    value = evaluation()
    retained = wire.AlertEvaluationView.model_validate(alert_content(value))
    assert retained.result is not None and retained.definition is not None
    assert retained.rule_content_digest == value.rule_content_digest
    assert retained.result.observation is not None
    assert retained.result.observation.context_key == retained.result.contexts[0].key
    expired = replace(
        value,
        result=None,
        definition=None,
        source_references=(),
        canonical_bindings=(),
        licenses=(),
        reproducibility=app.AlertReproducibility.EXPIRED,
    )
    safe = wire.AlertEvaluationView.model_validate(alert_content(expired))
    assert (
        safe.result is None
        and safe.definition is None
        and safe.input_digest == retained.input_digest
    )
    with pytest.raises(ValidationError):
        wire.AlertEvaluationView.model_validate({**safe.model_dump(), "result": retained.result})


def test_rule_version_history_rejects_another_rule_or_account() -> None:
    value = rule()
    content = wire.AlertRuleDetail.model_validate(alert_content(value)).model_dump()
    content["version_page"]["items"][0]["account_id"] = str(value.id)
    with pytest.raises(ValidationError):
        wire.AlertRuleDetail.model_validate(content)


@pytest.mark.parametrize("mutation", ["input", "context", "source", "decision"])
def test_invalid_retained_result_metadata_fails_before_public_serialization(mutation: str) -> None:
    content = wire.AlertEvaluationView.model_validate(alert_content(evaluation())).model_dump()
    if mutation == "input":
        content["result"]["input_digest"] = "f" * 64
    elif mutation == "context":
        content["result"]["observation"]["context_key"] = "unknown_context"
    elif mutation == "source":
        content["result"]["contexts"][0]["source_reference_keys"] = ["unknown_source"]
    else:
        content["result"]["decision"] = False
    with pytest.raises(ValidationError):
        wire.AlertEvaluationView.model_validate(content)
