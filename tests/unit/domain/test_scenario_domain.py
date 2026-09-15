"""Closed owner assumptions and complete sensitivity membership invariants."""

from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.scenario import (
    ScenarioExclusion,
    ScenarioInstrumentSelector,
    ScenarioPriceShock,
    ScenarioReason,
    scenario_exclusion_key,
    scenario_rule_key,
)
from trading212_domain.scenario_result import ScenarioMoneyMetric, ScenarioRatioMetric
from trading212_domain.scenario_serialization import (
    scenario_definition_bytes,
    scenario_definition_digest,
)
from trading212_domain.scenario_sources import (
    ScenarioSensitivityCapture,
    ScenarioSensitivityObservation,
)
from trading212_domain.sources import ObservationState

from tests.unit.analytics.xray_factories import uid
from tests.unit.domain.scenario_factories import definition, sensitivity_capture


def test_rule_order_does_not_change_definition_identity_but_economic_size_does() -> None:
    first = ScenarioPriceShock(
        selector=ScenarioInstrumentSelector(instrument_id=uid(10)), size=Decimal("-0.2")
    )
    second = ScenarioPriceShock(
        selector=ScenarioInstrumentSelector(instrument_id=uid(11)), size=Decimal("0.1")
    )
    exclusions = (
        ScenarioExclusion(selector=ScenarioInstrumentSelector(instrument_id=uid(12))),
        ScenarioExclusion(selector=ScenarioInstrumentSelector(instrument_id=uid(13))),
    )
    left = replace(definition(), shocks=(first, second), exclusions=exclusions)
    right = replace(definition(), shocks=(second, first), exclusions=tuple(reversed(exclusions)))
    assert scenario_definition_bytes(left) == scenario_definition_bytes(right)
    assert scenario_definition_digest(left) == scenario_definition_digest(right)
    assert scenario_rule_key(first) != scenario_rule_key(replace(first, size=Decimal("-0.1")))
    assert scenario_exclusion_key(exclusions[0]) != scenario_exclusion_key(exclusions[1])


def test_duplicate_selector_rejected_even_with_different_sizes() -> None:
    shock = ScenarioPriceShock(
        selector=ScenarioInstrumentSelector(instrument_id=uid(10)), size=Decimal("-0.2")
    )
    with pytest.raises(DomainError):
        replace(definition(), shocks=(shock, replace(shock, size=Decimal("0.2"))))
    exclusion = ScenarioExclusion(selector=shock.selector)
    with pytest.raises(DomainError):
        replace(definition(), exclusions=(exclusion, exclusion))


@pytest.mark.parametrize(
    "size", [Decimal("-1.000000000000000001"), Decimal("5.000000000000000001"), Decimal("NaN")]
)
def test_price_shock_bounds_are_not_clipped(size: Decimal) -> None:
    with pytest.raises(DomainError):
        ScenarioPriceShock(selector=ScenarioInstrumentSelector(instrument_id=uid(10)), size=size)


def test_available_source_requires_exact_membership_and_transformation_proof() -> None:
    capture = sensitivity_capture()
    with pytest.raises(DomainError):
        replace(
            capture, memberships=(replace(capture.memberships[0], observation_digest="f" * 64),)
        )
    with pytest.raises(DomainError):
        replace(capture, evidence=())
    with pytest.raises(DomainError):
        replace(capture, evidence=(replace(capture.evidence[0], transformation="unsupported"),))
    with pytest.raises(DomainError):
        replace(capture, licenses=())
    with pytest.raises(DomainError):
        replace(capture.observations[0], response_basis="fx_inclusive")
    missing = replace(
        capture.observations[0],
        state=ObservationState.MISSING,
        coefficient=None,
        reason=ScenarioReason.MISSING_SENSITIVITY,
    )
    from trading212_domain.scenario_serialization import scenario_sensitivity_observation_digest

    missing = replace(missing, content_digest=scenario_sensitivity_observation_digest(missing))
    retained = replace(
        capture,
        observations=(missing,),
        memberships=(replace(capture.memberships[0], observation_digest=missing.content_digest),),
    )
    assert retained.observations[0].coefficient is None


def test_source_row_budget_is_aggregate_and_precedes_record_expansion() -> None:
    # Each array alone is below the bound; their complete inventory exceeds it.
    invalid = cast(ScenarioSensitivityObservation, None)
    with pytest.raises(DomainError) as caught:
        ScenarioSensitivityCapture(
            observations=(invalid,) * 50_001, memberships=cast("Any", (None,) * 50_000)
        )
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_available_money_cannot_disguise_missing_data_as_zero() -> None:
    from trading212_domain.enums import QualityState
    from trading212_domain.values import Money

    with pytest.raises(DomainError):
        ScenarioMoneyMetric(
            value=Money.parse("0", "EUR"),
            quality=QualityState.FRESH,
            reason=ScenarioReason.MISSING_VALUE,
            confidence=None,
        )
    with pytest.raises(DomainError):
        ScenarioRatioMetric(value=None, quality=QualityState.PARTIAL, reason=None)


def test_unavailable_metrics_cannot_claim_fresh_quality() -> None:
    from trading212_domain.enums import QualityState

    with pytest.raises(DomainError):
        ScenarioMoneyMetric(
            value=None,
            quality=QualityState.FRESH,
            reason=ScenarioReason.MISSING_VALUE,
            confidence=None,
        )
    with pytest.raises(DomainError):
        ScenarioRatioMetric(
            value=None, quality=QualityState.FRESH, reason=ScenarioReason.MISSING_SENSITIVITY
        )


@pytest.mark.parametrize("invalid", ["A" * 64, "a" * 63, "a" * 65, "digest", " " + "a" * 64])
def test_every_nested_source_digest_requires_lowercase_sha256(invalid: str) -> None:
    source = sensitivity_capture()
    for record, field in (
        (source.versions[0], "content_digest"),
        (source.versions[0].driver, "definition_digest"),
        (source.observations[0], "content_digest"),
        (source.evidence[0], "content_digest"),
        (source.memberships[0], "version_digest"),
        (source.memberships[0], "observation_digest"),
    ):
        with pytest.raises(DomainError):
            replace(cast("Any", record), **{field: invalid})


def test_unavailable_sensitivity_use_cannot_retain_an_unbound_coefficient() -> None:
    from trading212_domain.enums import QualityState
    from trading212_domain.scenario_result import ScenarioRatioMetric, ScenarioSensitivityUse

    from tests.unit.domain.scenario_factories import sensitivity_capture

    capture = sensitivity_capture()
    with pytest.raises(DomainError, match="selected observation"):
        ScenarioSensitivityUse(
            rule_key="shock:fixture",
            driver=capture.versions[0].driver,
            version_id=capture.versions[0].version_id,
            candidate_observation_ids=(),
            observation_id=None,
            coefficient=Decimal("-2"),
            shock_size=Decimal(0),
            effect_ratio=ScenarioRatioMetric(
                value=Decimal(0), quality=QualityState.PARTIAL, reason=None
            ),
            reason=ScenarioReason.MISSING_SENSITIVITY,
        )
