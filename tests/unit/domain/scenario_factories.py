"""Explicit synthetic source evidence for scenario codec and extraction regressions."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from trading212_analytics.xray import calculate_xray
from trading212_domain.enums import QualityState
from trading212_domain.scenario import ScenarioVersionContent
from trading212_domain.scenario_execution import ScenarioExecutionInput, ScenarioInputPins
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_serialization import (
    scenario_definition_digest,
    scenario_input_digest,
    scenario_sensitivity_evidence_digest,
    scenario_sensitivity_observation_digest,
    scenario_sensitivity_version_digest,
)
from trading212_domain.scenario_sources import (
    ScenarioDriverReference,
    ScenarioInstrumentSubject,
    ScenarioRateEquivalence,
    ScenarioSensitivityCapture,
    ScenarioSensitivityEvidence,
    ScenarioSensitivityMembership,
    ScenarioSensitivityObservation,
    ScenarioSensitivitySourceVersion,
    ScenarioSourceLicense,
)
from trading212_domain.sources import (
    LicensePermission,
    ObservationState,
    SourceAvailability,
    SourceLicense,
)
from trading212_domain.xray import XrayInput
from trading212_domain.xray_codec import encode_xray_input, encode_xray_result

from tests.unit.analytics.xray_factories import AT, CUTOFF, EUR, fixture, uid


def definition() -> ScenarioVersionContent:
    return ScenarioVersionContent(
        name="Synthetic stress", description="Owner fixture assumptions", mode="compounded"
    )


def execution(source: XrayInput | None = None) -> ScenarioExecutionInput:
    source = fixture() if source is None else source
    result = calculate_xray(source)
    content = definition()
    value = ScenarioExecutionInput(
        pins=ScenarioInputPins(
            owner_id=source.owner_id,
            account_id=source.account_id,
            scenario_id=uid(8001),
            scenario_version_id=uid(8002),
            scenario_version_digest=scenario_definition_digest(content),
            portfolio_snapshot_id=source.snapshot_id,
            portfolio_snapshot_digest=source.snapshot_digest,
            xray_run_id=uid(8003),
            xray_input_id=uid(8004),
            xray_input_digest=sha256(encode_xray_input(source)).hexdigest(),
            xray_result_digest=sha256(encode_xray_result(result)).hexdigest(),
            reporting_currency=source.reporting_currency,
            source_cutoff_at=source.source_cutoff_at.value,
        ),
        definition=content,
        xray_input=source,
        xray_result=result,
        sensitivities=ScenarioSensitivityCapture(),
        replay=None,
        input_digest="0" * 64,
        expires_at=CUTOFF.value + timedelta(days=1),
    )
    return replace(value, input_digest=scenario_input_digest(value))


def sensitivity_capture() -> ScenarioSensitivityCapture:
    evidence = ScenarioSensitivityEvidence(
        id=uid(9100),
        owner_id=uid(1),
        provider_id=uid(900),
        license_version_id=uid(999),
        source_record_id=uid(9101),
        content_digest="b" * 64,
        effective_at=AT.value,
        first_known_at=AT.value,
        adapter_id="synthetic_rate",
        adapter_version="1",
        transformation="identity_local_simple_return_v1",
    )
    evidence = replace(evidence, content_digest=scenario_sensitivity_evidence_digest(evidence))
    driver = ScenarioDriverReference(
        driver_id=uid(9110),
        definition_version_id=uid(9111),
        definition_digest="c" * 64,
        kind="rate",
        shock_unit="absolute_rate_change",
        equivalence=ScenarioRateEquivalence(rate_id=uid(9112), currency=EUR),
        evidence_reference_ids=(evidence.id,),
    )
    version = ScenarioSensitivitySourceVersion(
        owner_id=uid(1),
        source_set_id=uid(9120),
        version_id=uid(9121),
        content_digest="d" * 64,
        provider_id=uid(900),
        license_version_id=uid(999),
        adapter_id="synthetic_rate",
        adapter_version="1",
        driver=driver,
        effective_at=AT.value,
        first_known_at=AT.value,
        valid_from=AT.value,
        valid_until=None,
        revision=1,
        availability=SourceAvailability.AVAILABLE,
        quality=QualityState.FRESH,
    )
    version = replace(version, content_digest=scenario_sensitivity_version_digest(version))
    observation = ScenarioSensitivityObservation(
        owner_id=uid(1),
        observation_id=uid(9130),
        version_id=version.version_id,
        content_digest="e" * 64,
        subject=ScenarioInstrumentSubject(instrument_id=uid(10)),
        driver_id=driver.driver_id,
        driver_definition_version_id=driver.definition_version_id,
        coefficient=Decimal("-2"),
        shock_unit="absolute_rate_change",
        response_unit="local_value_simple_return",
        response_basis="local_economic_value",
        response_currency=EUR,
        effective_at=AT.value,
        first_known_at=AT.value,
        valid_from=AT.value,
        valid_until=None,
        revision=1,
        provider_id=uid(900),
        license_version_id=uid(999),
        state=ObservationState.AVAILABLE,
        quality=QualityState.FRESH,
        confidence=Decimal("0.9"),
        reason=None,
        evidence_reference_ids=(evidence.id,),
    )
    observation = replace(
        observation, content_digest=scenario_sensitivity_observation_digest(observation)
    )
    license = ScenarioSourceLicense(
        license_version_id=uid(999),
        license=SourceLicense(
            id=str(uid(9140)),
            provider_id=str(uid(900)),
            version="1",
            effective_at=AT.value,
            store=LicensePermission.ALLOWED,
            display=LicensePermission.ALLOWED,
            report=LicensePermission.ALLOWED,
            export=LicensePermission.ALLOWED,
            retention_days=30,
            attribution="Synthetic regression fixture",
            evidence_key="fixture:license",
        ),
    )
    return ScenarioSensitivityCapture(
        versions=(version,),
        observations=(observation,),
        memberships=(
            ScenarioSensitivityMembership(
                version_id=version.version_id,
                version_digest=version.content_digest,
                observation_id=observation.observation_id,
                observation_digest=observation.content_digest,
            ),
        ),
        evidence=(evidence,),
        licenses=(license,),
    )


def baseline_calculation() -> ScenarioCalculation:
    from trading212_domain.scenario import ScenarioAssumption
    from trading212_domain.scenario_exposure import extract_scenario_exposures
    from trading212_domain.scenario_result import (
        ScenarioChannelEffects,
        ScenarioComponent,
        ScenarioMoneyMetric,
        ScenarioPartitionSummary,
        ScenarioRatioMetric,
    )
    from trading212_domain.scenario_result_validation import scenario_minimum_quality
    from trading212_domain.values import Money

    source = execution()
    exposures = extract_scenario_exposures(source.xray_input, source.xray_result)
    quality = scenario_minimum_quality(
        *(item.quality for item in exposures), *(item.pre_value.quality for item in exposures)
    )
    zero = ScenarioMoneyMetric(value=Money.zero(EUR), quality=quality, reason=None, confidence=None)
    ratio = ScenarioRatioMetric(value=Decimal(0), quality=quality, reason=None)
    effects = ScenarioChannelEffects(
        price_ratio=ratio,
        factor_ratio=ratio,
        fx_ratio=ratio,
        price=zero,
        factor=zero,
        fx=zero,
        interaction=zero,
    )
    components = tuple(
        ScenarioComponent(
            exposure=exposure,
            partition="covered",
            winning_price_rule_key=None,
            matching_exclusion_keys=(),
            uncertain_rule_keys=(),
            sensitivity_uses=(),
            effects=effects,
            post_value=replace(exposure.pre_value, quality=quality),
            impact=zero,
            rounding_residual=zero,
            money_basis="resolved",
            diagnostic_keys=(),
        )
        for exposure in exposures
    )
    total = ScenarioMoneyMetric(
        value=Money.parse("1000", EUR), quality=quality, reason=None, confidence=None
    )
    summary = ScenarioPartitionSummary(
        terminal_pre_value=total,
        covered_pre_value=total,
        uncovered_pre_value=zero,
        excluded_pre_value=zero,
        covered_count=len(components),
        uncovered_count=0,
        excluded_count=0,
        missing_pre_value_count=0,
        uncertain_money_count=0,
        covered_post_value=total,
        excluded_post_value=zero,
        provably_unchanged_uncovered_value=zero,
        post_value=total,
        impact=zero,
        effects=effects,
        rounding_residual=zero,
        component_sum_residual=zero,
    )
    return ScenarioCalculation(
        input_digest=source.input_digest,
        pins=source.pins,
        definition=source.definition,
        valuation_at=source.xray_result.valuation_at.value,
        components=components,
        summary=summary,
        upstream_portfolio_value=replace(total, quality=QualityState.FRESH),
        upstream_partition_difference=zero,
        upstream_residual_keys=(),
        replay=None,
        diagnostics=(),
        assumptions=(ScenarioAssumption.CANONICAL_TERMINAL_BASIS,),
        sensitivity_source_row_count=0,
    )
