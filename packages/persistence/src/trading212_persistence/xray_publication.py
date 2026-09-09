"""Atomic verified X-ray capture and normalized calculation publication."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from trading212_analytics.xray import calculate_xray, verify_xray_result
from trading212_application.xray import XrayServiceErrorCode
from trading212_domain.xray_codec import XrayComponent, encode_xray_component, encode_xray_result
from trading212_domain.xray_result import XrayCalculation

from . import xray_run_models as xm
from .planning_models import AnalyticsRunModel, AnalyticsSourceModel
from .xray_base import xray_error
from .xray_capture import XrayCapturedInput
from .xray_ingestion import XrayIngestion


def publish_xray(
    service: XrayIngestion, session: Session, captured: XrayCapturedInput
) -> xm.XrayRunModel:
    value = captured.value
    result = calculate_xray(value)
    verify_xray_result(value, result)
    canonical_result = encode_xray_result(result)
    fingerprint = sha256(captured.canonical_input).hexdigest()
    if result.input_digest != fingerprint:
        raise xray_error(XrayServiceErrorCode.XRAY_UNAVAILABLE)
    now = service._now()
    capture = xm.XrayInputSnapshotModel(
        id=uuid4(),
        owner_id=value.owner_id,
        account_id=value.account_id,
        snapshot_id=value.snapshot_id,
        valuation_run_id=captured.valuation_run_id,
        reconciliation_run_id=None,
        policy_id=value.policy.id,
        reporting_currency=value.reporting_currency.value,
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        captured_at=now,
        sealed_at=None,
        input_digest=fingerprint,
        canonical_input=captured.canonical_input,
        created_at=now,
    )
    session.add(capture)
    session.flush()
    dependencies: dict[UUID, xm.XrayInputDependencyModel] = {}
    for ordinal, position in enumerate(value.positions):
        session.add(
            xm.XrayInputPositionModel(
                owner_id=value.owner_id,
                input_id=capture.id,
                position_id=position.root.position_id,
                ordinal=ordinal,
                canonical_position=encode_xray_component(position),
                created_at=now,
            )
        )
    for ordinal, cash in enumerate(value.cash):
        session.add(
            xm.XrayInputCashModel(
                owner_id=value.owner_id,
                input_id=capture.id,
                cash_id=cash.root.snapshot_cash_id,
                ordinal=ordinal,
                canonical_cash=encode_xray_component(cash),
                created_at=now,
            )
        )
    for reference in value.source_dependencies:
        target = captured.targets.get(reference.id)
        if target is None:
            raise xray_error(XrayServiceErrorCode.XRAY_UNAVAILABLE)
        row = xm.XrayInputDependencyModel(
            id=uuid4(),
            owner_id=value.owner_id,
            input_id=capture.id,
            reference_id=reference.id,
            provider_id=None if reference.provider_id is None else UUID(reference.provider_id),
            license_version_id=reference.license_version_id,
            canonical_reference=encode_xray_component(reference),
            **{target[0]: target[1]},
            created_at=now,
        )
        session.add(row)
        dependencies[reference.id] = row
    session.flush()
    analytics = AnalyticsRunModel(
        id=uuid4(),
        owner_id=value.owner_id,
        broker_account_id=value.account_id,
        kind="xray",
        input_digest=fingerprint,
        content_digest=sha256(canonical_result).hexdigest(),
        method_version=value.policy.method_version,
        reporting_currency=value.reporting_currency.value,
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        canonical_input=captured.canonical_input,
        canonical_result=canonical_result,
        created_at=now,
    )
    session.add(analytics)
    session.flush()
    run = xm.XrayRunModel(
        id=uuid4(),
        owner_id=value.owner_id,
        input_id=capture.id,
        analytics_run_id=analytics.id,
        calculated_at=now,
        sealed_at=None,
        content_digest=analytics.content_digest,
        canonical_summary=encode_xray_component(result.portfolio_summary),
        canonical_reconciliation=encode_xray_component(result.reconciliation),
        canonical_exact_state=encode_xray_component(result.exact_state),
        created_at=now,
    )
    session.add(run)
    session.flush()
    session.add(
        AnalyticsSourceModel(
            owner_id=value.owner_id,
            run_id=analytics.id,
            xray_input_id=capture.id,
            digest=fingerprint,
            created_at=now,
        )
    )
    session.add(
        AnalyticsSourceModel(
            owner_id=value.owner_id,
            run_id=analytics.id,
            snapshot_id=value.snapshot_id,
            digest=value.snapshot_digest,
            created_at=now,
        )
    )
    broker_sources = {
        target[1] for target in captured.targets.values() if target[0] == "broker_source_record_id"
    }
    for source_id in broker_sources:
        source = next(
            item for item in value.source_dependencies if item.reference.record_id == source_id
        )
        session.add(
            AnalyticsSourceModel(
                owner_id=value.owner_id,
                run_id=analytics.id,
                source_record_id=source_id,
                digest=source.content_digest,
                created_at=now,
            )
        )
    evidence = {
        item.evidence.id: item.evidence.source_reference_id
        for group in (
            value.fund_definitions,
            value.fund_mappings,
            value.constituent_candidates,
            value.entity_evidence,
            value.relationship_versions,
            value.classification_batches,
        )
        for item in group
    }
    for selection in result.selections:
        selection_row = xm.XrayInputSourceSelectionModel(
            id=uuid4(),
            owner_id=value.owner_id,
            input_id=capture.id,
            key=selection.key,
            canonical_selection=encode_xray_component(selection),
            created_at=now,
        )
        session.add(selection_row)
        session.flush()
        for identifier in selection.candidate_evidence_ids:
            reference_id = evidence.get(identifier)
            if reference_id not in dependencies:
                raise xray_error(XrayServiceErrorCode.XRAY_UNAVAILABLE)
            session.add(
                xm.XraySelectionCandidateModel(
                    owner_id=value.owner_id,
                    selection_id=selection_row.id,
                    dependency_id=dependencies[reference_id].id,
                    evidence_id=identifier,
                    selected=identifier in selection.selected_evidence_ids,
                    created_at=now,
                )
            )
    for ordinal, use in enumerate(result.typed_source_uses):
        session.add(
            xm.XrayRunSourceModel(
                owner_id=value.owner_id,
                run_id=run.id,
                dependency_id=dependencies[use.source_reference_id].id,
                ordinal=ordinal,
                canonical_use=encode_xray_component(use),
                created_at=now,
            )
        )
    _result_rows(session, run, result)
    session.flush()
    # A future-effective license can become current during calculation or row
    # publication even while registration is excluded by the owner locks.
    service._permit_xray_storage_licenses(
        session,
        value.owner_id,
        (
            reference.license_version_id
            for reference in value.source_dependencies
            if reference.license_version_id is not None
        ),
        expires_at=service._xray_storage_expires_at(session, value.owner_id, capture.id),
    )
    # Insert all children before either immutable parent can be observed sealed.
    capture.sealed_at = now
    run.sealed_at = now
    session.flush()
    return run


def _result_rows(session: Session, run: xm.XrayRunModel, result: XrayCalculation) -> None:
    common = {"owner_id": run.owner_id, "run_id": run.id, "created_at": run.calculated_at}

    def add_rows[T: XrayComponent](
        model: type[xm.XrayRunPayloadFields],
        values: tuple[T, ...],
        extra: Callable[[T], dict[str, object]],
    ) -> None:
        for ordinal, value in enumerate(values):
            session.add(
                model(
                    **common,
                    ordinal=ordinal,
                    canonical_payload=encode_xray_component(value),
                    **extra(value),
                )
            )

    add_rows(
        xm.XrayDimensionModel, result.dimensions, lambda value: {"dimension": value.dimension.value}
    )
    add_rows(xm.XrayWarningModel, result.warnings, lambda value: {})
    add_rows(
        xm.XrayResidualModel, result.residuals, lambda value: {"consumer_key": value.consumer_key}
    )
    add_rows(
        xm.XrayClassificationDecisionModel,
        result.classification_decisions,
        lambda value: {"key": value.key},
    )
    add_rows(
        xm.XrayDirectPositionModel,
        result.direct_positions,
        lambda value: {"position_id": value.root.position_id},
    )
    add_rows(
        xm.XrayHeldFundModel,
        result.held_funds,
        lambda value: {"instrument_id": value.instrument_id},
    )
    exposures: dict[str, xm.XrayExposureModel] = {}
    by_path: dict[str, list[xm.XrayExposureModel]] = {}
    for ordinal, value in enumerate(result.exposure_buckets):
        row = xm.XrayExposureModel(
            id=uuid4(),
            **common,
            ordinal=ordinal,
            dimension=value.dimension.value,
            bucket_key=value.bucket_key,
            canonical_payload=encode_xray_component(value),
        )
        session.add(row)
        exposures[f"{value.dimension.value}:{value.bucket_key}"] = row
        for key in value.path_keys:
            by_path.setdefault(key, []).append(row)
    session.flush()
    for ordinal, path_value in enumerate(result.terminal_paths):
        path_row = xm.XrayExposurePathModel(
            id=uuid4(),
            **common,
            ordinal=ordinal,
            path_key=path_value.key,
            root_key=path_value.root_key,
            identity_decision_ids=list(path_value.identity_decision_ids),
            source_reference_ids=list(path_value.source_reference_ids),
            canonical_payload=encode_xray_component(path_value),
        )
        session.add(path_row)
        session.flush()
        for edge_ordinal, edge in enumerate(path_value.fund_edges):
            session.add(
                xm.XrayPathEdgeModel(
                    owner_id=run.owner_id,
                    path_id=path_row.id,
                    ordinal=edge_ordinal,
                    fund_mapping_id=edge.mapping_id,
                    constituent_snapshot_id=edge.candidate_id,
                    holding_id=edge.holding_id,
                    canonical_edge=encode_xray_component(edge),
                    created_at=run.calculated_at,
                )
            )
        for exposure in by_path.get(path_value.key, ()):
            session.add(
                xm.XrayExposurePathBucketModel(
                    owner_id=run.owner_id,
                    path_id=path_row.id,
                    exposure_id=exposure.id,
                    dimension=exposure.dimension,
                    ordinal=ordinal,
                    created_at=run.calculated_at,
                )
            )
    held = {item.instrument_id: item for item in result.held_funds}
    for ordinal, composition_value in enumerate(result.fund_compositions):
        composition_row = xm.XrayFundCompositionModel(
            id=uuid4(),
            **common,
            ordinal=ordinal,
            instrument_id=composition_value.fund_instrument_id,
            composition_root_key=composition_value.composition_root_key,
            position_count=len(held[composition_value.fund_instrument_id].root_keys),
            canonical_payload=encode_xray_component(composition_value),
        )
        session.add(composition_row)
        session.flush()
        for entity_ordinal, entity in enumerate(composition_value.entities):
            session.add(
                xm.XrayFundEntityModel(
                    owner_id=run.owner_id,
                    composition_id=composition_row.id,
                    entity_id=entity.entity_id,
                    ordinal=entity_ordinal,
                    relative_coefficient=format(entity.relative_coefficient, "f"),
                    canonical_payload=encode_xray_component(entity),
                    created_at=run.calculated_at,
                )
            )
