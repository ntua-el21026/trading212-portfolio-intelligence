"""Complete X-ray report projection; all money and overlap comes from the kernel."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from functools import cache
from itertools import combinations
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.xray import calculate_common_entities
from trading212_application import xray as app
from trading212_domain import reports as r
from trading212_domain import xray as d
from trading212_domain import xray_result as x
from trading212_domain.errors import fail_validation
from trading212_domain.report_manifest import encode_report_row
from trading212_domain.report_schema import report_tables, table_schema
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode, Instant
from trading212_domain.xray_codec import decode_xray_input, encode_xray_policy

from . import source_models as sm
from . import xray_catalog_models as cm
from .historical_base import digest
from .report_authorization import ReportAuthorization
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row, capture_table
from .xray_service import PostgresXrayService

_SOURCE_KINDS = {
    d.XrayReferenceKind.SNAPSHOT_POSITION: r.ReportSourceKind.SNAPSHOT_POSITION,
    d.XrayReferenceKind.SNAPSHOT_CASH: r.ReportSourceKind.SNAPSHOT_CASH,
    d.XrayReferenceKind.PORTFOLIO_SNAPSHOT: r.ReportSourceKind.PORTFOLIO_SNAPSHOT,
    d.XrayReferenceKind.CALCULATION_RUN: r.ReportSourceKind.CALCULATION,
    d.XrayReferenceKind.BROKER_SOURCE_RECORD: r.ReportSourceKind.BROKER_SOURCE_RECORD,
    d.XrayReferenceKind.RECONCILIATION_RUN: r.ReportSourceKind.RECONCILIATION,
    d.XrayReferenceKind.RECONCILIATION_DISCREPANCY: r.ReportSourceKind.RECONCILIATION_DISCREPANCY,
    d.XrayReferenceKind.OWNER_POLICY: r.ReportSourceKind.POLICY,
    d.XrayReferenceKind.PRICE_SNAPSHOT: r.ReportSourceKind.PRICE_SNAPSHOT,
    d.XrayReferenceKind.PRICE_OBSERVATION: r.ReportSourceKind.PRICE_OBSERVATION,
    d.XrayReferenceKind.FX_SNAPSHOT: r.ReportSourceKind.FX_SNAPSHOT,
    d.XrayReferenceKind.FX_OBSERVATION: r.ReportSourceKind.FX_OBSERVATION,
    d.XrayReferenceKind.FX_COVERAGE_GAP: r.ReportSourceKind.FX_COVERAGE_GAP,
    d.XrayReferenceKind.FUND_DEFINITION: r.ReportSourceKind.FUND_DEFINITION,
    d.XrayReferenceKind.FUND_MAPPING: r.ReportSourceKind.FUND_MAPPING,
    d.XrayReferenceKind.CONSTITUENT_SNAPSHOT: r.ReportSourceKind.CONSTITUENT_SNAPSHOT,
    d.XrayReferenceKind.CONSTITUENT_HOLDING: r.ReportSourceKind.CONSTITUENT_HOLDING,
    d.XrayReferenceKind.ENTITY_EVIDENCE_VERSION: r.ReportSourceKind.ENTITY_EVIDENCE_VERSION,
    d.XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE: r.ReportSourceKind.ENTITY_EVIDENCE_REFERENCE,
    d.XrayReferenceKind.RELATIONSHIP: r.ReportSourceKind.RELATIONSHIP,
    d.XrayReferenceKind.CLASSIFICATION_SNAPSHOT: r.ReportSourceKind.CLASSIFICATION_SNAPSHOT,
    d.XrayReferenceKind.CLASSIFICATION_ASSIGNMENT: r.ReportSourceKind.CLASSIFICATION_ASSIGNMENT,
}
type XrayRow = (
    x.XrayPortfolioSummary
    | x.XrayQualityCoverage
    | x.XrayDimensionSummary
    | x.XrayExposureBucket
    | x.XrayTerminalPath
    | x.FundComposition
    | x.CanonicalOverlapPair
    | x.CanonicalCommonEntity
    | x.XrayTopConcentration
    | x.XrayThresholdConclusion
    | x.XrayDisplayResidual
    | x.XraySelection
    | x.XraySourceUse
    | x.XrayFundEdge
    | x.XrayPathClassification
    | x.XrayClassificationDecision
    | d.XrayBrokerFx
    | d.XrayFxLeg
)
type XrayValue = ReportValue | d.XrayMoneyMetric | d.XrayRatioMetric | CurrencyCode | Instant


def _source_key(identifier: UUID) -> str:
    return f"xray.source.{identifier}"


def _metric(
    builder: ReportBuilder,
    context: r.ReportContext,
    key: str,
    value: d.XrayMoneyMetric | d.XrayRatioMetric,
    *,
    missing_currency: CurrencyCode | None = None,
) -> r.ReportCell:
    reason = None
    if value.reason is not None:
        reason = f"xray.reason.{value.reason.value}"
        capture_note(builder, context, key=reason, text=value.reason.value, code=value.reason.value)
    positive = isinstance(value, d.XrayRatioMetric) and value.positive_below_quantum
    kind = (
        r.ReportBoundKind.UNAVAILABLE
        if value.value is None
        else r.ReportBoundKind(value.bound.value)
    )
    bound_key = f"xray.bound.{kind.value}.{str(positive).lower()}"
    builder.add_bound(
        r.ReportBoundFact(
            key=bound_key,
            family=r.ReportFamily.XRAY,
            kind=kind,
            quantum=Decimal("0.000000000000000001"),
            rounding="ROUND_HALF_EVEN",
            positive_below_quantum=positive,
        )
    )
    provenance = f"xray.metric.sources.{digest(value.source_reference_ids)}"
    if not value.source_reference_ids:
        # An explicit empty metric source set must not inherit the root's sources.
        builder.add_context(
            replace(context, key=f"{context.key}.unsourced", provenance_set_key=provenance)
        )
    for identifier in value.source_reference_ids:
        reference = builder.references.get(_source_key(identifier))
        if reference is None:
            fail_validation("X-ray metric source reference is unresolved.", field="sources")
        builder.add_reference(reference, provenance_set_key=provenance)
    if isinstance(value, d.XrayMoneyMetric):
        amount = None if value.value is None else value.value.amount
        currency = (
            (missing_currency or builder.selection.reporting_currency)
            if value.value is None
            else value.value.currency
        )
        role = r.DecimalRole.MONEY
        origin = r.ReportMetricOrigin(value.origin.value)
    else:
        amount = value.value
        currency = None
        role = r.DecimalRole.RATIO
        origin = None
    return r.ReportCell(
        kind=r.CellKind.DECIMAL,
        value=amount,
        state=r.CellState(value.availability.value),
        decimal_role=role,
        currency=currency,
        context_key=context.key,
        reason_key=reason,
        bound_key=bound_key,
        quality=value.quality,
        origin=origin,
        confidence=value.confidence,
        method_key=context.method_key,
        method_version=context.method_version,
        provenance_set_key=provenance,
        note_set_key=context.note_set_key,
    )


def _row(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    source: XrayRow | None = None,
    *,
    extra: Mapping[str, XrayValue] | None = None,
) -> r.ReportRow:
    supplied = extra or {}
    values: dict[str, ReportValue] = {}
    for column in table_schema(table).columns:
        value = supplied[column.key] if column.key in supplied else getattr(source, column.key)
        if isinstance(value, (d.XrayMoneyMetric, d.XrayRatioMetric)):
            values[column.key] = _metric(builder, context, f"{key}.{column.key}", value)
        elif isinstance(value, (CurrencyCode, Instant)):
            values[column.key] = value.value
        else:
            values[column.key] = value
    return capture_row(
        builder,
        context,
        table,
        key=key,
        values=values,
        currency=builder.selection.reporting_currency,
    )


def _proof(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    source: XrayRow | None = None,
    *,
    extra: Mapping[str, XrayValue] | None = None,
) -> None:
    builder.add_proof(
        r.ReportProofRelation(
            table=table, row=_row(builder, context, table, key, source, extra=extra)
        )
    )


def _input_proof(builder: ReportBuilder, context: r.ReportContext, value: d.XrayInput) -> None:
    capture_note(
        builder,
        context,
        key="xray.numeric_policy",
        text=value.policy.numeric_policy,
        kind=r.ReportNoteKind.ASSUMPTION,
        code="canonical_numeric_policy",
    )
    valuation_roots: tuple[d.XrayPosition | d.XrayCash, ...] = (*value.positions, *value.cash)
    for item in valuation_roots:
        root = item.root
        position = root if isinstance(root, d.PositionRoot) else None
        cash = root if isinstance(root, d.CashRoot) else None
        _proof(
            builder,
            context,
            r.ReportTableKey.XRAY_VALUATION_ROOTS,
            f"xray.root.{root.key}",
            extra={
                "root_key": root.key,
                "root_kind": "position" if position else "cash",
                "position_id": None if position is None else position.position_id,
                "snapshot_cash_id": None if cash is None else cash.snapshot_cash_id,
                "instrument_id": None if position is None else position.instrument_id,
                "listing_id": None if position is None else position.listing_id,
                "original_value": _metric(
                    builder,
                    context,
                    f"xray.root.{root.key}.original_value",
                    item.original_value,
                    missing_currency=None if cash is None else cash.original_currency,
                ),
                "reporting_value": item.reporting_value,
            },
        )
    for index, broker in enumerate(value.broker_fx):
        _proof(builder, context, r.ReportTableKey.XRAY_BROKER_FX, f"xray.broker_fx.{index}", broker)
    for index, attempt in enumerate(value.licensed_fx):
        _proof(
            builder,
            context,
            r.ReportTableKey.XRAY_LICENSED_FX,
            f"xray.licensed_fx.{index}",
            extra={
                "consumer_key": attempt.consumer_key,
                "input_value": attempt.input_value,
                "output_currency": attempt.output_currency,
                "leg_count": len(attempt.legs),
            },
        )
        for ordinal, leg in enumerate(attempt.legs):
            _proof(
                builder,
                context,
                r.ReportTableKey.XRAY_FX_LEGS,
                f"xray.licensed_fx.{index}.leg.{ordinal}",
                leg,
                extra={"consumer_key": attempt.consumer_key, "ordinal": ordinal},
            )
    for dependency in value.source_dependencies:
        _proof(
            builder,
            context,
            r.ReportTableKey.XRAY_DEPENDENCY_IDENTITIES,
            f"xray.dependency.{dependency.id}",
            extra={
                "source_key": _source_key(dependency.id),
                "dependency_id": dependency.id,
                "kind": dependency.kind,
                "subject_kind": dependency.subject_kind,
                "subject_id": dependency.subject_id,
                "physical_kind": dependency.reference.kind,
                "physical_record_id": dependency.reference.record_id,
                "physical_parent_id": dependency.reference.parent_record_id,
            },
        )
    _proof(
        builder,
        context,
        r.ReportTableKey.XRAY_RECONCILIATION,
        "xray.reconciliation",
        extra={
            "declared_total": value.reconciliation.declared_total,
            "root_total": value.reconciliation.root_total,
            "difference": value.reconciliation.difference,
        },
    )


def _result_proof(
    builder: ReportBuilder, context: r.ReportContext, result: x.XrayCalculation
) -> None:
    for selection in result.selections:
        key = f"xray.selection.{selection.key}"
        _proof(builder, context, r.ReportTableKey.XRAY_SELECTIONS, key, selection)
        for role, ids in (
            ("candidate", selection.candidate_evidence_ids),
            ("selected", selection.selected_evidence_ids),
        ):
            for ordinal, identifier in enumerate(ids):
                _proof(
                    builder,
                    context,
                    r.ReportTableKey.XRAY_SELECTION_EVIDENCE,
                    f"{key}.{role}.{ordinal}",
                    extra={
                        "selection_key": selection.key,
                        "role": role,
                        "ordinal": ordinal,
                        "evidence_id": identifier,
                    },
                )
    for ordinal, use in enumerate(result.typed_source_uses):
        _proof(builder, context, r.ReportTableKey.XRAY_SOURCE_USES, f"xray.use.{ordinal}", use)
    for decision in result.classification_decisions:
        key = f"xray.classification.{decision.key}"
        _proof(builder, context, r.ReportTableKey.XRAY_CLASSIFICATION_DECISIONS, key, decision)
        for role, identifiers in (
            ("assignment", decision.assignment_ids),
            ("evidence", decision.evidence_ids),
            ("source", decision.source_reference_ids),
        ):
            for ordinal, identifier in enumerate(identifiers):
                _proof(
                    builder,
                    context,
                    r.ReportTableKey.XRAY_CLASSIFICATION_MEMBERSHIPS,
                    f"{key}.{role}.{ordinal}",
                    extra={
                        "decision_key": decision.key,
                        "role": role,
                        "ordinal": ordinal,
                        "reference_id": identifier,
                    },
                )
    for path in result.terminal_paths:
        for ordinal, edge in enumerate(path.fund_edges):
            _proof(
                builder,
                context,
                r.ReportTableKey.XRAY_FUND_EDGES,
                f"xray.path.{path.key}.edge.{ordinal}",
                edge,
                extra={"path_key": path.key, "ordinal": ordinal},
            )
        for classification in path.classifications:
            _proof(
                builder,
                context,
                r.ReportTableKey.XRAY_PATH_CLASSIFICATIONS,
                f"xray.path.{path.key}.{classification.dimension.value}",
                classification,
                extra={"path_key": path.key},
            )
        relations: tuple[tuple[str, tuple[str | UUID, ...]], ...] = (
            (
                "fund_edge",
                tuple(f"xray.path.{path.key}.edge.{i}" for i in range(len(path.fund_edges))),
            ),
            ("identity_decision", path.identity_decision_ids),
            ("source", path.source_reference_ids),
            (
                "classification",
                tuple(
                    item.decision_key
                    for item in path.classifications
                    if item.decision_key is not None
                ),
            ),
        )
        for kind, relation_identifiers in relations:
            for ordinal, relation_id in enumerate(relation_identifiers):
                row = _row(
                    builder,
                    context,
                    r.ReportTableKey.XRAY_PATH_RELATIONS,
                    f"xray.path.{path.key}.{kind}.{ordinal}",
                    extra={
                        "path_key": path.key,
                        "relation_kind": kind,
                        "ordinal": ordinal,
                        "referenced_key": relation_id,
                    },
                )
                builder.add_proof(
                    r.ReportProofRelation(table=r.ReportTableKey.XRAY_PATH_RELATIONS, row=row)
                )
    for ordinal, warning in enumerate(result.warnings):
        key = f"xray.warning.{ordinal}"
        source_set = f"{key}.sources"
        builder.add_note(
            r.ReportNote(
                key=key,
                family=r.ReportFamily.XRAY,
                kind=r.ReportNoteKind.WARNING,
                code=warning.code.value,
                text=warning.code.value
                if warning.reason is None
                else f"{warning.code.value}: {warning.reason.value}",
                related_provenance_set_key=source_set if warning.source_reference_ids else None,
            ),
            note_set_key=context.note_set_key,
        )
        for identifier in warning.source_reference_ids:
            builder.add_reference(
                builder.references[_source_key(identifier)], provenance_set_key=source_set
            )
        for index, path_key in enumerate(warning.path_keys):
            _proof(
                builder,
                context,
                r.ReportTableKey.XRAY_WARNING_PATHS,
                f"{key}.path.{index}",
                extra={
                    "note_key": key,
                    "ordinal": index,
                    "path_key": path_key,
                },
            )


def project_xray(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.XrayInput,
    result: x.XrayCalculation,
    *,
    instrument_name: Callable[[UUID], str],
    entity_name: Callable[[UUID], str],
) -> None:
    """Render no finance: project retained values, invoking only canonical overlap analytics."""
    requested = set(report_tables(builder.selection))
    valuation_roots: tuple[d.XrayPosition | d.XrayCash, ...] = (*value.positions, *value.cash)
    roots = {item.root.key: item.root for item in valuation_roots}
    paths = {item.key: item for item in result.terminal_paths}
    compositions = {item.fund_instrument_id: item for item in result.fund_compositions}
    candidates = {item.id: item for item in value.constituent_candidates}

    def put(table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> None:
        if table in requested:
            capture_table(builder, table, rows)

    def rows(table: r.ReportTableKey, items: Iterable[XrayRow]) -> Iterable[r.ReportRow]:
        for ordinal, item in enumerate(items):
            yield _row(builder, context, table, f"xray.{table.value}.{ordinal}", item)

    put(
        r.ReportTableKey.XRAY_SUMMARY,
        rows(r.ReportTableKey.XRAY_SUMMARY, (result.portfolio_summary,)),
    )
    put(
        r.ReportTableKey.XRAY_QUALITY,
        rows(r.ReportTableKey.XRAY_QUALITY, (result.portfolio_summary.quality_coverage,)),
    )
    put(r.ReportTableKey.XRAY_DIMENSIONS, rows(r.ReportTableKey.XRAY_DIMENSIONS, result.dimensions))
    put(
        r.ReportTableKey.XRAY_EXPOSURES,
        (
            _row(
                builder,
                context,
                r.ReportTableKey.XRAY_EXPOSURES,
                f"xray.exposure.{index}",
                item,
                extra={
                    "name": entity_name(UUID(item.bucket_key))
                    if item.dimension is d.XrayDimension.COMPANY
                    else item.bucket_key,
                    "path_count": len(item.path_keys),
                    "quality": item.effective.quality,
                },
            )
            for index, item in enumerate(result.exposure_buckets)
        ),
    )

    def path_rows() -> Iterable[r.ReportRow]:
        for index, path in enumerate(result.terminal_paths):
            root = roots[path.root_key]
            company = next(
                item.normalized_known_weight
                for item in path.dimension_weights
                if item.dimension is d.XrayDimension.COMPANY
            )
            name = (
                entity_name(path.entity_id)
                if path.entity_id is not None
                else instrument_name(path.instrument_id)
                if path.instrument_id is not None
                else "Cash"
                if path.explicit_cash
                else "Unresolved exposure"
            )
            yield _row(
                builder,
                context,
                r.ReportTableKey.XRAY_PATHS,
                f"xray.path.{index}",
                path,
                extra={
                    "root_kind": "position" if isinstance(root, d.PositionRoot) else "cash",
                    "position_id": root.position_id if isinstance(root, d.PositionRoot) else None,
                    "name": name,
                    "normalized_known_weight": company,
                },
            )

    put(r.ReportTableKey.XRAY_PATHS, path_rows())

    def fund_rows() -> Iterable[r.ReportRow]:
        for index, held in enumerate(result.held_funds):
            composition = compositions[held.instrument_id]
            first = paths[composition.path_keys[0]] if composition.path_keys else None
            candidate = (
                None
                if first is None or not first.fund_edges
                else candidates.get(first.fund_edges[0].candidate_id)
            )
            yield _row(
                builder,
                context,
                r.ReportTableKey.XRAY_HELD_FUNDS,
                f"xray.fund.{index}",
                composition,
                extra={
                    "instrument_id": held.instrument_id,
                    "name": instrument_name(held.instrument_id),
                    "position_count": len(held.root_keys),
                    "unit_coverage": composition.coverage,
                    "constituent_snapshot_id": None if candidate is None else candidate.id,
                    "source_at": None if candidate is None else candidate.evidence.effective_at,
                },
            )

    put(r.ReportTableKey.XRAY_HELD_FUNDS, fund_rows())
    put(
        r.ReportTableKey.XRAY_CONCENTRATIONS,
        rows(r.ReportTableKey.XRAY_CONCENTRATIONS, result.portfolio_summary.top_concentrations),
    )
    put(
        r.ReportTableKey.XRAY_CONCENTRATION_MEMBERS,
        (
            _row(
                builder,
                context,
                r.ReportTableKey.XRAY_CONCENTRATION_MEMBERS,
                f"xray.concentration.{item.count}.{ordinal}",
                extra={"count": item.count, "ordinal": ordinal, "entity_id": entity},
            )
            for item in result.portfolio_summary.top_concentrations
            for ordinal, entity in enumerate(item.entity_ids)
        ),
    )
    put(
        r.ReportTableKey.XRAY_THRESHOLDS,
        rows(r.ReportTableKey.XRAY_THRESHOLDS, result.portfolio_summary.thresholds),
    )
    put(r.ReportTableKey.XRAY_RESIDUALS, rows(r.ReportTableKey.XRAY_RESIDUALS, result.residuals))
    # One kernel call produces a pair metric AND all its common entities. Only
    # identity enumeration/counting happens here; no Decimal arithmetic does.
    funds = tuple(sorted((item.instrument_id for item in result.held_funds), key=str))
    count = len(funds) * (len(funds) - 1) // 2
    r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "overlap_pairs")
    pair_rows: list[r.ReportRow] = []
    buffered_bytes = 0
    common_count = 0

    def common_rows() -> Iterable[r.ReportRow]:
        nonlocal buffered_bytes, common_count
        for left, right in combinations(funds, 2):
            common = calculate_common_entities(result, x.CanonicalFundPair(left, right))
            pair_key = f"{left}:{right}"
            pair_row = _row(
                builder,
                context,
                r.ReportTableKey.XRAY_OVERLAP_PAIRS,
                f"xray.pair.{pair_key}",
                common.pair,
                extra={
                    "pair_key": pair_key,
                    "left_instrument_id": left,
                    "right_instrument_id": right,
                },
            )
            buffered_bytes += len(encode_report_row(pair_row))
            r.report_limit(
                buffered_bytes + builder.byte_length <= r.MAX_REPORT_DOCUMENT_BYTES,
                "document_bytes",
            )
            pair_rows.append(pair_row)
            for item in common.entities:
                common_count += 1
                r.report_limit(common_count <= r.MAX_REPORT_DATASET_ROWS, "overlap_entities")
                row = _row(
                    builder,
                    context,
                    r.ReportTableKey.XRAY_OVERLAP_ENTITIES,
                    f"xray.common.{pair_key}.{item.entity_id}",
                    extra={
                        "pair_key": pair_key,
                        "entity_id": item.entity_id,
                        "name": entity_name(item.entity_id),
                        "left_weight": item.first_weight,
                        "right_weight": item.second_weight,
                        "common_weight": item.common_weight,
                    },
                )
                r.report_limit(
                    buffered_bytes + builder.byte_length + len(encode_report_row(row))
                    <= r.MAX_REPORT_DOCUMENT_BYTES,
                    "document_bytes",
                )
                yield row

    # Stream the potentially large common-entity table while retaining only the
    # bounded pair table. Each pair is calculated exactly once.
    put(r.ReportTableKey.XRAY_OVERLAP_ENTITIES, common_rows())
    put(r.ReportTableKey.XRAY_OVERLAP_PAIRS, pair_rows)
    _input_proof(builder, context, value)
    _result_proof(builder, context, result)
    from .report_capture_xray_proof import capture_xray_semantics

    capture_xray_semantics(builder, context, value, result)
    if r.ReportTableKey.XRAY_PATH_RELATIONS not in builder.proof_table_keys:
        put(r.ReportTableKey.XRAY_PATH_RELATIONS, ())


def _source_parents(
    builder: ReportBuilder,
    context: r.ReportContext,
    session: Session,
    service: PostgresXrayService,
    result: x.XrayCalculation,
    source_use: SourceUse,
) -> None:
    """Retain actual licensed parent headers for every child proof reference."""
    targets: dict[
        d.XrayReferenceKind,
        tuple[type[cm.XrayEvidenceFields | sm.SourceSnapshotFields], r.ReportSourceKind],
    ] = {
        d.XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE: (
            cm.EntityEvidenceVersionModel,
            r.ReportSourceKind.ENTITY_EVIDENCE_VERSION,
        ),
        d.XrayReferenceKind.RELATIONSHIP: (
            cm.EntityEvidenceVersionModel,
            r.ReportSourceKind.ENTITY_EVIDENCE_VERSION,
        ),
        d.XrayReferenceKind.CLASSIFICATION_ASSIGNMENT: (
            cm.ClassificationSnapshotModel,
            r.ReportSourceKind.CLASSIFICATION_SNAPSHOT,
        ),
        d.XrayReferenceKind.CONSTITUENT_HOLDING: (
            cm.ConstituentSnapshotModel,
            r.ReportSourceKind.CONSTITUENT_SNAPSHOT,
        ),
        d.XrayReferenceKind.FX_OBSERVATION: (sm.FxSnapshotModel, r.ReportSourceKind.FX_SNAPSHOT),
        d.XrayReferenceKind.FX_COVERAGE_GAP: (sm.FxSnapshotModel, r.ReportSourceKind.FX_SNAPSHOT),
        d.XrayReferenceKind.PRICE_OBSERVATION: (
            sm.PriceSnapshotModel,
            r.ReportSourceKind.PRICE_SNAPSHOT,
        ),
    }
    retained = {(item.kind, item.subject_id) for item in builder.references.values()}
    for dependency in result.source_dependencies:
        target = targets.get(dependency.reference.kind)
        if target is None:
            continue
        model, kind = target
        identifier = dependency.reference.parent_record_id
        if identifier is None:
            fail_validation("A captured source child requires its actual parent.", field="source")
        if (kind, identifier) in retained:
            continue
        parent = service._owned(session, result.owner_id, model, identifier)
        if isinstance(parent, sm.SourceSnapshotFields):
            service._snapshot_permit(session, parent, source_use)
        else:
            service._evidence_permit(session, parent, source_use)
        if (str(parent.provider_id), parent.license_version_id) != (
            dependency.provider_id,
            dependency.license_version_id,
        ):
            fail_validation("Source child and parent ownership differ.", field="source")
        builder.add_reference(
            r.ReportSourceReference(
                key=f"xray.parent.{kind.value}.{parent.id}",
                kind=kind,
                subject_id=parent.id,
                content_digest=parent.content_digest,
                provider_id=parent.provider_id,
                license_version_id=parent.license_version_id,
                source_at=parent.effective_at,
                first_observed_at=parent.first_observed_at,
            ),
            provenance_set_key=context.provenance_set_key,
        )
        retained.add((kind, identifier))


def capture_xray(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
    source_use: SourceUse,
) -> None:
    if r.ReportTableKey.XRAY_SUMMARY not in report_tables(builder.selection):
        return
    if source_use not in (SourceUse.REPORT, SourceUse.EXPORT):
        fail_validation("A report/export copy permission is required.", field="source_use")
    authorization.check(session, now=clock())
    principal = authorization.as_principal(now=clock())
    service = PostgresXrayService(
        sessions=sessions,
        cursor_signing_key=cursor_signing_key,
        clock=clock,
        required_copy_use=source_use,
    )
    request = app.XrayRunRequest(
        snapshot_id=str(builder.selection.snapshot_id),
        source_cutoff_at=builder.selection.source_cutoff_at,
        currency=app.ExplicitCurrency(reporting_currency=builder.selection.reporting_currency),
    )
    handle = service._resolve_xray_run(session, principal, authorization.account_id, request)
    result = service._load_xray_result(session, principal, authorization.account_id, handle)
    _, capture, _ = service._authorized_rows(
        session, principal, authorization.account_id, handle.run_id
    )
    value = decode_xray_input(capture.canonical_input)
    constituent = builder.selection.constituent_snapshot_id
    if constituent is not None and not any(
        item.reference.kind is d.XrayReferenceKind.CONSTITUENT_SNAPSHOT
        and item.reference.record_id == constituent
        for item in result.source_dependencies
    ):
        fail_validation(
            "The constituent snapshot is absent from the captured X-ray dependencies.",
            field="constituent_snapshot_id",
        )
    context = r.ReportContext(
        key="xray",
        family=r.ReportFamily.XRAY,
        method_key=value.policy.method_name,
        method_version=value.policy.method_version,
        valuation_at=result.valuation_at.value,
        source_cutoff_at=result.source_cutoff_at.value,
        quality=result.portfolio_summary.total.quality,
        provenance_set_key="xray.sources",
        coverage_set_key="xray.coverage",
        note_set_key="xray.notes",
    )
    builder.add_context(context)
    for reference in result.source_dependencies:
        view = service._source_view(session, authorization.owner_id, reference)
        if reference.license_version_id is not None:
            license = service._license(
                session, authorization.owner_id, reference.license_version_id
            )
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=reference.license_version_id,
                    provider_id=UUID(license.provider_id),
                    license_digest=digest(license),
                    attribution=license.attribution,
                    pinned_store=license.store,
                    pinned_display=license.display,
                    pinned_report=license.report,
                    pinned_export=license.export,
                    valid_from=license.effective_at,
                )
            )
        builder.add_reference(
            r.ReportSourceReference(
                key=_source_key(reference.id),
                kind=_SOURCE_KINDS[reference.reference.kind],
                subject_id=reference.reference.record_id,
                parent_id=reference.reference.parent_record_id,
                content_digest=reference.content_digest,
                source_at=view.source_at,
                first_observed_at=view.first_observed_at,
                provider_id=None if reference.provider_id is None else UUID(reference.provider_id),
                license_version_id=reference.license_version_id,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    _source_parents(builder, context, session, service, result, source_use)
    from hashlib import sha256

    for role, identifier, content in (
        (r.ReportInputRole.INPUT, handle.input_id, result.input_digest),
        (r.ReportInputRole.RESULT, handle.run_id, result.content_digest),
        (
            r.ReportInputRole.POLICY,
            value.policy.id,
            sha256(encode_xray_policy(value.policy)).hexdigest(),
        ),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=r.ReportFamily.XRAY,
                role=role,
                subject_id=identifier,
                content_digest=content,
                method_key=context.method_key,
                method_version=context.method_version,
            )
        )

    @cache
    def instrument_name(identifier: UUID) -> str:
        return service._instrument_name(session, identifier)

    @cache
    def entity_name(identifier: UUID) -> str:
        return service._entity_name(session, authorization.owner_id, handle, identifier)

    project_xray(
        builder, context, value, result, instrument_name=instrument_name, entity_name=entity_name
    )
    authorization.check(session, now=clock())
