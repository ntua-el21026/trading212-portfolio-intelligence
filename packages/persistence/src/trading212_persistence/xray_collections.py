"""X-ray collection identity, current authorization pins and shared reservations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application.queries import CursorCodec, CursorValidationError
from trading212_application.xray import XrayServiceErrorCode

from .collection_snapshots import (
    CollectionSnapshot,
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotStore,
    _cursor_binding,
    _cursor_resource,
)
from .models import CollectionQuerySnapshotModel
from .xray_base import xray_error
from .xray_run_models import XrayCollectionBindingModel


def cursor_parent(
    session: Session,
    codec: CursorCodec,
    definition: CollectionSnapshotDefinition,
    cursor: str,
) -> XrayCollectionBindingModel:
    """Decode only the scope-bound identity; callers authorize the run before any payload read."""
    try:
        created, key = codec.decode(
            cursor,
            resource=_cursor_resource(definition.resource),
            binding=_cursor_binding(definition),
            key_size=2,
        )
        identifier = UUID(key[0])
        after = int(key[1])
        if after < 1:
            raise CursorValidationError("Invalid X-ray cursor.")
        row = session.scalar(
            select(XrayCollectionBindingModel)
            .join(
                CollectionQuerySnapshotModel,
                CollectionQuerySnapshotModel.id == XrayCollectionBindingModel.collection_id,
            )
            .where(
                XrayCollectionBindingModel.owner_id == definition.owner_id,
                CollectionQuerySnapshotModel.id == identifier,
                CollectionQuerySnapshotModel.owner_id == definition.owner_id,
                CollectionQuerySnapshotModel.broker_account_id == definition.broker_account_id,
                CollectionQuerySnapshotModel.resource == definition.resource.value,
                CollectionQuerySnapshotModel.filter_fingerprint == definition.filter_fingerprint,
                CollectionQuerySnapshotModel.sort_specification == definition.sort_specification,
                CollectionQuerySnapshotModel.created_at == created,
                CollectionQuerySnapshotModel.expires_at > func.now(),
                CollectionQuerySnapshotModel.exact_total > after,
            )
        )
        if row is None:
            raise CursorValidationError("Invalid X-ray cursor.")
        return row
    except (CursorValidationError, ValueError, TypeError):
        raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED) from None


def retained_first_page(
    session: Session,
    store: CollectionSnapshotStore,
    definition: CollectionSnapshotDefinition,
    *,
    run_id: UUID | None,
    source_id: UUID | None,
    limit: int,
) -> CollectionSnapshotPage | None:
    if (run_id is None) == (source_id is None):
        raise ValueError("A collection must bind exactly one retained parent.")
    row = session.scalar(
        select(CollectionQuerySnapshotModel)
        .join(
            XrayCollectionBindingModel,
            XrayCollectionBindingModel.collection_id == CollectionQuerySnapshotModel.id,
        )
        .where(
            XrayCollectionBindingModel.owner_id == definition.owner_id,
            XrayCollectionBindingModel.run_id == run_id,
            XrayCollectionBindingModel.constituent_snapshot_id == source_id,
            CollectionQuerySnapshotModel.owner_id == definition.owner_id,
            CollectionQuerySnapshotModel.broker_account_id == definition.broker_account_id,
            CollectionQuerySnapshotModel.resource == definition.resource.value,
            CollectionQuerySnapshotModel.filter_fingerprint == definition.filter_fingerprint,
            CollectionQuerySnapshotModel.sort_specification == definition.sort_specification,
            CollectionQuerySnapshotModel.expires_at > func.now(),
        )
        .order_by(
            CollectionQuerySnapshotModel.created_at.desc(), CollectionQuerySnapshotModel.id.desc()
        )
        .limit(1)
    )
    if row is None:
        return None
    # The immutable run and exact filters fix membership. Do not extend its TTL
    # or allocate another collection simply because the caller changes page size.
    return store._read_page(
        CollectionSnapshot(
            row.id,
            definition,
            row.exact_total,
            row.created_at,
            row.expires_at,
        ),
        after_ordinal=0,
        limit=limit,
    )


def bind_collection(
    session: Session,
    definition: CollectionSnapshotDefinition,
    collection_id: UUID,
    *,
    run_id: UUID | None,
    source_id: UUID | None,
) -> None:
    if (run_id is None) == (source_id is None):
        raise ValueError("A collection must bind exactly one retained parent.")
    session.add(
        XrayCollectionBindingModel(
            owner_id=definition.owner_id,
            collection_id=collection_id,
            run_id=run_id,
            constituent_snapshot_id=source_id,
        )
    )
    session.flush()


def generated_page(
    session: Session,
    store: CollectionSnapshotStore,
    definition: CollectionSnapshotDefinition,
    *,
    run_id: UUID | None,
    source_id: UUID | None,
    exact_total: int,
    create_records: Callable[[UUID], Iterable[UUID]],
    limit: int,
) -> CollectionSnapshotPage:
    def create(identifier: UUID) -> Iterable[UUID]:
        # The reservation and parent exist before the first projection payload.
        bind_collection(session, definition, identifier, run_id=run_id, source_id=source_id)
        return create_records(identifier)

    return store.materialize_generated(
        definition,
        exact_total=exact_total,
        create_records=create,
        limit=limit,
    )
