"""Indexed payload removal using the shared expiry allowance.

Only fixed persistence participants supply tables and columns. These helpers are
not an application query interface and do not grant retention authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    Integer,
    LargeBinary,
    Table,
    Text,
    Uuid,
    case,
    delete,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .premium_retention_costs import premium_mutation_cost
from .projection_retention_costs import projection_mutation_cost
from .research_retention_costs import research_mutation_cost
from .source_retention import PayloadCopyCost, SourcePurgeBudget
from .types import UTCDateTime


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadPurgeResult:
    complete: bool
    removed_rows: int
    removed_bytes: int


def logical_payload_size(table: Table, names: tuple[str, ...]) -> ColumnElement[int]:
    """Logical bytes of the exact copied columns, without client materialization.

    BYTEA/text use uncompressed content length; Q18 numerics use their exact
    PostgreSQL textual representation. Copied UUID/date/time/bool/integer values
    use fixed 16/4/8/1/4 byte logical widths. NULL and an empty blob cost zero.
    Identity/audit columns kept as tombstones are omitted by the fixed caller.
    """
    size: ColumnElement[int] = literal(0)
    for name in names:
        column = table.c[name]
        kind = column.type
        width = (
            16
            if isinstance(kind, Uuid)
            else 8
            if isinstance(kind, UTCDateTime)
            else 8
            if isinstance(kind, BigInteger)
            else 4
            if isinstance(kind, (Date, Integer))
            else 1
            if isinstance(kind, Boolean)
            else None
        )
        if isinstance(kind, ARRAY) and isinstance(kind.item_type, Uuid):
            size = size + func.coalesce(func.cardinality(column), 0) * 16
        elif width is not None:
            size = size + case((column.is_(None), 0), else_=width)
        else:
            value = column if isinstance(kind, LargeBinary) else column.cast(Text)
            size = size + func.coalesce(func.octet_length(value), 0)
    return size


def purge_payload_rows(
    session: Session,
    table: Table,
    predicate: ColumnElement[bool],
    *,
    payload_columns: tuple[str, ...],
    delete_rows: bool,
    budget: SourcePurgeBudget,
) -> PayloadPurgeResult:
    """Clear/delete only bounded locked IDs; false leaves their parent pending.

    For clearing, payload_columns is the full closed set authorized by the SQL
    retention guard. A partial index on parent/id with this same remaining-payload
    predicate supports resumption without scanning every already-cleared row.
    Callers must hold their ordinary exact-source/owner lock throughout.
    """
    if not payload_columns or len(set(payload_columns)) != len(payload_columns):
        raise ValueError("A fixed nonempty payload column inventory is required.")
    cleared = {
        name: b"" if isinstance(table.c[name].type, LargeBinary) else None
        for name in payload_columns
    }
    remaining = (
        predicate
        if delete_rows
        else predicate
        & or_(
            *(
                table.c[name] != b"" if value == b"" else table.c[name].is_not(None)
                for name, value in cleared.items()
            )
        )
    )
    size = logical_payload_size(table, payload_columns)
    cost = (
        premium_mutation_cost(table.name, delete_rows=delete_rows)
        or research_mutation_cost(table.name, delete_rows=delete_rows)
        or projection_mutation_cost(table.name, delete_rows=delete_rows)
    )
    removed_rows = 0
    removed_bytes = 0
    while budget.metadata_limit:
        # Parent scope joins and all triggered row inspections are reserved before
        # choosing a batch. A small remainder never fetches a row it cannot mutate.
        if budget.rows_inspected < cost.scope_rows + 1 + cost.mutation_rows:
            break
        if not budget.inspect(rows=cost.scope_rows):
            break
        metadata = session.execute(
            select(table.c.id, size.label("payload_bytes"))
            .where(remaining)
            .order_by(table.c.id)
            # Metadata and mutation each inspect the row. Reserve room for both
            # so a small remaining allowance cannot spend every pass on metadata.
            .limit(
                min(
                    budget.metadata_limit,
                    budget.rows_inspected // (1 + cost.mutation_rows),
                    512 // cost.mutation_rows,
                )
            )
            .with_for_update(skip_locked=True)
        ).all()
        if not budget.inspect(rows=len(metadata)):
            raise RuntimeError("Source expiry metadata exceeded its reserved row bound.")
        if not metadata:
            # SKIP LOCKED alone cannot prove completion while another writer owns
            # a remaining row. This indexed probe is charged if it returns an ID.
            if budget.rows_inspected < cost.scope_rows + 1:
                break
            if not budget.inspect(rows=cost.scope_rows):
                break
            pending = session.scalar(select(table.c.id).where(remaining).limit(1))
            if pending is not None:
                if not budget.inspect(rows=1):
                    raise RuntimeError("Source expiry completion probe exceeded its row bound.")
                break
            return PayloadPurgeResult(
                complete=True, removed_rows=removed_rows, removed_bytes=removed_bytes
            )
        costs = tuple(
            PayloadCopyCost(
                row_id=row.id,
                payload_bytes=row.payload_bytes,
                inspection_rows=cost.mutation_rows,
                payload_inspections=cost.payload_inspections,
            )
            for row in metadata
        )
        ids = budget.reserve_clear_batch(costs)
        if not ids:
            break
        bounded = remaining & table.c.id.in_(ids)
        statement = (
            delete(table).where(bounded)
            if delete_rows
            else (update(table).where(bounded).values(**cleared))
        )
        result = cast(CursorResult[tuple[object, ...]], session.execute(statement))
        if result.rowcount != len(ids):
            raise RuntimeError("Retained payload changed during locked source expiry.")
        removed_rows += len(ids)
        removed_bytes += sum(cost.payload_bytes for cost in costs[: len(ids)])
        if len(ids) != len(costs):
            break
    return PayloadPurgeResult(
        complete=False, removed_rows=removed_rows, removed_bytes=removed_bytes
    )
