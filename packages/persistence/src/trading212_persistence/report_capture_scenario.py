"""Lossless tables for one authorized saved scenario; no calculation or private reads."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_v3 import (
    ReportHistoricalInputBinding,
    ReportScenarioRunBinding,
    ReportScenarioRunSelection,
    ReportSelectionV3,
    ReportXrayRunBinding,
)
from trading212_domain.scenario import (
    SCENARIO_METHOD,
    ScenarioComponentSelector,
    ScenarioCurrencySelector,
    ScenarioEntitySelector,
    ScenarioFactorShock,
    ScenarioInstrumentSelector,
    ScenarioRateShock,
    ScenarioRegionSelector,
    ScenarioSectorSelector,
    scenario_exclusion_key,
    scenario_rule_key,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.scenario_result import ScenarioCalculation, ScenarioChannelEffects
from trading212_domain.scenario_serialization import (
    encode_scenario_execution,
    scenario_result_digest,
)
from trading212_domain.scenario_sources import sensitivity_row_count

from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note
from .report_capture_scenario_cells import ScenarioReportWriter
from .report_capture_scenario_proof import (
    capture_scenario_component_proof,
    capture_scenario_source_proof,
    coefficient_cell,
)
from .report_capture_scenario_replay import capture_scenario_replay


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioReportMetadata(r.ReportRecord):
    run_id: UUID
    result_id: UUID
    result_digest: str
    scenario_version_number: int
    created_at: datetime
    completed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if (
            not 1 <= self.scenario_version_number <= 512
            or not self.created_at <= self.completed_at < self.expires_at
        ):
            fail_validation("Scenario report metadata differs.", field="scenario_run_id")


def selector_values(value: ScenarioComponentSelector | None) -> dict[str, ReportValue]:
    return {
        "selector_kind": None if value is None else value.kind,
        "instrument_id": value.instrument_id
        if isinstance(value, ScenarioInstrumentSelector)
        else None,
        "entity_id": value.entity_id if isinstance(value, ScenarioEntitySelector) else None,
        "taxonomy_id": value.taxonomy_id
        if isinstance(value, (ScenarioSectorSelector, ScenarioRegionSelector))
        else None,
        "taxonomy_version": value.taxonomy_version
        if isinstance(value, (ScenarioSectorSelector, ScenarioRegionSelector))
        else None,
        "bucket_key": value.bucket_key
        if isinstance(value, (ScenarioSectorSelector, ScenarioRegionSelector))
        else None,
        "currency": value.currency.value if isinstance(value, ScenarioCurrencySelector) else None,
    }


def _check(
    builder: ReportBuilder,
    value: ScenarioCalculation,
    execution: ScenarioExecutionInput,
    metadata: ScenarioReportMetadata,
) -> None:
    # Admit the complete aggregate before expanding candidate or source maps.
    sensitivity_row_count(
        execution.sensitivities,
        applied_uses=sum(len(item.sensitivity_uses) for item in value.components),
    )
    licenses = {item.license_version_id for item in execution.sensitivities.licenses}
    licenses.update(
        item.license_version_id
        for item in execution.xray_input.source_dependencies
        if item.license_version_id is not None
    )
    if execution.replay is not None:
        licenses.update(
            UUID(item.id)
            for item in execution.replay.historical_input.sources
            if item.kind == "provider_license_version"
        )
    r.report_limit(len(licenses) <= 256, "licenses")
    encode_scenario_execution(execution)
    selection, pins = builder.selection, execution.pins
    if not isinstance(selection, ReportSelectionV3) or not isinstance(
        selection.premium_run, ReportScenarioRunSelection
    ):
        fail_validation(
            "An explicit scenario report selection is required.", field="scenario_run_id"
        )
    if (
        selection.premium_run.run_id != metadata.run_id
        or r.ReportSection.SCENARIO not in selection.sections
        or pins.owner_id != builder.owner_id
        or pins.account_id != selection.account_id
        or pins.portfolio_snapshot_id != selection.snapshot_id
        or pins.reporting_currency != selection.reporting_currency
        or pins.source_cutoff_at != selection.source_cutoff_at
        or metadata.expires_at != execution.expires_at
        or value.pins != pins
        or value.input_digest != execution.input_digest
        or value.definition != execution.definition
        or value.sensitivity_source_row_count != sensitivity_row_count(execution.sensitivities)
        or value.valuation_at != execution.xray_input.valuation_at.value
        or builder.valuation_at != value.valuation_at
        or metadata.result_digest != scenario_result_digest(value)
        or (value.replay is None) != (execution.replay is None)
        or tuple(item.exposure for item in value.components)
        != extract_scenario_exposures(execution.xray_input, execution.xray_result)
    ):
        fail_validation("Scenario report differs from its retained run.", field="scenario_run_id")
    if (
        execution.replay is not None
        and value.replay is not None
        and (
            value.replay.selection != execution.replay.selection
            or selection.start_date != execution.replay.selection.start_date
            or selection.end_date != execution.replay.selection.end_date
            or value.replay.holdings_evidence_at != execution.replay.holdings_evidence_at
            or value.replay.holdings_knowledge_cutoff_at
            != execution.replay.holdings_knowledge_cutoff_at
            or value.replay.context.input_digest != execution.replay.historical_input_digest
        )
    ):
        fail_validation("Scenario replay report window differs.", field="scenario_run_id")


def scenario_report_context(
    value: ScenarioCalculation, metadata: ScenarioReportMetadata
) -> r.ReportContext:
    prefix = f"scenario.{metadata.run_id}"
    return r.ReportContext(
        key=prefix,
        family=r.ReportFamily.SCENARIO,
        method_key=SCENARIO_METHOD,
        method_version=value.method_version,
        valuation_at=value.valuation_at,
        source_cutoff_at=value.pins.source_cutoff_at,
        quality=value.summary.post_value.quality,
        provenance_set_key=f"{prefix}.sources",
        coverage_set_key=f"{prefix}.coverage",
        note_set_key=f"{prefix}.notes",
        schema_version="3.0.0",
    )


def project_scenario(
    builder: ReportBuilder,
    value: ScenarioCalculation,
    execution: ScenarioExecutionInput,
    metadata: ScenarioReportMetadata,
) -> r.ReportContext:
    """Copy the canonical values after the loader registers all authorized source headers."""
    _check(builder, value, execution, metadata)
    builder.limit_copy_expiry(min(metadata.expires_at, execution.expires_at))
    context = scenario_report_context(value, metadata)
    prefix = context.key
    builder.add_context(context)
    writer = ScenarioReportWriter(builder, context)
    pins = value.pins
    writer.table(
        r.ReportTableKey.SCENARIO_BASIS_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_BASIS_V1,
                source=pins,
                extra={
                    "run_id": metadata.run_id,
                    "result_id": metadata.result_id,
                    "result_digest": metadata.result_digest,
                    "input_digest": execution.input_digest,
                    "scenario_version_number": metadata.scenario_version_number,
                    "reporting_currency": pins.reporting_currency.value,
                    "valuation_at": value.valuation_at,
                    "created_at": metadata.created_at,
                    "completed_at": metadata.completed_at,
                    "expires_at": metadata.expires_at,
                    "family": value.family,
                    "method": value.method,
                    "method_version": value.method_version,
                    "schema_version": value.schema_version,
                    "numerical_profile": value.numerical_profile,
                    "sensitivity_source_row_count": value.sensitivity_source_row_count,
                    "replay_selected": value.replay is not None,
                },
            ),
        ),
        analytical=True,
    )
    writer.table(
        r.ReportTableKey.SCENARIO_DEFINITION_V1,
        (writer.row(r.ReportTableKey.SCENARIO_DEFINITION_V1, source=value.definition),),
        analytical=True,
    )

    def shocks() -> Iterable[r.ReportRow]:
        for ordinal, shock in enumerate(value.definition.shocks):
            pin = (
                shock.source
                if isinstance(shock, (ScenarioRateShock, ScenarioFactorShock))
                else None
            )
            selector = (
                shock.selector
                if not isinstance(shock, (ScenarioRateShock, ScenarioFactorShock))
                else None
            )
            yield writer.row(
                r.ReportTableKey.SCENARIO_SHOCKS_V1,
                ordinal,
                extra={
                    **selector_values(selector),
                    "ordinal": ordinal,
                    "rule_key": scenario_rule_key(shock),
                    "kind": shock.kind,
                    "size": shock.size,
                    "sensitivity_version_id": None if pin is None else pin.version_id,
                    "sensitivity_content_digest": None if pin is None else pin.content_digest,
                    "driver_id": None if pin is None else pin.driver_id,
                    "driver_definition_version_id": None
                    if pin is None
                    else pin.driver_definition_version_id,
                },
            )

    writer.table(r.ReportTableKey.SCENARIO_SHOCKS_V1, shocks(), analytical=True)
    writer.table(
        r.ReportTableKey.SCENARIO_EXCLUSIONS_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_EXCLUSIONS_V1,
                i,
                extra={
                    **selector_values(item.selector),
                    "ordinal": i,
                    "rule_key": scenario_exclusion_key(item),
                },
            )
            for i, item in enumerate(value.definition.exclusions)
        ),
        analytical=True,
    )
    writer.table(
        r.ReportTableKey.SCENARIO_SUMMARY_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_SUMMARY_V1,
                source=value.summary,
                extra={
                    "upstream_portfolio_value": value.upstream_portfolio_value,
                    "upstream_partition_difference": value.upstream_partition_difference,
                },
            ),
        ),
        analytical=True,
    )

    def components() -> Iterable[r.ReportRow]:
        for ordinal, item in enumerate(value.components):
            yield writer.row(
                r.ReportTableKey.SCENARIO_COMPONENTS_V1,
                ordinal,
                item.exposure,
                extra={
                    "ordinal": ordinal,
                    "partition": item.partition,
                    "winning_price_rule_key": item.winning_price_rule_key,
                    "post_value": item.post_value,
                    "impact": item.impact,
                    "rounding_residual": item.rounding_residual,
                    "money_basis": item.money_basis,
                    "exposure_quality": item.exposure.quality,
                    "exposure_confidence": item.exposure.confidence,
                },
            )

    writer.table(r.ReportTableKey.SCENARIO_COMPONENTS_V1, components(), analytical=True)

    def channels() -> Iterable[r.ReportRow]:
        effects: Iterable[tuple[str, str | None, ScenarioChannelEffects]] = chain(
            (("summary", None, value.summary.effects),),
            (("component", item.exposure.path_key, item.effects) for item in value.components),
        )
        for scope, path, effect in effects:
            for channel in ("price", "factor", "fx", "interaction"):
                yield writer.row(
                    r.ReportTableKey.SCENARIO_CHANNELS_V1,
                    f"{scope}.{0 if path is None else next_index[path]}.{channel}",
                    extra={
                        "scope": scope,
                        "path_key": path,
                        "channel": channel,
                        "ratio": None
                        if channel == "interaction"
                        else getattr(effect, f"{channel}_ratio"),
                        "effect": getattr(effect, channel),
                    },
                )

    next_index = {item.exposure.path_key: i for i, item in enumerate(value.components)}
    writer.table(r.ReportTableKey.SCENARIO_CHANNELS_V1, channels(), analytical=True)

    def applied() -> Iterable[r.ReportRow]:
        for component_index, component in enumerate(value.components):
            for ordinal, use in enumerate(component.sensitivity_uses):
                key = f"{component_index}.{ordinal}"
                row = writer.row(
                    r.ReportTableKey.SCENARIO_APPLIED_SENSITIVITIES_V1,
                    key,
                    use,
                    extra={
                        "path_key": component.exposure.path_key,
                        "ordinal": ordinal,
                        "driver_id": use.driver.driver_id,
                        "driver_definition_version_id": use.driver.definition_version_id,
                        "driver_definition_digest": use.driver.definition_digest,
                        "driver_kind": use.driver.kind,
                        "shock_unit": use.driver.shock_unit,
                        "coefficient": coefficient_cell(
                            writer,
                            use.coefficient,
                            quality=use.effect_ratio.quality,
                            reason=use.reason,
                        ),
                    },
                )
                writer.members(
                    "applied_sensitivity",
                    row.key,
                    "candidate_observation_ids",
                    use.candidate_observation_ids,
                )
                writer.members(
                    "applied_sensitivity",
                    row.key,
                    "evidence_reference_ids",
                    use.driver.evidence_reference_ids,
                )
                yield row

    writer.table(r.ReportTableKey.SCENARIO_APPLIED_SENSITIVITIES_V1, applied(), analytical=True)
    diagnostics = (
        ("calculation", value.diagnostics),
        ("replay", () if value.replay is None else value.replay.diagnostics),
    )

    def diagnostic_rows() -> Iterable[r.ReportRow]:
        for scope, items in diagnostics:
            for ordinal, issue in enumerate(items):
                row = writer.row(
                    r.ReportTableKey.SCENARIO_DIAGNOSTICS_V1,
                    f"{scope}.{ordinal}",
                    issue,
                    extra={"scope": scope, "ordinal": ordinal, "diagnostic_key": issue.key},
                )
                writer.members(
                    "diagnostic", row.key, "source_reference_ids", issue.source_reference_ids
                )
                writer.members("diagnostic", row.key, "source_use_keys", issue.source_use_keys)
                yield row

    writer.table(r.ReportTableKey.SCENARIO_DIAGNOSTICS_V1, diagnostic_rows(), analytical=True)
    writer.members("calculation", prefix, "upstream_residual_keys", value.upstream_residual_keys)
    writer.members("calculation", prefix, "assumptions", value.assumptions)
    for assumption in value.assumptions:
        capture_note(
            builder,
            context,
            key=f"{prefix}.assumption.{assumption.value}",
            text=assumption.value,
            code=assumption.value,
            kind=r.ReportNoteKind.ASSUMPTION,
        )
    for name in (
        "covered_count",
        "uncovered_count",
        "excluded_count",
        "missing_pre_value_count",
        "uncertain_money_count",
    ):
        builder.add_coverage(
            r.ReportCoverageFact(
                set_key=context.coverage_set_key,
                family=r.ReportFamily.SCENARIO,
                metric_key=name,
                value=r.ReportCell(
                    kind=r.CellKind.INTEGER,
                    value=getattr(value.summary, name),
                    context_key=context.key,
                ),
            )
        )
    for role, subject, content, parent in (
        (r.ReportInputRole.INPUT, metadata.run_id, execution.input_digest, None),
        (r.ReportInputRole.RESULT, metadata.result_id, metadata.result_digest, metadata.run_id),
        (
            r.ReportInputRole.POLICY,
            pins.scenario_version_id,
            pins.scenario_version_digest,
            pins.scenario_id,
        ),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=r.ReportFamily.SCENARIO,
                role=role,
                subject_id=subject,
                content_digest=content,
                parent_id=parent,
                method_key=SCENARIO_METHOD,
                method_version=value.method_version,
            )
        )
    capture_scenario_component_proof(writer, value)
    capture_scenario_source_proof(writer, execution.sensitivities)
    capture_scenario_replay(writer, value, execution)
    if r.ReportTableKey.SCENARIO_MEMBERS_V1 not in builder.proof_table_keys:
        writer.table(r.ReportTableKey.SCENARIO_MEMBERS_V1, ())
    return context


def scenario_report_binding(
    value: ScenarioCalculation, execution: ScenarioExecutionInput, metadata: ScenarioReportMetadata
) -> ReportScenarioRunBinding:
    """The typed V3 header binding uses the actual selected scenario and saved parents."""
    pins = execution.pins
    return ReportScenarioRunBinding(
        run_id=metadata.run_id,
        result_id=metadata.result_id,
        input_digest=execution.input_digest,
        result_digest=metadata.result_digest,
        owner_id=pins.owner_id,
        account_id=pins.account_id,
        snapshot_id=pins.portfolio_snapshot_id,
        snapshot_digest=pins.portfolio_snapshot_digest,
        reporting_currency=pins.reporting_currency,
        source_cutoff_at=pins.source_cutoff_at,
        valuation_at=value.valuation_at,
        created_at=metadata.created_at,
        completed_at=metadata.completed_at,
        expires_at=metadata.expires_at,
        scenario_id=pins.scenario_id,
        scenario_version_id=pins.scenario_version_id,
        scenario_version_digest=pins.scenario_version_digest,
        xray=ReportXrayRunBinding(
            run_id=pins.xray_run_id,
            input_id=pins.xray_input_id,
            input_digest=pins.xray_input_digest,
            result_digest=pins.xray_result_digest,
        ),
        historical=None
        if execution.replay is None
        else ReportHistoricalInputBinding(
            input_snapshot_id=execution.replay.selection.historical_input_snapshot_id,
            input_digest=execution.replay.historical_input_digest,
        ),
    )
