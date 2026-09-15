"""Owned saved-input pins and the complete private scenario execution envelope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from .errors import fail_validation
from .historical import HistoricalInput, KnowledgePolicy
from .historical_serialization import historical_input_digest
from .scenario import (
    MAX_SCENARIO_COMPONENTS,
    ScenarioReason,
    ScenarioRecord,
    ScenarioVersionContent,
)
from .scenario_sources import (
    ScenarioSensitivityCapture,
    ScenarioSensitivityEvidence,
    ScenarioSensitivityObservation,
    ScenarioSensitivitySourceVersion,
    sensitivity_row_count,
)
from .scenario_validation import scenario_bound, unique
from .values import CurrencyCode
from .xray import XrayInput
from .xray_codec import encode_xray_input, encode_xray_result
from .xray_result import XrayCalculation


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioInputPins(ScenarioRecord):
    owner_id: UUID
    account_id: UUID
    scenario_id: UUID
    scenario_version_id: UUID
    scenario_version_digest: str
    portfolio_snapshot_id: UUID
    portfolio_snapshot_digest: str
    xray_run_id: UUID
    xray_input_id: UUID
    xray_input_digest: str
    xray_result_digest: str
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplaySelection(ScenarioRecord):
    historical_input_snapshot_id: UUID
    start_date: date
    end_date: date
    market_knowledge_cutoff_at: datetime
    holdings_basis: Literal["current_holdings", "historical_holdings"]
    knowledge_basis: Literal["point_in_time", "retrospective"]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if not 0 < (self.end_date - self.start_date).days <= 3660:
            fail_validation("Scenario replay requires a positive date window.", field="end_date")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplayMarketBinding(ScenarioRecord):
    instrument_id: UUID
    local_series_id: UUID | None
    local_currency: CurrencyCode | None
    response_basis: Literal["local_total_return", "reporting_total_return", "unavailable"]
    reason: ScenarioReason | None
    source_reference_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        unique(self.source_reference_ids, "source_reference_ids")
        if self.response_basis == "unavailable":
            if self.reason is None:
                fail_validation("Unavailable replay mapping requires a reason.")
        elif self.reason is not None or self.local_series_id is None or self.local_currency is None:
            fail_validation("Available replay mapping requires a currency and series.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReplayInput(ScenarioRecord):
    selection: ScenarioReplaySelection
    historical_input: HistoricalInput
    historical_input_digest: str
    market_bindings: tuple[ScenarioReplayMarketBinding, ...]
    holdings_evidence_at: datetime
    holdings_knowledge_cutoff_at: datetime

    def __post_init__(self) -> None:
        scenario_bound(
            type(self.market_bindings) is tuple and len(self.market_bindings) <= 256,
            "market_bindings",
        )
        ScenarioRecord.__post_init__(self)
        unique(tuple(item.instrument_id for item in self.market_bindings), "market_bindings")
        window = self.historical_input.selection.window
        selection = self.selection
        expected_knowledge = (
            KnowledgePolicy.POINT_IN_TIME
            if selection.knowledge_basis == "point_in_time"
            else KnowledgePolicy.AS_OF_CUTOFF
        )
        if (
            window.start_date != selection.start_date
            or window.end_date != selection.end_date
            or window.source_cutoff_at != selection.market_knowledge_cutoff_at
            or window.knowledge_policy is not expected_knowledge
        ):
            fail_validation("Scenario replay window and knowledge pins differ.")
        if historical_input_digest(self.historical_input) != self.historical_input_digest:
            fail_validation("Scenario replay input digest differs.")
        object.__setattr__(
            self,
            "market_bindings",
            tuple(sorted(self.market_bindings, key=lambda item: item.instrument_id)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioExecutionInput(ScenarioRecord):
    pins: ScenarioInputPins
    definition: ScenarioVersionContent
    xray_input: XrayInput
    xray_result: XrayCalculation
    sensitivities: ScenarioSensitivityCapture
    replay: ScenarioReplayInput | None
    input_digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        sensitivity_row_count(self.sensitivities)
        scenario_bound(
            len(self.xray_result.terminal_paths) <= MAX_SCENARIO_COMPONENTS, "terminal_paths"
        )
        from .scenario_serialization import scenario_definition_digest

        pins, source, result = self.pins, self.xray_input, self.xray_result
        if (
            pins.owner_id != source.owner_id
            or pins.account_id != source.account_id
            or pins.portfolio_snapshot_id != source.snapshot_id
            or pins.portfolio_snapshot_digest != source.snapshot_digest
            or pins.reporting_currency != source.reporting_currency
            or pins.source_cutoff_at != source.source_cutoff_at.value
            or pins.scenario_version_digest != scenario_definition_digest(self.definition)
            or pins.xray_input_digest != sha256(encode_xray_input(source)).hexdigest()
            or pins.xray_result_digest != sha256(encode_xray_result(result)).hexdigest()
            or result.input_digest != pins.xray_input_digest
            or result.owner_id != pins.owner_id
            or result.account_id != pins.account_id
            or result.snapshot_id != pins.portfolio_snapshot_id
            or result.reporting_currency != pins.reporting_currency
            or result.source_cutoff_at != source.source_cutoff_at
            or result.valuation_at != source.valuation_at
        ):
            fail_validation("Scenario saved input identities differ.", field="pins")
        owned_records: tuple[
            ScenarioSensitivitySourceVersion
            | ScenarioSensitivityObservation
            | ScenarioSensitivityEvidence,
            ...,
        ] = (
            *self.sensitivities.versions,
            *self.sensitivities.observations,
            *self.sensitivities.evidence,
        )
        if any(item.owner_id != pins.owner_id for item in owned_records):
            fail_validation("Scenario sensitivity ownership differs.")
        versions = {item.version_id: item for item in self.sensitivities.versions}
        selected = [
            shock.source for shock in self.definition.shocks if shock.kind in ("rate", "factor")
        ]
        if set(versions) != {pin.version_id for pin in selected}:
            fail_validation("Scenario sensitivity capture differs from selected versions.")
        for pin in selected:
            version = versions[pin.version_id]
            if (
                pin.content_digest != version.content_digest
                or pin.driver_id != version.driver.driver_id
                or pin.driver_definition_version_id != version.driver.definition_version_id
            ):
                fail_validation("Scenario sensitivity pin differs from captured version.")
        if self.replay is not None:
            if self.definition.shocks:
                fail_validation("Scenario replay excludes hypothetical shocks.")
            historical = self.replay.historical_input
            if (
                historical.owner_id != str(pins.owner_id)
                or historical.account_id != str(pins.account_id)
                or historical.selection.window.reporting_currency != pins.reporting_currency
            ):
                fail_validation("Scenario replay ownership differs.")
