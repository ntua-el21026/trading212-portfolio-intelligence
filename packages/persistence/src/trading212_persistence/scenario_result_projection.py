"""Fixed complete normalized result projection and stable child identities."""

from dataclasses import dataclass
from uuid import UUID, uuid5

from trading212_domain.scenario import MAX_SCENARIO_BYTES
from trading212_domain.scenario_result import ScenarioCalculation, ScenarioMoneyMetric
from trading212_domain.scenario_serialization import canonical_scenario_bytes, scenario_record_bytes

from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioResultProjection:
    canonical_result: bytes
    components: tuple[dict[str, object], ...]
    applied_uses: tuple[dict[str, object], ...]


def _amount(metric: ScenarioMoneyMetric) -> object:
    return None if metric.value is None else metric.value.amount


def normalized_scenario_result(
    result: ScenarioCalculation, result_id: UUID
) -> ScenarioResultProjection:
    payload = canonical_scenario_bytes(result)
    components: list[dict[str, object]] = []
    uses: list[dict[str, object]] = []
    size = len(payload)
    for component in result.components:
        exposure = component.exposure
        identifier = uuid5(result_id, "scenario_components:" + exposure.path_key)
        canonical = scenario_record_bytes(component)
        size += len(canonical)
        if size > MAX_SCENARIO_BYTES:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        components.append(
            dict(
                id=identifier,
                path_key=exposure.path_key,
                root_key=exposure.root_key,
                root_kind=exposure.root_kind,
                position_id=exposure.position_id,
                snapshot_cash_id=exposure.snapshot_cash_id,
                root_instrument_id=exposure.root_instrument_id,
                partition=component.partition,
                money_basis=component.money_basis,
                currency=result.pins.reporting_currency.value,
                pre_value=_amount(exposure.pre_value),
                post_value=_amount(component.post_value),
                impact=_amount(component.impact),
                rounding_residual=_amount(component.rounding_residual),
                quality=component.post_value.quality.value,
                reason=None
                if component.post_value.reason is None
                else component.post_value.reason.value,
                applied_use_count=len(component.sensitivity_uses),
                canonical_component=canonical,
            )
        )
        uses.extend(
            dict(
                id=uuid5(identifier, "scenario_applied_sensitivities:" + use.rule_key),
                component_id=identifier,
                rule_key=use.rule_key,
                version_id=use.version_id,
                driver_id=use.driver.driver_id,
                driver_definition_version_id=use.driver.definition_version_id,
                candidate_observation_ids=list(use.candidate_observation_ids),
                observation_id=use.observation_id,
                coefficient=use.coefficient,
                shock_size=use.shock_size,
                effect_ratio=use.effect_ratio.value,
                effect_reason=None
                if use.effect_ratio.reason is None
                else use.effect_ratio.reason.value,
                effect_quality=use.effect_ratio.quality.value,
                reason=None if use.reason is None else use.reason.value,
            )
            for use in component.sensitivity_uses
        )
    return ScenarioResultProjection(
        canonical_result=payload, components=tuple(components), applied_uses=tuple(uses)
    )
