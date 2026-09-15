"""Evidence-only selector matching for deterministic stress; no source lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trading212_domain.errors import fail_validation
from trading212_domain.scenario import (
    ScenarioComponentSelector,
    ScenarioCurrencySelector,
    ScenarioEntitySelector,
    ScenarioExclusion,
    ScenarioInstrumentSelector,
    ScenarioPriceShock,
    ScenarioRegionSelector,
    ScenarioSectorSelector,
)
from trading212_domain.scenario_result import ScenarioTerminalExposure

type MatchState = Literal["match", "no_match", "unknown"]


def selector_match(
    selector: ScenarioComponentSelector, exposure: ScenarioTerminalExposure
) -> MatchState:
    """Only an evidenced unequal identity/category establishes a negative match."""
    if isinstance(selector, ScenarioInstrumentSelector):
        fact = exposure.instrument
        if fact.state == "not_applicable":
            return "no_match"
        if fact.state == "unknown":
            return "unknown"
        return "match" if fact.subject_id == selector.instrument_id else "no_match"
    if isinstance(selector, ScenarioEntitySelector):
        fact = exposure.entity
        if fact.state == "not_applicable":
            return "no_match"
        if fact.state == "unknown":
            return "unknown"
        return "match" if fact.subject_id == selector.entity_id else "no_match"
    if isinstance(selector, (ScenarioSectorSelector, ScenarioRegionSelector)):
        classification = (
            exposure.sector if isinstance(selector, ScenarioSectorSelector) else exposure.region
        )
        if classification.state == "not_applicable":
            return "no_match"
        if (
            classification.state == "unknown"
            or classification.taxonomy_id != selector.taxonomy_id
            or classification.taxonomy_version != selector.taxonomy_version
        ):
            return "unknown"
        return "match" if classification.bucket_key == selector.bucket_key else "no_match"
    if isinstance(selector, ScenarioCurrencySelector):
        currency = exposure.economic_currency
        if currency.state == "unknown":
            return "unknown"
        return "match" if currency.currency == selector.currency else "no_match"
    fail_validation("Unsupported scenario selector.", field="selector")


@dataclass(frozen=True, slots=True)
class ExclusionDecision:
    matched: tuple[ScenarioExclusion, ...]
    uncertain: tuple[ScenarioExclusion, ...]

    @property
    def excluded(self) -> bool:
        return bool(self.matched)


def resolve_exclusions(
    exclusions: tuple[ScenarioExclusion, ...], exposure: ScenarioTerminalExposure
) -> ExclusionDecision:
    matched: list[ScenarioExclusion] = []
    uncertain: list[ScenarioExclusion] = []
    for exclusion in exclusions:
        decision = selector_match(exclusion.selector, exposure)
        if decision == "match":
            matched.append(exclusion)
        elif decision == "unknown":
            uncertain.append(exclusion)
    return ExclusionDecision(tuple(matched), tuple(uncertain))


@dataclass(frozen=True, slots=True)
class PriceDecision:
    winner: ScenarioPriceShock | None
    uncertain: tuple[ScenarioPriceShock, ...]
    possible: tuple[ScenarioPriceShock, ...]

    @property
    def resolved(self) -> bool:
        return not self.uncertain


def resolve_price(
    shocks: tuple[ScenarioPriceShock, ...], exposure: ScenarioTerminalExposure
) -> PriceDecision:
    """Stop at the highest relevant priority, including unresolved higher rules."""
    priorities = (
        ScenarioInstrumentSelector,
        ScenarioEntitySelector,
        ScenarioSectorSelector,
        ScenarioRegionSelector,
    )
    for level, kind in enumerate(priorities):
        matched: list[ScenarioPriceShock] = []
        uncertain: list[ScenarioPriceShock] = []
        for shock in shocks:
            if not isinstance(shock.selector, kind):
                continue
            decision = selector_match(shock.selector, exposure)
            if decision == "match":
                matched.append(shock)
            elif decision == "unknown":
                uncertain.append(shock)
        if len(matched) > 1:
            fail_validation("Competing scenario price rules have equal priority.", field="shocks")
        if uncertain:
            possible = [*matched, *uncertain]
            if not matched:
                # Higher unknown rules may all miss, leaving a lower winner. Keep
                # these candidates for the separate proof of an unchanged value.
                for lower in priorities[level + 1 :]:
                    lower_candidates = [item for item in shocks if isinstance(item.selector, lower)]
                    possible.extend(
                        item
                        for item in lower_candidates
                        if selector_match(item.selector, exposure) != "no_match"
                    )
                    if any(
                        selector_match(item.selector, exposure) == "match"
                        for item in lower_candidates
                    ):
                        break
            return PriceDecision(None, tuple(uncertain), tuple(possible))
        if matched:
            return PriceDecision(matched[0], (), (matched[0],))
    return PriceDecision(None, (), ())
