"""Complete terminal evidence and licensed sensitivity relations for scenario reports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import fail_validation
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_sources import (
    ScenarioEntitySubject,
    ScenarioFactorEquivalence,
    ScenarioFxEquivalence,
    ScenarioInstrumentSubject,
    ScenarioPriceEquivalence,
    ScenarioRateEquivalence,
    ScenarioSensitivityCapture,
    ScenarioUnknownEquivalence,
)

from .report_capture_common import capture_note
from .report_capture_scenario_cells import ScenarioReportWriter


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSourceHeader(r.ReportRecord):
    source_kind: str
    subject_id: UUID
    content_digest: str
    created_at: datetime
    expires_at: datetime | None

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.source_kind not in {
            "scenario_sensitivity_version",
            "scenario_sensitivity_observation",
            "scenario_sensitivity_evidence",
        } or (self.source_kind == "scenario_sensitivity_version") != (self.expires_at is not None):
            fail_validation("Scenario source header kind/lifetime differs.", field="sources")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            fail_validation("Scenario source header lifetime is empty.", field="sources")


def coefficient_cell(
    writer: ScenarioReportWriter,
    value: Decimal | None,
    *,
    quality: QualityState,
    reason: ScenarioReason | None,
    confidence: Decimal | None = None,
) -> r.ReportCell:
    """A missing source coefficient remains unavailable, never structurally inapplicable."""
    note = None
    if value is None:
        code = ScenarioReason.MISSING_SENSITIVITY if reason is None else reason
        note = capture_note(
            writer.builder,
            writer.context,
            key=f"{writer.context.key}.reason.{code.value}",
            text=code.value,
            code=code.value,
        )
    return r.ReportCell(
        kind=r.CellKind.DECIMAL,
        decimal_role=r.DecimalRole.SCORE,
        value=value,
        state=r.CellState.UNAVAILABLE if value is None else r.CellState.AVAILABLE,
        reason_key=note,
        context_key=writer.context.key,
        quality=quality,
        confidence=confidence,
        origin=r.ReportMetricOrigin.NORMALIZED_PROVIDER,
        method_key=writer.context.method_key,
        method_version=writer.context.method_version,
        provenance_set_key=writer.context.provenance_set_key,
        coverage_key=writer.context.coverage_set_key,
        note_set_key=writer.context.note_set_key,
    )


def capture_scenario_component_proof(
    writer: ScenarioReportWriter, value: ScenarioCalculation
) -> None:
    def subjects() -> Iterable[r.ReportRow]:
        for index, component in enumerate(value.components):
            exposure = component.exposure
            writer.members(
                "exposure",
                writer.key(r.ReportTableKey.SCENARIO_COMPONENTS_V1, index),
                "source_reference_ids",
                exposure.source_reference_ids,
            )
            for subject in (exposure.instrument, exposure.entity):
                row = writer.row(
                    r.ReportTableKey.SCENARIO_SUBJECTS_V1,
                    f"{index}.{subject.dimension}",
                    subject,
                    extra={"path_key": exposure.path_key},
                )
                for field in ("identity_decision_ids", "source_reference_ids"):
                    writer.members("subject", row.key, field, getattr(subject, field))
                yield row

    writer.table(r.ReportTableKey.SCENARIO_SUBJECTS_V1, subjects())

    def classifications() -> Iterable[r.ReportRow]:
        for index, component in enumerate(value.components):
            for fact in (component.exposure.sector, component.exposure.region):
                row = writer.row(
                    r.ReportTableKey.SCENARIO_CLASSIFICATIONS_V1,
                    f"{index}.{fact.dimension}",
                    fact,
                    extra={"path_key": component.exposure.path_key},
                )
                for field in ("assignment_ids", "evidence_ids", "source_reference_ids"):
                    writer.members("classification", row.key, field, getattr(fact, field))
                yield row

    writer.table(r.ReportTableKey.SCENARIO_CLASSIFICATIONS_V1, classifications())

    def currencies() -> Iterable[r.ReportRow]:
        for index, component in enumerate(value.components):
            fact = component.exposure.economic_currency
            row = writer.row(
                r.ReportTableKey.SCENARIO_CURRENCIES_V1,
                index,
                fact,
                extra={
                    "path_key": component.exposure.path_key,
                    "currency": None if fact.currency is None else fact.currency.value,
                },
            )
            for field in ("assignment_ids", "evidence_ids", "source_reference_ids"):
                writer.members("economic_currency", row.key, field, getattr(fact, field))
            yield row

    writer.table(r.ReportTableKey.SCENARIO_CURRENCIES_V1, currencies())
    for index, component in enumerate(value.components):
        for field in ("matching_exclusion_keys", "uncertain_rule_keys", "diagnostic_keys"):
            writer.members(
                "component",
                writer.key(r.ReportTableKey.SCENARIO_COMPONENTS_V1, index),
                field,
                getattr(component, field),
            )


def capture_scenario_source_proof(
    writer: ScenarioReportWriter, value: ScenarioSensitivityCapture
) -> None:
    from .report_capture_scenario import selector_values

    writer.table(
        r.ReportTableKey.SCENARIO_SENSITIVITY_VERSIONS_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_SENSITIVITY_VERSIONS_V1,
                index,
                item,
                extra={
                    "driver_id": item.driver.driver_id,
                    "driver_definition_version_id": item.driver.definition_version_id,
                },
            )
            for index, item in enumerate(value.versions)
        ),
    )

    def drivers() -> Iterable[r.ReportRow]:
        for index, version in enumerate(value.versions):
            driver, equivalence = version.driver, version.driver.equivalence
            selector = (
                equivalence.selector if isinstance(equivalence, ScenarioPriceEquivalence) else None
            )
            data = selector_values(selector)
            row = writer.row(
                r.ReportTableKey.SCENARIO_DRIVERS_V1,
                index,
                driver,
                extra={
                    **data,
                    "version_id": version.version_id,
                    "equivalence_kind": equivalence.kind,
                    "rate_id": equivalence.rate_id
                    if isinstance(equivalence, ScenarioRateEquivalence)
                    else None,
                    "factor_id": equivalence.factor_id
                    if isinstance(equivalence, ScenarioFactorEquivalence)
                    else None,
                    "currency": equivalence.currency.value
                    if isinstance(equivalence, (ScenarioRateEquivalence, ScenarioFxEquivalence))
                    else None,
                    "reason": equivalence.reason
                    if isinstance(equivalence, ScenarioUnknownEquivalence)
                    else None,
                },
            )
            writer.members(
                "sensitivity_driver",
                row.key,
                "evidence_reference_ids",
                driver.evidence_reference_ids,
            )
            yield row

    writer.table(r.ReportTableKey.SCENARIO_DRIVERS_V1, drivers())

    def observations() -> Iterable[r.ReportRow]:
        for index, item in enumerate(value.observations):
            subject = item.subject
            if isinstance(subject, ScenarioInstrumentSubject):
                identifier = subject.instrument_id
            elif isinstance(subject, ScenarioEntitySubject):
                identifier = subject.entity_id
            else:
                fail_validation("Scenario sensitivity subject differs.")
            row = writer.row(
                r.ReportTableKey.SCENARIO_SENSITIVITY_OBSERVATIONS_V1,
                index,
                item,
                extra={
                    "subject_kind": subject.kind,
                    "subject_id": identifier,
                    "response_currency": None
                    if item.response_currency is None
                    else item.response_currency.value,
                    "coefficient": coefficient_cell(
                        writer,
                        item.coefficient,
                        quality=item.quality,
                        reason=item.reason,
                        confidence=item.confidence,
                    ),
                },
            )
            writer.members(
                "sensitivity_observation",
                row.key,
                "evidence_reference_ids",
                item.evidence_reference_ids,
            )
            yield row

    writer.table(r.ReportTableKey.SCENARIO_SENSITIVITY_OBSERVATIONS_V1, observations())
    writer.table(
        r.ReportTableKey.SCENARIO_SENSITIVITY_MEMBERSHIPS_V1,
        (
            writer.row(r.ReportTableKey.SCENARIO_SENSITIVITY_MEMBERSHIPS_V1, i, item)
            for i, item in enumerate(value.memberships)
        ),
    )
    writer.table(
        r.ReportTableKey.SCENARIO_SENSITIVITY_EVIDENCE_V1,
        (
            writer.row(r.ReportTableKey.SCENARIO_SENSITIVITY_EVIDENCE_V1, i, item)
            for i, item in enumerate(value.evidence)
        ),
    )
    writer.table(
        r.ReportTableKey.SCENARIO_SOURCE_LICENSES_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_SOURCE_LICENSES_V1,
                i,
                item.license,
                extra={"license_version_id": item.license_version_id},
            )
            for i, item in enumerate(value.licenses)
        ),
    )


def capture_scenario_source_headers(
    writer: ScenarioReportWriter,
    value: ScenarioSensitivityCapture,
    headers: tuple[ScenarioSourceHeader, ...],
) -> None:
    expected = {
        **{
            ("scenario_sensitivity_version", row.version_id): row.content_digest
            for row in value.versions
        },
        **{
            ("scenario_sensitivity_observation", row.observation_id): row.content_digest
            for row in value.observations
        },
        **{("scenario_sensitivity_evidence", row.id): row.content_digest for row in value.evidence},
    }
    actual = {(row.source_kind, row.subject_id): row.content_digest for row in headers}
    if len(actual) != len(headers) or actual != expected:
        fail_validation("Scenario original source header inventory differs.", field="sources")
    writer.table(
        r.ReportTableKey.SCENARIO_SOURCE_HEADERS_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_SOURCE_HEADERS_V1,
                i,
                extra={
                    "source_kind": row.source_kind,
                    "subject_id": row.subject_id,
                    "content_digest": row.content_digest,
                    "created_at": row.created_at,
                    "expires_at": row.expires_at,
                },
            )
            for i, row in enumerate(
                sorted(headers, key=lambda item: (item.source_kind, item.subject_id))
            )
        ),
    )
