"""Bounded physical X-ray copy cleanup within the existing shared expiry budget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from . import xray_run_models as xm
from .models import CollectionQuerySnapshotMemberModel, CollectionQuerySnapshotModel
from .phase2_retention_costs import PHASE2_COLLECTION_MUTATION_ROWS, PHASE2_MARKER_ROWS
from .phase2_retention_models import Phase2RetentionSweepModel, XrayRetainedSourceModel
from .phase2_retention_runtime import charge, drain_retained_sources, source_erasure_authorized
from .planning_models import AnalyticsRunModel
from .source_models import FxSnapshotModel, SourceSnapshotFields
from .source_retention import PayloadCopyCost, SourcePurgeBudget
from .source_retention_sql import logical_payload_size, purge_payload_rows
from .xray_catalog_models import (
    ClassificationSnapshotModel,
    ConstituentSnapshotModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    XrayEvidenceFields,
)


def purge_collection_copies(
    session: Session,
    owner: UUID,
    collection_id: UUID,
    *,
    budget: SourcePurgeBudget,
) -> bool:
    """The caller holds owner locks and proves TTL or exact dependent-source expiry."""
    for model, columns in (
        (xm.EtfOverlapEntityModel, ("canonical_payload",)),
        (xm.EtfOverlapPairModel, ("canonical_payload",)),
    ):
        table = cast(Table, model.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == owner) & (table.c.collection_id == collection_id),
            payload_columns=columns,
            delete_rows=True,
            budget=budget,
        ).complete:
            return False
    members = CollectionQuerySnapshotMemberModel
    while budget.rows_inspected >= PHASE2_COLLECTION_MUTATION_ROWS + 2:
        if not charge(budget):
            return False
        rows = session.execute(
            select(members.ordinal, members.record_id)
            .where(
                members.snapshot_id == collection_id,
            )
            .order_by(members.ordinal)
            .limit(
                min(
                    512 // PHASE2_COLLECTION_MUTATION_ROWS,
                    budget.rows_inspected // (PHASE2_COLLECTION_MUTATION_ROWS + 1),
                )
            )
            .with_for_update()
        ).all()
        if not rows:
            break
        if not budget.inspect(rows=len(rows)):
            raise RuntimeError("Collection member sizing exceeded the shared row budget.")
        # One copied UUID and one bigint ordinal, without loading a member's target.
        identifiers = budget.reserve_clear_batch(
            tuple(
                PayloadCopyCost(
                    row_id=row.record_id,
                    payload_bytes=24,
                    inspection_rows=PHASE2_COLLECTION_MUTATION_ROWS,
                    payload_inspections=2,
                )
                for row in rows
            )
        )
        if not identifiers:
            return False
        result = cast(
            CursorResult[tuple[object, ...]],
            session.execute(
                delete(members).where(
                    members.snapshot_id == collection_id,
                    members.record_id.in_(identifiers),
                )
            ),
        )
        if result.rowcount != len(identifiers):
            raise RuntimeError("A locked collection member changed during cleanup.")
        if len(identifiers) != len(rows):
            return False
    if budget.rows_inspected < 2 * PHASE2_COLLECTION_MUTATION_ROWS + 3:
        return False
    # Reserve both remaining rows before either deletion. Removing the binding
    # alone would lose discovery of an unfinished collection after a budget stop.
    pending: list[tuple[Table, UUID, int]] = []
    for metadata_model, column, metadata_columns in (
        (xm.XrayCollectionBindingModel, "collection_id", ("run_id", "constituent_snapshot_id")),
        (
            CollectionQuerySnapshotModel,
            "id",
            ("resource", "sort_specification", "filter_fingerprint", "exact_total"),
        ),
    ):
        if not charge(budget):
            return False
        table = cast(Table, metadata_model.__table__)
        row = session.execute(
            select(table.c.id, logical_payload_size(table, metadata_columns).label("size"))
            .where(
                table.c.owner_id == owner,
                table.c[column] == collection_id,
            )
            .limit(1)
            .with_for_update()
        ).first()
        if row is not None:
            pending.append((table, row.id, row.size))
    total = sum(size for _, _, size in pending)
    if (
        len(pending) * PHASE2_COLLECTION_MUTATION_ROWS > budget.rows_inspected
        or len(pending) > budget.rows_removed
        or total > budget.bytes_removed
        or total * 2 > budget.bytes_inspected
    ):
        return False
    for _table, identifier, size in pending:
        if budget.reserve_clear_batch(
            (
                PayloadCopyCost(
                    row_id=identifier,
                    payload_bytes=size,
                    inspection_rows=PHASE2_COLLECTION_MUTATION_ROWS,
                    payload_inspections=2,
                ),
            )
        ) != (identifier,):
            raise RuntimeError("A reserved collection cleanup group changed.")
    for table, identifier, _ in pending:
        result = cast(
            CursorResult[tuple[object, ...]],
            session.execute(
                delete(table).where(
                    table.c.owner_id == owner,
                    table.c.id == identifier,
                )
            ),
        )
        if result.rowcount != 1:
            raise RuntimeError("A locked collection changed during cleanup.")
    return True


def _run_collections(
    session: Session, owner: UUID, run_id: UUID, budget: SourcePurgeBudget
) -> bool:
    while charge(budget):
        collection = session.scalar(
            select(xm.XrayCollectionBindingModel.collection_id)
            .where(
                xm.XrayCollectionBindingModel.owner_id == owner,
                xm.XrayCollectionBindingModel.run_id == run_id,
            )
            .order_by(xm.XrayCollectionBindingModel.id)
            .limit(1)
        )
        if collection is None:
            return True
        if not purge_collection_copies(session, owner, collection, budget=budget):
            return False
    return False


def _run_payloads(
    session: Session,
    owner: UUID,
    run_id: UUID,
    analytics_run_id: UUID,
    budget: SourcePurgeBudget,
) -> bool:
    if not _run_collections(session, owner, run_id, budget):
        return False
    # Child indexes are reached through one parent ID at a time, never an all-run
    # join/subquery that silently inspects an unbounded number of parent copies.
    for parent, child, parent_column, columns in (
        (xm.XrayExposurePathModel, xm.XrayPathEdgeModel, "path_id", ("canonical_edge",)),
        (
            xm.XrayFundCompositionModel,
            xm.XrayFundEntityModel,
            "composition_id",
            ("canonical_payload", "relative_coefficient"),
        ),
    ):
        parent_table = cast(Table, parent.__table__)
        child_table = cast(Table, child.__table__)
        while charge(budget):
            query = select(parent_table.c.id).where(
                parent_table.c.owner_id == owner,
                parent_table.c.run_id == run_id,
                parent_table.c.canonical_payload != b"",
            )
            identifier = session.scalar(query.order_by(parent_table.c.id).limit(1))
            if identifier is None:
                break
            if not budget.inspect(rows=1):
                raise RuntimeError("X-ray parent lookup exceeded the shared row budget.")
            if not purge_payload_rows(
                session,
                child_table,
                (child_table.c.owner_id == owner) & (child_table.c[parent_column] == identifier),
                payload_columns=columns,
                delete_rows=child is xm.XrayPathEdgeModel,
                budget=budget,
            ).complete:
                return False
            if not purge_payload_rows(
                session,
                parent_table,
                (parent_table.c.owner_id == owner) & (parent_table.c.id == identifier),
                payload_columns=("canonical_payload",),
                delete_rows=False,
                budget=budget,
            ).complete:
                return False
        if not budget.metadata_limit:
            return False
    for model in (
        xm.XrayRunSourceModel,
        xm.XrayDimensionModel,
        xm.XrayWarningModel,
        xm.XrayResidualModel,
        xm.XrayClassificationDecisionModel,
        xm.XrayDirectPositionModel,
        xm.XrayHeldFundModel,
        xm.XrayExposureModel,
        xm.XrayExposurePathModel,
        xm.XrayFundCompositionModel,
    ):
        table = cast(Table, model.__table__)
        columns = (
            ("canonical_use",)
            if model is xm.XrayRunSourceModel
            else ("canonical_payload", "bucket_key")
            if model is xm.XrayExposureModel
            else ("canonical_payload",)
        )
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == owner) & (table.c.run_id == run_id),
            payload_columns=columns,
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
    table = cast(Table, xm.XrayRunModel.__table__)
    if not purge_payload_rows(
        session,
        table,
        (table.c.owner_id == owner) & (table.c.id == run_id),
        payload_columns=("canonical_summary", "canonical_reconciliation", "canonical_exact_state"),
        delete_rows=False,
        budget=budget,
    ).complete:
        return False
    table = cast(Table, AnalyticsRunModel.__table__)
    return purge_payload_rows(
        session,
        table,
        (table.c.owner_id == owner) & (table.c.id == analytics_run_id),
        payload_columns=("canonical_input", "canonical_result"),
        delete_rows=False,
        budget=budget,
    ).complete


def purge_xray_source_copies(
    session: Session,
    source: SourceSnapshotFields | XrayEvidenceFields,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    references = {
        FxSnapshotModel: "fx_snapshot_id",
        EntityEvidenceVersionModel: "entity_evidence_version_id",
        ClassificationSnapshotModel: "classification_snapshot_id",
        FundDefinitionModel: "fund_definition_id",
        FundSourceMappingModel: "fund_mapping_id",
        ConstituentSnapshotModel: "constituent_snapshot_id",
    }
    reference = references.get(type(source))
    if reference is None:
        # Existing price/action/benchmark families are not X-ray inputs.
        return True
    kind = {
        "fx_snapshot_id": "fx",
        "entity_evidence_version_id": "entity_evidence",
        "classification_snapshot_id": "classification",
        "fund_definition_id": "fund_definition",
        "fund_mapping_id": "fund_mapping",
        "constituent_snapshot_id": "constituent",
    }[reference]
    if not source_erasure_authorized(session, source.owner_id, kind, source.id, at, budget):
        return False
    if isinstance(source, ConstituentSnapshotModel):
        while charge(budget):
            collection = session.scalar(
                select(xm.XrayCollectionBindingModel.collection_id)
                .where(
                    xm.XrayCollectionBindingModel.owner_id == source.owner_id,
                    xm.XrayCollectionBindingModel.constituent_snapshot_id == source.id,
                )
                .order_by(xm.XrayCollectionBindingModel.id)
                .limit(1)
            )
            if collection is None:
                break
            if not purge_collection_copies(
                session,
                source.owner_id,
                collection,
                budget=budget,
            ):
                return False
        if not budget.metadata_limit:
            return False
    membership = XrayRetainedSourceModel
    capture = xm.XrayInputSnapshotModel
    while budget.metadata_limit >= 2:
        if not charge(budget, 2):
            return False
        candidate = session.execute(
            select(membership.input_id.label("id"), membership.dependency_id)
            .where(
                membership.owner_id == source.owner_id,
                membership.source_kind == kind,
                membership.source_id == source.id,
            )
            .order_by(membership.input_id, membership.dependency_id)
            .limit(1)
        ).first()
        if candidate is None:
            return True
        if not budget.enter_capture("xray", candidate.id):
            return False
        if not budget.metadata_limit:
            return False
        from .scenario_retention import purge_scenario_xray_copies

        if not purge_scenario_xray_copies(
            session, source.owner_id, candidate.id, at=at, budget=budget
        ):
            return False
        if not charge(budget):
            return False
        event = session.scalar(
            select(xm.XrayRetentionEventModel.id)
            .where(
                xm.XrayRetentionEventModel.owner_id == source.owner_id,
                xm.XrayRetentionEventModel.input_id == candidate.id,
            )
            .limit(1)
        )
        if event is None:
            if not charge(budget, PHASE2_MARKER_ROWS):
                return False
            session.add(
                xm.XrayRetentionEventModel(
                    owner_id=source.owner_id,
                    input_id=candidate.id,
                    dependency_id=candidate.dependency_id,
                    expired_at=at,
                    created_at=at,
                )
            )
            session.flush()
        if not charge(budget):
            return False
        # Fetch only run identity, never its canonical payload during discovery.
        run = session.execute(
            select(xm.XrayRunModel.id, xm.XrayRunModel.analytics_run_id)
            .where(
                xm.XrayRunModel.owner_id == source.owner_id,
                xm.XrayRunModel.input_id == candidate.id,
            )
            .limit(1)
        ).first()
        if run is not None:
            if not budget.enter_run("xray", run.id):
                return False
            if not _run_payloads(session, source.owner_id, run.id, run.analytics_run_id, budget):
                return False
        for model, columns in (
            (xm.XrayInputPositionModel, ("canonical_position",)),
            (xm.XrayInputCashModel, ("canonical_cash",)),
            (xm.XrayInputSourceSelectionModel, ("canonical_selection",)),
            (xm.XrayInputDependencyModel, ("canonical_reference",)),
        ):
            table = cast(Table, model.__table__)
            if not purge_payload_rows(
                session,
                table,
                (table.c.owner_id == source.owner_id) & (table.c.input_id == candidate.id),
                payload_columns=columns,
                delete_rows=False,
                budget=budget,
            ).complete:
                return False
        # Keep every source membership until the input and all copied descendants
        # are absent; each membership removal checks the exact protected counter.
        table = cast(Table, capture.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == source.owner_id) & (table.c.id == candidate.id),
            payload_columns=("canonical_input",),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
        if not drain_retained_sources(session, source.owner_id, "xray", candidate.id, budget):
            return False
    return False


def cleanup_expired_xray_collections(
    session: Session,
    owner: UUID,
    budget: SourcePurgeBudget,
    *,
    at: datetime | None = None,
) -> bool:
    """Remove expired bound projections under sources -> xray, before capacity reservation.

    False means that physical copies remain and still occupy shared capacity.
    The caller supplies its pinned store clock when available. No cascade may
    remove these copies outside this shared row/byte budget.
    """
    cutoff = datetime.now(UTC) if at is None else at
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Collection cleanup requires an aware timestamp.")
    if not charge(budget, 3):
        return False
    session.execute(
        insert(Phase2RetentionSweepModel)
        .values(family="xray_collection", scope_id=owner)
        .on_conflict_do_nothing()
    )
    sweep = session.get(Phase2RetentionSweepModel, ("xray_collection", owner), with_for_update=True)
    if sweep is None:
        raise RuntimeError("X-ray collection scheduling state is unavailable.")
    binding = xm.XrayCollectionBindingModel
    while budget.rows_inspected >= 4:
        if not charge(budget, 2):
            return False
        query = select(binding.id, binding.collection_id).where(binding.owner_id == owner)
        if sweep.after_id is not None:
            query = query.where(binding.id > sweep.after_id)
        candidate = session.execute(query.order_by(binding.id).limit(1)).first()
        if candidate is None:
            if not charge(budget):
                return False
            sweep.after_id = None
            session.flush()
            return True
        if not charge(budget):
            return False
        expires = session.scalar(
            select(CollectionQuerySnapshotModel.expires_at).where(
                CollectionQuerySnapshotModel.owner_id == owner,
                CollectionQuerySnapshotModel.id == candidate.collection_id,
            )
        )
        if expires is None:
            raise RuntimeError("X-ray collection binding has no owned root.")
        if expires <= cutoff and not purge_collection_copies(
            session, owner, candidate.collection_id, budget=budget
        ):
            return False
        if not charge(budget):
            return False
        sweep.after_id = candidate.id
        session.flush()
    return False
