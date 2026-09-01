"""PostgreSQL persistence adapters for the Phase 1 canonical model."""

from .base import Base
from .collection_snapshots import (
    COLLECTION_SNAPSHOT_SCHEMA_VERSION,
    DEFAULT_MAX_ACTIVE_COLLECTION_MEMBERS_PER_OWNER,
    DEFAULT_MAX_ACTIVE_COLLECTION_SNAPSHOTS_PER_OWNER,
    CollectionSnapshot,
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotScopeError,
    CollectionSnapshotStore,
    cleanup_expired_collection_snapshots,
    collection_filter_fingerprint,
)
from .database import UnitOfWork, create_database_engine, create_session_factory
from .dispatcher_readiness import refresh_dispatcher_is_ready
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
    "COLLECTION_SNAPSHOT_SCHEMA_VERSION",
    "DEFAULT_MAX_ACTIVE_COLLECTION_MEMBERS_PER_OWNER",
    "DEFAULT_MAX_ACTIVE_COLLECTION_SNAPSHOTS_PER_OWNER",
    "AccountRepository",
    "Base",
    "CheckpointRepository",
    "CollectionSnapshot",
    "CollectionSnapshotDefinition",
    "CollectionSnapshotPage",
    "CollectionSnapshotResource",
    "CollectionSnapshotScopeError",
    "CollectionSnapshotStore",
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
    "cleanup_expired_collection_snapshots",
    "collection_filter_fingerprint",
    "create_database_engine",
    "create_session_factory",
    "refresh_dispatcher_is_ready",
]
