"""Closed metadata-only SQL predicates for physical cleanup, never read authority."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

from .premium_models import PremiumRunModel


def projection_original_restricted(at: datetime) -> ColumnElement[bool]:
    return cast(
        ColumnElement[bool], func.projection_original_sources_restricted(PremiumRunModel.id, at)
    )


def projection_source_matches(
    owner: UUID,
    kind: Literal["price", "fx", "corporate_action", "benchmark", "historical"],
    source_id: UUID,
) -> ColumnElement[bool]:
    if kind not in ("price", "fx", "corporate_action", "benchmark", "historical"):
        raise ValueError("A closed projection source family is required.")
    return cast(
        ColumnElement[bool],
        func.projection_references_source(owner, PremiumRunModel.id, kind, source_id),
    )
