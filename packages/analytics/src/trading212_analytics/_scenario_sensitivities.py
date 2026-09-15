"""Indexed sensitivity membership and driver equivalence over immutable source capture."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.scenario import (
    MAX_SCENARIO_BYTES,
    MAX_SCENARIO_SENSITIVITY_ROWS,
    ScenarioFactorShock,
    ScenarioRateShock,
    ScenarioReason,
    scenario_rule_key,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import (
    ScenarioDiagnostic,
    ScenarioSensitivityUse,
    ScenarioTerminalExposure,
)
from trading212_domain.scenario_serialization import scenario_record_bytes
from trading212_domain.scenario_sources import (
    ScenarioFxEquivalence,
    ScenarioInstrumentSubject,
    ScenarioPriceEquivalence,
    ScenarioSensitivityObservation,
    ScenarioSensitivitySourceVersion,
    ScenarioUnknownEquivalence,
    sensitivity_row_count,
)
from trading212_domain.scenario_validation import scenario_bound
from trading212_domain.sources import ObservationState, SourceAvailability

from ._premium_numeric import ZERO, arithmetic
from ._scenario_components import ratio_metric, scenario_diagnostic, scenario_quality
from ._scenario_matching import PriceDecision, selector_match


@dataclass(slots=True)
class ScenarioOutputBudget:
    source_rows: int
    applied_uses: int = 0
    reference_bytes: int = 0
    component_bytes: int = 0

    def reserve_use(self, candidates: int) -> None:
        scenario_bound(
            self.source_rows + self.applied_uses + 1 <= MAX_SCENARIO_SENSITIVITY_ROWS,
            "sensitivity_rows",
        )
        # UUID strings and separators alone establish this lower bound before expanding the output.
        scenario_bound(
            self.reference_bytes + 39 * candidates <= MAX_SCENARIO_BYTES, "scenario.reference_bytes"
        )
        self.applied_uses += 1
        self.reference_bytes += 39 * candidates

    def reserve_component(self, size: int) -> None:
        scenario_bound(
            self.component_bytes + size + 1 <= MAX_SCENARIO_BYTES, "scenario.result_bytes"
        )
        self.component_bytes += size + 1


@dataclass(frozen=True, slots=True)
class SensitivityDecision:
    value: Decimal | None
    reason: ScenarioReason | None
    zero_effect_proven: bool
    uses: tuple[ScenarioSensitivityUse, ...]
    diagnostics: tuple[ScenarioDiagnostic, ...]
    confidences: tuple[Decimal | None, ...]


class SensitivityIndex:
    def __init__(self, execution: ScenarioExecutionInput) -> None:
        self.execution = execution
        source = execution.sensitivities
        self.budget = ScenarioOutputBudget(sensitivity_row_count(source))
        self.versions = {item.version_id: item for item in source.versions}
        self.evidence = {item.id: item for item in source.evidence}
        self.observations: dict[tuple[UUID, str, UUID], list[ScenarioSensitivityObservation]] = {}
        self.kind_rows: dict[tuple[UUID, str], list[ScenarioSensitivityObservation]] = {}
        for observation in source.observations:
            subject = observation.subject
            identity = (
                subject.instrument_id
                if isinstance(subject, ScenarioInstrumentSubject)
                else subject.entity_id
            )
            self.observations.setdefault(
                (observation.version_id, subject.kind, identity), []
            ).append(observation)
            self.kind_rows.setdefault((observation.version_id, subject.kind), []).append(
                observation
            )
        self.shocks = tuple(
            shock
            for shock in execution.definition.shocks
            if isinstance(shock, (ScenarioRateShock, ScenarioFactorShock))
        )
        equivalences: set[bytes] = set()
        for shock in self.shocks:
            version = self.versions[shock.source.version_id]
            if version.driver.kind != shock.kind:
                fail_validation(
                    "Sensitivity driver kind differs from the selected shock.", field="shocks"
                )
            if isinstance(version.driver.equivalence, ScenarioUnknownEquivalence):
                continue
            key = scenario_record_bytes(version.driver.equivalence)
            if key in equivalences:
                fail_validation(
                    "Scenario source aliases duplicate one economic driver.", field="shocks"
                )
            equivalences.add(key)

    def _evidence_eligible(self, identifiers: tuple[UUID, ...]) -> bool:
        at = self.execution.xray_input.valuation_at.value
        cutoff = self.execution.pins.source_cutoff_at
        return all(
            self.evidence[item].effective_at <= at and self.evidence[item].first_known_at <= cutoff
            for item in identifiers
        )

    def _version_eligible(self, version: ScenarioSensitivitySourceVersion) -> bool:
        at = self.execution.xray_input.valuation_at.value
        return (
            version.effective_at <= at
            and version.first_known_at <= self.execution.pins.source_cutoff_at
            and version.valid_from <= at
            and (version.valid_until is None or at < version.valid_until)
            and version.availability in (SourceAvailability.AVAILABLE, SourceAvailability.PARTIAL)
            and self._evidence_eligible(version.driver.evidence_reference_ids)
        )

    def _observation_eligible(self, value: ScenarioSensitivityObservation) -> bool:
        at = self.execution.xray_input.valuation_at.value
        return (
            value.effective_at <= at
            and value.first_known_at <= self.execution.pins.source_cutoff_at
            and value.valid_from <= at
            and (value.valid_until is None or at < value.valid_until)
            and self._evidence_eligible(value.evidence_reference_ids)
        )

    def _candidates(
        self, version_id: UUID, exposure: ScenarioTerminalExposure
    ) -> tuple[
        tuple[list[ScenarioSensitivityObservation], ...],
        tuple[list[ScenarioSensitivityObservation], ...],
    ]:
        # Keep bucket references; reserve capacity before flattening candidates.
        definite: list[list[ScenarioSensitivityObservation]] = []
        uncertain: list[list[ScenarioSensitivityObservation]] = []
        for dimension, fact in (("instrument", exposure.instrument), ("entity", exposure.entity)):
            if fact.state == "not_applicable":
                continue
            if fact.state == "known":
                assert fact.subject_id is not None
                bucket = self.observations.get((version_id, dimension, fact.subject_id))
                if bucket is not None:
                    definite.append(bucket)
            else:
                bucket = self.kind_rows.get((version_id, dimension))
                if bucket is not None:
                    uncertain.append(bucket)
        return tuple(definite), tuple(uncertain)

    def _equivalence(
        self,
        version: ScenarioSensitivitySourceVersion,
        exposure: ScenarioTerminalExposure,
        price: PriceDecision,
        fx_matched: bool,
    ) -> ScenarioReason | None:
        equivalence = version.driver.equivalence
        if isinstance(equivalence, ScenarioUnknownEquivalence):
            return ScenarioReason.UNKNOWN_DRIVER_EQUIVALENCE
        if isinstance(equivalence, ScenarioPriceEquivalence) and price.winner is not None:
            match = selector_match(equivalence.selector, exposure)
            if match == "match":
                fail_validation(
                    "A sensitivity duplicates the selected direct price treatment.", field="shocks"
                )
            if match == "unknown":
                return ScenarioReason.UNKNOWN_DRIVER_EQUIVALENCE
        if (
            isinstance(equivalence, ScenarioFxEquivalence)
            and fx_matched
            and exposure.economic_currency.currency == equivalence.currency
        ):
            fail_validation(
                "A sensitivity duplicates the selected direct FX treatment.", field="shocks"
            )
        return None

    def resolve(
        self, exposure: ScenarioTerminalExposure, price: PriceDecision, *, fx_matched: bool
    ) -> SensitivityDecision:
        if (
            exposure.instrument.state == "not_applicable"
            and exposure.entity.state == "not_applicable"
        ):
            return SensitivityDecision(ZERO, None, True, (), (), ())
        uses: list[ScenarioSensitivityUse] = []
        diagnostics: list[ScenarioDiagnostic] = []
        effects: list[Decimal] = []
        reasons: list[ScenarioReason] = []
        confidences: list[Decimal | None] = []
        for shock in self.shocks:
            version = self.versions[shock.source.version_id]
            definite_groups, uncertain_groups = self._candidates(version.version_id, exposure)
            self.budget.reserve_use(
                sum(map(len, definite_groups)) + sum(map(len, uncertain_groups))
            )
            definite = [item for group in definite_groups for item in group]
            uncertain = [item for group in uncertain_groups for item in group]
            candidate_ids = tuple(sorted(item.observation_id for item in (*definite, *uncertain)))
            eligible = [item for item in definite if self._observation_eligible(item)]
            uncertain_eligible = [item for item in uncertain if self._observation_eligible(item)]
            reason = self._equivalence(version, exposure, price, fx_matched)
            selected = None
            if not self._version_eligible(version):
                reason = reason or ScenarioReason.MISSING_SENSITIVITY
            elif len(eligible) > 1 or uncertain_eligible:
                reason = reason or ScenarioReason.AMBIGUOUS_SENSITIVITY
            elif not eligible:
                reason = reason or ScenarioReason.MISSING_SENSITIVITY
            else:
                selected = eligible[0]
                if selected.state is not ObservationState.AVAILABLE:
                    reason = reason or selected.reason or ScenarioReason.MISSING_SENSITIVITY
                elif (
                    selected.response_basis != "local_economic_value"
                    or selected.response_currency is None
                ):
                    reason = reason or ScenarioReason.UNSUPPORTED_SENSITIVITY
                elif exposure.economic_currency.currency is None:
                    reason = reason or ScenarioReason.MISSING_ECONOMIC_CURRENCY
                elif selected.response_currency != exposure.economic_currency.currency:
                    reason = reason or ScenarioReason.INCOMPATIBLE_SENSITIVITY_CURRENCY
            coefficient = selected.coefficient if selected is not None else None
            if shock.size != ZERO:
                # A zero shock proves its product without relying on coefficient confidence.
                confidences.append(
                    selected.confidence if selected is not None and reason is None else None
                )
            # Unknown normalized membership/coefficient is bounded by the declared finite method.
            # Explicit unsupported transformations cannot establish that zero-effect proof.
            zero = shock.size == ZERO and all(
                item.state is not ObservationState.UNSUPPORTED
                and item.response_basis != "fx_inclusive"
                for item in (*eligible, *uncertain_eligible)
            )
            effect: Decimal | None = None
            if reason is None:
                assert coefficient is not None
                with arithmetic():
                    effect = coefficient * shock.size
            elif zero:
                effect = ZERO
            if effect is not None:
                effects.append(effect)
            if reason is not None:
                reasons.append(reason)
                diagnostic = scenario_diagnostic(
                    exposure,
                    reason,
                    rule_key=scenario_rule_key(shock),
                    references=tuple(
                        sorted(
                            set(
                                version.driver.evidence_reference_ids
                                + tuple(
                                    identifier
                                    for item in (*definite, *uncertain)
                                    for identifier in item.evidence_reference_ids
                                )
                            )
                        )
                    ),
                )
                diagnostics.append(diagnostic)
            source_quality = scenario_quality(
                version.quality,
                selected.quality if selected is not None else QualityState.PARTIAL,
                QualityState.ESTIMATED,
            )
            uses.append(
                ScenarioSensitivityUse(
                    rule_key=scenario_rule_key(shock),
                    driver=version.driver,
                    version_id=version.version_id,
                    candidate_observation_ids=candidate_ids,
                    observation_id=None if selected is None else selected.observation_id,
                    coefficient=coefficient,
                    shock_size=shock.size,
                    effect_ratio=ratio_metric(
                        effect,
                        quality=source_quality,
                        reason=reason or ScenarioReason.MISSING_SENSITIVITY,
                    ),
                    reason=reason,
                )
            )
        with arithmetic():
            value = sum(effects, ZERO) if len(effects) == len(self.shocks) else None
        if value is not None and not Decimal("-1") <= value <= Decimal("5"):
            fail_validation("Summed scenario sensitivity effect exceeds its bound.", field="shocks")
        return SensitivityDecision(
            value,
            reasons[0] if reasons else None,
            value == ZERO,
            tuple(sorted(uses, key=lambda item: item.rule_key)),
            tuple(sorted(diagnostics, key=lambda item: item.key)),
            tuple(confidences),
        )
