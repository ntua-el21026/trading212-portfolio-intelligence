"""Provenance, coverage, quality, and calculation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from .enums import QualityState, ValueOrigin
from .errors import fail_validation
from .identifiers import CalculationRunId, SourceRecordId, require_uuid
from .values import CurrencyCode, Instant, require_bounded_text


@dataclass(frozen=True, slots=True)
class DomainWarning:
    code: str
    message: str
    affected_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_bounded_text(self.code, field="warning.code", maximum=80)
        require_bounded_text(self.message, field="warning.message", maximum=500)
        if len(self.affected_fields) > 32:
            fail_validation("too many affected warning fields", field="affected_fields")


@dataclass(frozen=True, slots=True)
class Coverage:
    start_at: Instant | None
    end_at: Instant | None
    complete: bool
    gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_at is not None and not isinstance(self.start_at, Instant):
            fail_validation("coverage start_at must be Instant or None", field="start_at")
        if self.end_at is not None and not isinstance(self.end_at, Instant):
            fail_validation("coverage end_at must be Instant or None", field="end_at")
        if self.start_at and self.end_at and self.end_at < self.start_at:
            fail_validation("coverage end precedes start", field="end_at")
        if self.complete and self.gaps:
            fail_validation("complete coverage cannot contain gaps", field="gaps")
        if len(self.gaps) > 128:
            fail_validation("coverage gap list is too large", field="gaps")


@dataclass(frozen=True, slots=True)
class DataQuality:
    state: QualityState
    evaluated_at: Instant
    freshness_threshold_seconds: int | None
    coverage: Coverage
    warnings: tuple[DomainWarning, ...] = ()
    missing_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, QualityState):
            fail_validation("state must be QualityState", field="state")
        if self.freshness_threshold_seconds is not None and self.freshness_threshold_seconds < 0:
            fail_validation(
                "freshness threshold must not be negative",
                field="freshness_threshold_seconds",
            )
        fresh_has_limitations = self.warnings or self.missing_inputs or not self.coverage.complete
        if self.state is QualityState.FRESH and fresh_has_limitations:
            fail_validation(
                "fresh quality cannot claim warnings, missing inputs, or incomplete coverage",
                field="state",
            )


@dataclass(frozen=True, slots=True)
class ProvenanceReference:
    source_record_ids: tuple[SourceRecordId, ...]
    mapping_version: str
    origin: ValueOrigin

    def __post_init__(self) -> None:
        if not self.source_record_ids:
            fail_validation("at least one source record is required", field="source_record_ids")
        for source_id in self.source_record_ids:
            require_uuid(source_id, field="source_record_id")
        require_bounded_text(self.mapping_version, field="mapping_version", maximum=80)


@dataclass(frozen=True, slots=True)
class CalculationMetadata:
    calculation_name: str
    version: str
    run_id: CalculationRunId
    calculated_at: Instant
    valuation_at: Instant
    source_cutoff_at: Instant
    reporting_currency: CurrencyCode
    input_ids: tuple[UUID, ...]
    method: str
    assumptions: tuple[str, ...]
    data_quality: DataQuality
    options: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        require_bounded_text(self.calculation_name, field="calculation_name", maximum=100)
        require_bounded_text(self.version, field="version", maximum=32)
        require_uuid(self.run_id, field="run_id")
        if self.source_cutoff_at > self.calculated_at:
            fail_validation(
                "source cutoff cannot follow calculation time",
                field="source_cutoff_at",
            )
        if self.valuation_at > self.calculated_at:
            fail_validation("valuation cannot follow calculation time", field="valuation_at")
        for input_id in self.input_ids:
            require_uuid(input_id, field="input_id")
        require_bounded_text(self.method, field="method", maximum=200)


@dataclass(frozen=True, slots=True)
class CalculationDefinition:
    calculation_id: str
    version: str
    input_schema_version: str
    output_schema_version: str
    method_summary: str
    quality_policy: str

    def __post_init__(self) -> None:
        require_bounded_text(self.calculation_id, field="calculation_id", maximum=100)
        require_bounded_text(self.version, field="version", maximum=32)
        require_bounded_text(self.input_schema_version, field="input_schema_version", maximum=32)
        require_bounded_text(self.output_schema_version, field="output_schema_version", maximum=32)
        require_bounded_text(self.method_summary, field="method_summary", maximum=500)
        require_bounded_text(self.quality_policy, field="quality_policy", maximum=500)
