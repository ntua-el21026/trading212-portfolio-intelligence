"""Canonical UUID identity aliases and validation."""

from __future__ import annotations

from typing import NewType
from uuid import UUID, uuid4

from .errors import fail_validation

OwnerId = NewType("OwnerId", UUID)
PrincipalId = NewType("PrincipalId", UUID)
BrokerConnectionId = NewType("BrokerConnectionId", UUID)
BrokerAccountId = NewType("BrokerAccountId", UUID)
InstrumentId = NewType("InstrumentId", UUID)
ListingId = NewType("ListingId", UUID)
IngestionRunId = NewType("IngestionRunId", UUID)
SourceRecordId = NewType("SourceRecordId", UUID)
TransactionId = NewType("TransactionId", UUID)
CashFlowId = NewType("CashFlowId", UUID)
DividendId = NewType("DividendId", UUID)
OrderObservationId = NewType("OrderObservationId", UUID)
PositionObservationId = NewType("PositionObservationId", UUID)
CashObservationId = NewType("CashObservationId", UUID)
LedgerEntryId = NewType("LedgerEntryId", UUID)
SnapshotId = NewType("SnapshotId", UUID)
ReconciliationRunId = NewType("ReconciliationRunId", UUID)
DiscrepancyId = NewType("DiscrepancyId", UUID)
CalculationRunId = NewType("CalculationRunId", UUID)
AuditEventId = NewType("AuditEventId", UUID)

type CanonicalId = UUID


def new_id() -> UUID:
    return uuid4()


def require_uuid(value: UUID, *, field: str) -> UUID:
    if not isinstance(value, UUID):
        fail_validation(f"{field} must be a UUID", field=field)
    return value
