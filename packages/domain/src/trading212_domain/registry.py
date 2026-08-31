"""Versioned registry for authoritative calculations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from .errors import DomainError, ErrorCode, fail_validation
from .metadata import CalculationDefinition


class CalculationRegistry:
    def __init__(self, definitions: Iterable[CalculationDefinition]) -> None:
        indexed: dict[str, CalculationDefinition] = {}
        for definition in definitions:
            if definition.calculation_id in indexed:
                fail_validation(
                    f"duplicate calculation ID: {definition.calculation_id}",
                    field="calculation_id",
                )
            indexed[definition.calculation_id] = definition
        self._definitions: Mapping[str, CalculationDefinition] = MappingProxyType(indexed)

    def get(self, calculation_id: str) -> CalculationDefinition:
        try:
            return self._definitions[calculation_id]
        except KeyError as exc:
            raise DomainError(
                ErrorCode.NOT_FOUND,
                f"unknown calculation: {calculation_id}",
                "calculation_id",
            ) from exc

    def all(self) -> tuple[CalculationDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


PHASE_1_CALCULATION_REGISTRY = CalculationRegistry(
    (
        CalculationDefinition(
            calculation_id="portfolio_snapshot",
            version="1.0.0",
            input_schema_version="1.0.0",
            output_schema_version="1.0.0",
            method_summary="Exact cash plus position aggregation at an explicit cutoff.",
            quality_policy=(
                "Never exceeds material input quality; missing FX yields partial output."
            ),
        ),
        CalculationDefinition(
            calculation_id="direct_allocation",
            version="1.0.0",
            input_schema_version="1.0.0",
            output_schema_version="1.0.0",
            method_summary="Exact reporting-currency component weights with explicit residual.",
            quality_policy=(
                "Unavailable for unsupported totals; partial when conversion coverage is partial."
            ),
        ),
        CalculationDefinition(
            calculation_id="reconciliation",
            version="1.0.0",
            input_schema_version="1.0.0",
            output_schema_version="1.0.0",
            method_summary="Quantity and currency-ledger bridges using tolerance policy v1.",
            quality_policy="Residuals beyond tolerance produce unreconciled state.",
        ),
        CalculationDefinition(
            calculation_id="performance_summary",
            version="1.0.0",
            input_schema_version="1.0.0",
            output_schema_version="1.0.0",
            method_summary="Coverage-gated MWR, TWR, and Modified Dietz summary.",
            quality_policy=(
                "Missing history, valuation, fees, or FX returns unavailable/partial, "
                "never guessed."
            ),
        ),
    )
)
