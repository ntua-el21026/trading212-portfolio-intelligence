"""Reuse retained immutable planning membership without bypassing hard reservations."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application.queries import CursorValidationError

from .collection_snapshots import (
    CollectionSnapshot,
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
)
from .models import CollectionQuerySnapshotMemberModel, CollectionQuerySnapshotModel
from .planning_inputs import digest
from .planning_models import PlanningCollectionBindingModel


def first_immutable_page(
    session: Session,
    store: CollectionSnapshotStore,
    definition: CollectionSnapshotDefinition,
    record_ids: tuple[UUID, ...],
    *,
    limit: int,
    source_kind: Literal["request", "result", "run"],
    source_id: UUID,
) -> CollectionSnapshotPage:
    if definition.resource not in {
        CollectionSnapshotResource.PLAN_LINES,
        CollectionSnapshotResource.ACTUAL_TARGET_ROWS,
    }:
        raise ValueError("Unsupported immutable planning collection.")
    cache_key = digest(
        (
            definition.owner_id,
            definition.broker_account_id,
            definition.resource,
            definition.filter_fingerprint,
            source_kind,
            source_id,
            record_ids,
        )
    )
    retained = session.scalar(
        select(CollectionQuerySnapshotModel)
        .join(
            PlanningCollectionBindingModel,
            PlanningCollectionBindingModel.collection_snapshot_id
            == CollectionQuerySnapshotModel.id,
        )
        .where(
            PlanningCollectionBindingModel.owner_id == definition.owner_id,
            PlanningCollectionBindingModel.cache_key == cache_key,
            CollectionQuerySnapshotModel.owner_id == definition.owner_id,
            CollectionQuerySnapshotModel.broker_account_id == definition.broker_account_id,
            CollectionQuerySnapshotModel.resource == definition.resource.value,
            CollectionQuerySnapshotModel.filter_fingerprint == definition.filter_fingerprint,
            CollectionQuerySnapshotModel.expires_at > func.now(),
        )
        .order_by(
            CollectionQuerySnapshotModel.created_at.desc(), CollectionQuerySnapshotModel.id.desc()
        )
        .limit(1)
        .with_for_update(read=True)
    )
    if retained is not None:
        members = tuple(
            session.scalars(
                select(CollectionQuerySnapshotMemberModel.record_id)
                .where(CollectionQuerySnapshotMemberModel.snapshot_id == retained.id)
                .order_by(CollectionQuerySnapshotMemberModel.ordinal)
                .limit(len(record_ids) + 1)
            )
        )
        if retained.exact_total != len(record_ids) or members != record_ids:
            raise CursorValidationError("The retained planning membership is invalid.")
        # TTL, quota reservation, source identity and ordering remain unchanged.
        return store._read_page(
            CollectionSnapshot(
                retained.id,
                definition,
                retained.exact_total,
                retained.created_at,
                retained.expires_at,
            ),
            after_ordinal=0,
            limit=limit,
        )
    page = store.materialize(definition, record_ids, limit=limit)
    session.add(
        PlanningCollectionBindingModel(
            owner_id=definition.owner_id,
            collection_snapshot_id=page.snapshot_id,
            cache_key=cache_key,
            request_id=source_id if source_kind == "request" else None,
            result_id=source_id if source_kind == "result" else None,
            run_id=source_id if source_kind == "run" else None,
        )
    )
    session.flush()
    return page
