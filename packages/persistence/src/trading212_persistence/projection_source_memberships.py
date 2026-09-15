"""Closed physical lineage emitted by the authorized projection source resolver.

This private index is a retention blocker, never authorization to decode a source.
It preserves no financial data and does not broaden historical evidence admission.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import projection as app

from .projection_definition_store import ProjectionStorageError
from .projection_models import ProjectionRetainedSourceModel
from .report_authorization import ReportAuthorization

if TYPE_CHECKING:
    from .projection_source_store import ProjectionSourceHeader

MAX_RETAINED_SOURCE_MEMBERSHIPS = 100_000
SOURCE_KINDS = frozenset(
    ("price", "fx", "corporate_action", "benchmark", "historical", "license", "classification")
)


def retained_source_keys(
    headers: Sequence[ProjectionSourceHeader],
) -> tuple[tuple[str, UUID, datetime], ...]:
    """Deduplicate complete authorized metadata, rejecting a missing direct root."""
    keys: dict[tuple[str, UUID], datetime] = {}
    for header in headers:
        expected = {
            "price_total_return": "price",
            "benchmark_total_return": "benchmark",
            "historical_input": "historical",
        }.get(header.kind)
        if header.kind == "portfolio_snapshot":
            if header.retained_sources:
                raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
            continue
        if expected is None or (expected, header.subject_id) not in {
            (kind, identifier) for kind, identifier, _ in header.retained_sources
        }:
            raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
        for kind, identifier, original_at in header.retained_sources:
            if kind not in SOURCE_KINDS or not isinstance(identifier, UUID):
                raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
            if not isinstance(original_at, datetime) or original_at.utcoffset() != timedelta(0):
                raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
            key = (kind, identifier)
            keys[key] = min(keys.get(key, original_at), original_at)
            if len(keys) > MAX_RETAINED_SOURCE_MEMBERSHIPS:
                raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
    return tuple((kind, identifier, keys[(kind, identifier)]) for kind, identifier in sorted(keys))


def verify_retained_source_keys(
    session: Session,
    auth: ReportAuthorization,
    run_id: UUID,
    headers: Sequence[ProjectionSourceHeader],
) -> None:
    expected = retained_source_keys(headers)
    model = ProjectionRetainedSourceModel
    actual = tuple(
        (row.source_kind, row.source_id, row.original_created_at)
        for row in session.execute(
            select(model.source_kind, model.source_id, model.original_created_at)
            .where(
                model.owner_id == auth.owner_id,
                model.account_id == auth.account_id,
                model.run_id == run_id,
            )
            .order_by(model.source_kind, model.source_id)
            .limit(MAX_RETAINED_SOURCE_MEMBERSHIPS + 1)
        )
    )
    if actual != expected:
        raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
