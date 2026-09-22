"""Physical owner-layout erasure using the existing shared row/byte allowance."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, delete, select, text, update
from sqlalchemy.orm import Session
from trading212_domain.values import require_utc

from .owner_layout_models import (
    OwnerLayoutCommandModel,
    OwnerLayoutErasureModel,
    OwnerLayoutModel,
    SavedLayoutWidgetModel,
    SavedViewVersionModel,
)
from .source_retention import PayloadCopyCost, SourcePurgeBudget
from .source_retention_sql import logical_payload_size

# Each deletion covers the target, marker/owner lock checks, reverse FK probes and
# fixed trigger/constraint work. No full version validator runs during erasure.
_LAYOUT_DELETE_INSPECTIONS = 32
_LAYOUT_MARKER_INSPECTIONS = 12


def _remove_one(
    session: Session, table: Table, owner: UUID, identifier: UUID, budget: SourcePurgeBudget
) -> bool:
    if not budget.inspect(rows=1):
        return False
    row = session.execute(
        select(
            table.c.id,
            logical_payload_size(table, tuple(column.name for column in table.columns)).label(
                "payload_bytes"
            ),
        )
        .where(table.c.owner_id == owner, table.c.id == identifier)
        .with_for_update()
    ).one_or_none()
    if row is None:
        return True
    permitted = budget.reserve_clear_batch(
        (
            PayloadCopyCost(
                row_id=row.id,
                payload_bytes=row.payload_bytes,
                inspection_rows=_LAYOUT_DELETE_INSPECTIONS,
                payload_inspections=2,
            ),
        )
    )
    if not permitted:
        return False
    session.execute(delete(table).where(table.c.owner_id == owner, table.c.id == identifier))
    return True


def purge_owner_layouts(
    session: Session, owner: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    """Terminate layout access, then drain commands/widgets/versions/headers in order.

    Call only from the operator-owned erasure composition. This grants no public
    erasure capability. The SQL marker rejects owners with any active principal
    or connection; ordinary archive never clears content or its capacity charge.
    """
    at = require_utc(at)
    if type(owner) is not UUID:
        raise ValueError("An exact layout owner is required.")
    if not budget.inspect(rows=_LAYOUT_MARKER_INSPECTIONS):
        return False
    locked = session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"preferences:{owner}"},
    )
    if not locked:
        return False
    marker = session.get(OwnerLayoutErasureModel, owner, with_for_update=True)
    if marker is None:
        marker = OwnerLayoutErasureModel(owner_id=owner, created_at=at, completed_at=None)
        session.add(marker)
        session.flush()
    if marker.completed_at is not None:
        return True
    roots = cast(Table, OwnerLayoutModel.__table__)
    versions = cast(Table, SavedViewVersionModel.__table__)
    commands = cast(Table, OwnerLayoutCommandModel.__table__)
    widgets = cast(Table, SavedLayoutWidgetModel.__table__)
    while budget.inspect(rows=1):
        root = session.execute(
            select(roots.c.id, roots.c.state)
            .where(roots.c.owner_id == owner)
            .order_by(roots.c.created_at, roots.c.id)
            .limit(1)
            .with_for_update()
        ).one_or_none()
        if root is None:
            if not budget.inspect(rows=_LAYOUT_MARKER_INSPECTIONS):
                return False
            marker.completed_at = at
            session.flush()
            return True
        if not budget.enter_capture("layout", root.id):
            return False
        if root.state != "erasing":
            if not budget.reserve_clear_batch(
                (
                    PayloadCopyCost(
                        row_id=root.id,
                        payload_bytes=16,
                        inspection_rows=_LAYOUT_DELETE_INSPECTIONS,
                        payload_inspections=1,
                    ),
                )
            ):
                return False
            # The marker alone authorizes this internal state. Removing only this
            # pointer permits whole-version deletion across separate transactions.
            session.execute(
                update(roots)
                .where(roots.c.owner_id == owner, roots.c.id == root.id)
                .values(state="erasing", current_version_id=None)
            )
        while budget.inspect(rows=1):
            version = session.scalar(
                select(versions.c.id)
                .where(versions.c.owner_id == owner, versions.c.layout_id == root.id)
                .order_by(versions.c.version_number.desc())
                .limit(1)
            )
            if version is None:
                break
            for table, order in (
                (commands, commands.c.result_revision),
                (widgets, widgets.c.ordinal),
            ):
                while budget.inspect(rows=1):
                    child = session.scalar(
                        select(table.c.id)
                        .where(table.c.owner_id == owner, table.c.version_id == version)
                        .order_by(order)
                        .limit(1)
                    )
                    if child is None:
                        break
                    if not _remove_one(session, table, owner, child, budget):
                        return False
                else:
                    return False
            if not _remove_one(session, versions, owner, version, budget):
                return False
        else:
            return False
        if not _remove_one(session, roots, owner, root.id, budget):
            return False
    return False
