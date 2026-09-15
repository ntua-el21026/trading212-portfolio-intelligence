"""Independent hand-sized portfolios and explicit immutable scenario source evidence."""

from dataclasses import replace
from decimal import Decimal
from typing import Literal

from trading212_domain.scenario import (
    ScenarioInstrumentSelector,
    ScenarioPriceShock,
    ScenarioRateShock,
    ScenarioSensitivityVersionPin,
    ScenarioShock,
    ScenarioVersionContent,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_serialization import (
    scenario_definition_digest,
    scenario_input_digest,
    scenario_sensitivity_observation_digest,
    scenario_sensitivity_version_digest,
)
from trading212_domain.scenario_sources import (
    ScenarioSensitivityCapture,
    ScenarioSensitivityObservation,
)
from trading212_domain.xray import XrayDimension, XrayHoldingKind, XrayInput

from tests.unit.analytics.xray_factories import Builder, uid
from tests.unit.domain.scenario_factories import execution, sensitivity_capture


def portfolio(amounts: tuple[str, ...] = ("60", "40"), *, economic: str = "USD") -> XrayInput:
    builder = Builder()
    for index, amount in enumerate(amounts):
        instrument, entity = uid(10 + index), uid(110 + index)
        builder.position(instrument, amount)
        builder.identity(instrument, entity)
        builder.classifications_for(entity, key="technology")
    builder.classifications = [
        replace(
            batch,
            assignments=tuple(
                replace(item, bucket_key=economic)
                if item.dimension is XrayDimension.CURRENCY
                else item
                for item in batch.assignments
            ),
        )
        for batch in builder.classifications
    ]
    return builder.finish()


def entity_only() -> XrayInput:
    builder = Builder()
    builder.position(uid(20), "100")
    candidate = builder.fund(uid(20), ((None, "1"),))
    builder.constituents[0] = replace(
        candidate,
        holdings=(
            replace(
                candidate.holdings[0],
                kind=XrayHoldingKind.ENTITY,
                entity_id=uid(110),
                evidence_key="fixture:entity",
            ),
        ),
        stated_coverage=Decimal("1"),
        cash_weight=Decimal("0"),
    )
    builder.classifications_for(uid(110))
    return builder.finish()


def input_for(
    source: XrayInput,
    definition: ScenarioVersionContent,
    sensitivities: ScenarioSensitivityCapture | None = None,
) -> ScenarioExecutionInput:
    base = execution(source)
    provisional = replace(
        base,
        definition=definition,
        pins=replace(base.pins, scenario_version_digest=scenario_definition_digest(definition)),
        sensitivities=ScenarioSensitivityCapture() if sensitivities is None else sensitivities,
        input_digest="0" * 64,
    )
    return replace(provisional, input_digest=scenario_input_digest(provisional))


def content(
    *shocks: ScenarioShock,
    mode: Literal["first_order", "compounded"] = "compounded",
) -> ScenarioVersionContent:
    return ScenarioVersionContent(
        name="Independent stress fixture",
        description="Explicit owner assumptions",
        mode=mode,
        shocks=shocks,
    )


def price(instrument: int, size: str) -> ScenarioPriceShock:
    return ScenarioPriceShock(
        selector=ScenarioInstrumentSelector(instrument_id=uid(instrument)), size=Decimal(size)
    )


def rate(capture: ScenarioSensitivityCapture, size: str) -> ScenarioRateShock:
    version = capture.versions[0]
    return ScenarioRateShock(
        source=ScenarioSensitivityVersionPin(
            version_id=version.version_id,
            content_digest=version.content_digest,
            driver_id=version.driver.driver_id,
            driver_definition_version_id=version.driver.definition_version_id,
        ),
        size=Decimal(size),
    )


def with_observation(
    capture: ScenarioSensitivityCapture, observation: ScenarioSensitivityObservation
) -> ScenarioSensitivityCapture:
    observation = replace(
        observation, content_digest=scenario_sensitivity_observation_digest(observation)
    )
    return replace(
        capture,
        observations=(observation,),
        memberships=(
            replace(capture.memberships[0], observation_digest=observation.content_digest),
        ),
    )


def alias_capture() -> ScenarioSensitivityCapture:
    source = sensitivity_capture()
    original = source.versions[0]
    second = replace(
        original,
        version_id=uid(9300),
        source_set_id=uid(9301),
        driver=replace(original.driver, driver_id=uid(9302), definition_version_id=uid(9303)),
    )
    second = replace(second, content_digest=scenario_sensitivity_version_digest(second))
    observation = replace(
        source.observations[0],
        version_id=second.version_id,
        observation_id=uid(9304),
        driver_id=second.driver.driver_id,
        driver_definition_version_id=second.driver.definition_version_id,
    )
    observation = replace(
        observation, content_digest=scenario_sensitivity_observation_digest(observation)
    )
    membership = replace(
        source.memberships[0],
        version_id=second.version_id,
        version_digest=second.content_digest,
        observation_id=observation.observation_id,
        observation_digest=observation.content_digest,
    )
    return replace(
        source,
        versions=(*source.versions, second),
        observations=(*source.observations, observation),
        memberships=(*source.memberships, membership),
    )
