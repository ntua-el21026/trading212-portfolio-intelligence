"""PostgreSQL persistence adapters for the Phase 1 canonical model."""

from .base import Base
from .database import UnitOfWork, create_database_engine, create_session_factory
from .models import ALL_MODELS
from .portfolio_service import PostgresPortfolioService
from .repositories import (
    AccountRepository,
    CheckpointRepository,
    ReconciliationDiscrepancyWrite,
    ReconciliationPersistenceResult,
    ReconciliationRepository,
    SnapshotPersistenceResult,
    SnapshotRepository,
    SnapshotWriteContext,
    SourceRecordRepository,
)
from .types import ExactNumeric, UTCDateTime

__all__ = [
    "ALL_MODELS",
    "AccountRepository",
    "Base",
    "CheckpointRepository",
    "ExactNumeric",
    "PostgresPortfolioService",
    "ReconciliationDiscrepancyWrite",
    "ReconciliationPersistenceResult",
    "ReconciliationRepository",
    "SnapshotPersistenceResult",
    "SnapshotRepository",
    "SnapshotWriteContext",
    "SourceRecordRepository",
    "UTCDateTime",
    "UnitOfWork",
    "create_database_engine",
    "create_session_factory",
]
