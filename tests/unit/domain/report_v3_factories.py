"""Synthetic version-three report bindings; no provider or persistence dependencies."""

from dataclasses import fields, replace
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading212_domain import report_v3 as v3
from trading212_domain import reports as r
from trading212_domain.report_manifest import (
    encode_report_proof,
    encode_report_schema,
    report_document_digest,
    report_table_digest,
)
from trading212_domain.report_schema import report_tables, table_schema

from tests.unit.domain.report_factories import AT, ZERO_DIGEST, _row, document, selection, uid


def selection_v3(*, risk: bool = False) -> v3.ReportSelectionV3:
    original = selection()
    return v3.ReportSelectionV3(
        **{
            x.name: getattr(original, x.name)
            for x in fields(original)
            if x.name not in {"risk_run_id", "sections"}
        },
        sections=(*original.sections, r.ReportSection.RISK if risk else r.ReportSection.SCENARIO),
        premium_run=v3.ReportRiskRunSelection(run_id=uid(90))
        if risk
        else v3.ReportScenarioRunSelection(run_id=uid(90)),
    )


def binding_v3(*, risk: bool = False) -> v3.ReportRiskRunBinding | v3.ReportScenarioRunBinding:
    chosen = selection_v3(risk=risk)
    original = document().capture
    common: dict[str, Any] = dict(
        run_id=uid(90),
        result_id=uid(91),
        input_digest="1" * 64,
        result_digest="2" * 64,
        owner_id=original.header.owner_id,
        account_id=chosen.account_id,
        snapshot_id=chosen.snapshot_id,
        snapshot_digest=ZERO_DIGEST,
        reporting_currency=chosen.reporting_currency,
        source_cutoff_at=AT,
        valuation_at=AT,
        created_at=AT + timedelta(days=1),
        completed_at=AT + timedelta(days=1, minutes=1),
        expires_at=AT + timedelta(days=8),
    )
    historical = v3.ReportHistoricalInputBinding(input_snapshot_id=uid(93), input_digest="3" * 64)
    if risk:
        return v3.ReportRiskRunBinding(
            **common,
            definition_id=uid(94),
            definition_version_id=uid(95),
            definition_digest="4" * 64,
            start_date=chosen.start_date,
            end_date=chosen.end_date,
            historical=historical,
        )
    return v3.ReportScenarioRunBinding(
        **common,
        scenario_id=uid(94),
        scenario_version_id=uid(95),
        scenario_version_digest="4" * 64,
        xray=v3.ReportXrayRunBinding(
            run_id=uid(96), input_id=uid(97), input_digest="5" * 64, result_digest="6" * 64
        ),
        historical=historical,
    )


def bindings_v3(
    pin: v3.ReportRiskRunBinding | v3.ReportScenarioRunBinding,
) -> tuple[r.ReportBinding, ...]:
    definition = (
        (pin.definition_version_id, pin.definition_digest, pin.definition_id)
        if isinstance(pin, v3.ReportRiskRunBinding)
        else (pin.scenario_version_id, pin.scenario_version_digest, pin.scenario_id)
    )
    values = [
        r.ReportBinding(
            family=pin.family,
            role=r.ReportInputRole.INPUT,
            subject_id=pin.run_id,
            content_digest=pin.input_digest,
        ),
        r.ReportBinding(
            family=pin.family,
            role=r.ReportInputRole.RESULT,
            subject_id=pin.result_id,
            content_digest=pin.result_digest,
            parent_id=pin.run_id,
        ),
        r.ReportBinding(
            family=pin.family,
            role=r.ReportInputRole.POLICY,
            subject_id=definition[0],
            content_digest=definition[1],
            parent_id=definition[2],
        ),
        r.ReportBinding(
            family=r.ReportFamily.SNAPSHOT,
            role=r.ReportInputRole.SNAPSHOT,
            subject_id=pin.snapshot_id,
            content_digest=pin.snapshot_digest,
        ),
    ]
    if pin.historical is not None:
        values.append(
            r.ReportBinding(
                family=r.ReportFamily.PERFORMANCE,
                role=r.ReportInputRole.INPUT,
                subject_id=pin.historical.input_snapshot_id,
                content_digest=pin.historical.input_digest,
            )
        )
    if pin.xray is not None:
        values.extend(
            [
                r.ReportBinding(
                    family=r.ReportFamily.XRAY,
                    role=r.ReportInputRole.INPUT,
                    subject_id=pin.xray.input_id,
                    content_digest=pin.xray.input_digest,
                ),
                r.ReportBinding(
                    family=r.ReportFamily.XRAY,
                    role=r.ReportInputRole.RESULT,
                    subject_id=pin.xray.run_id,
                    content_digest=pin.xray.result_digest,
                ),
            ]
        )
    return tuple(values)


def capture_v3(*, risk: bool = False) -> v3.ReportCaptureSummaryV3:
    original = document().capture
    chosen = selection_v3(risk=risk)
    pin = binding_v3(risk=risk)
    contexts = tuple(replace(x, schema_version="3.0.0") for x in original.proof.contexts)
    context = replace(
        contexts[0],
        key="premium.fixture",
        family=pin.family,
        method_key="risk_v1" if risk else "stress_v1",
    )
    proof = replace(original.proof, contexts=(*contexts, context))
    proof_digest = sha256(encode_report_proof(proof)).hexdigest()
    supplied = {x.table for x in original.header.tables}
    singletons = {
        r.ReportTableKey.SCENARIO_BASIS_V1,
        r.ReportTableKey.SCENARIO_DEFINITION_V1,
        r.ReportTableKey.SCENARIO_SUMMARY_V1,
    }
    descriptors = (
        *original.header.tables,
        *(
            r.ReportTableDescriptor(
                table=table,
                schema_digest=sha256(encode_report_schema(table_schema(table))).hexdigest(),
                row_count=1 if table in singletons else 0,
                content_digest=report_table_digest(
                    table, (_row(table),) if table in singletons else ()
                ),
            )
            for table in report_tables(chosen)
            if table not in supplied
        ),
    )
    header = v3.ReportDocumentHeaderV3(
        selection=chosen,
        owner_id=pin.owner_id,
        valuation_at=AT,
        context_digest=proof_digest,
        tables=descriptors,
        document_digest=ZERO_DIGEST,
        premium_binding=pin,
    )
    header = replace(header, document_digest=report_document_digest(header))
    return v3.ReportCaptureSummaryV3(
        header=header,
        canonical_byte_length=0,
        chunk_count=0,
        immutable_bindings=bindings_v3(pin),
        proof=proof,
        proof_digest=proof_digest,
        renderer_profile=original.renderer_profile,
        copy_expires_at=pin.expires_at,
    )
