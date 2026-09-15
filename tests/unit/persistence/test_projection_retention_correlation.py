"""Nested retention markers must not open an unrelated projection source relation."""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql.base import PGDialect
from trading212_persistence.historical_models import HistoricalRetentionEventModel
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.projection_retention_policy import projection_run_restricted
from trading212_persistence.source_models import SourceExpiryEventModel, SourceRetentionWorkModel


def test_nested_source_markers_keep_only_their_own_local_from_relation() -> None:
    # Correlation is a correctness property of the emitted SQL: a nested local
    # projection_run_sources FROM would match another owner's retained source.
    query = select(PremiumRunModel.id).where(
        projection_run_restricted(datetime(2026, 9, 15, tzinfo=UTC))
    )
    sql = str(query.compile(dialect=PGDialect()))  # type: ignore[no-untyped-call]  # SQLAlchemy dialect constructor.
    for model, count in (
        (HistoricalRetentionEventModel, 1),
        (SourceExpiryEventModel, 2),
        (SourceRetentionWorkModel, 2),
    ):
        table = model.__tablename__
        clauses = re.findall(
            r"SELECT\s+" + re.escape(table) + r"\.id\s+FROM\s+(.*?)\s+WHERE", sql, flags=re.DOTALL
        )
        assert len(clauses) == count
        assert all(clause.strip() == table for clause in clauses), clauses
