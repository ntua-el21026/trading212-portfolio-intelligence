"""Deterministic synthetic acceptance scenarios through production persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_analytics import (
    RECONCILIATION_VERSION,
    CashBridgeInput,
    QuantityBridgeInput,
    reconcile_portfolio,
)
from trading212_domain import (
    BrokerAccountId,
    Coverage,
    CurrencyCode,
    DiscrepancyId,
    Instant,
    ListingId,
    Money,
    ProvenanceReference,
    Quantity,
    ReconciliationDiscrepancy,
    ReconciliationRun,
    ReconciliationRunId,
    ResolutionState,
    SourceRecordId,
    ValueOrigin,
    canonical_json,
)
from trading212_persistence.models import SourceRecordModel
from trading212_persistence.repositories import (
    ReconciliationDiscrepancyWrite,
    ReconciliationRepository,
)

_SCENARIO_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "trading212-portfolio-intelligence/phase-1-acceptance-scenarios",
)
_MAPPING_VERSION = "synthetic-mismatch-scenario/1.0.0"


def persist_quantity_cash_mismatch_scenario(
    session: Session,
    *,
    account_id: UUID,
    listing_id: UUID,
    as_of: datetime,
) -> UUID:
    """Persist one reproducible quantity/cash mismatch using the real domain gate.

    The fixture is restricted to retained synthetic source evidence. It gives the
    browser, REST API, and MCP acceptance tests one identical immutable scenario
    without pretending that the real provider exposes an opening balance.
    """

    observed_at = _utc(as_of)
    source_records = tuple(
        session.scalars(
            select(SourceRecordModel)
            .where(
                SourceRecordModel.broker_account_id == account_id,
                SourceRecordModel.provider == "synthetic",
            )
            .order_by(SourceRecordModel.observed_at, SourceRecordModel.id)
        )
    )
    if not source_records:
        raise ValueError("synthetic mismatch scenario requires retained source evidence")
    if max(record.observed_at for record in source_records) > observed_at:
        raise ValueError("synthetic mismatch scenario cannot precede its source evidence")

    broker_account_id = BrokerAccountId(account_id)
    canonical_listing_id = ListingId(listing_id)
    currency = CurrencyCode("EUR")
    result = reconcile_portfolio(
        account_id=broker_account_id,
        quantity_bridges=(
            QuantityBridgeInput(
                account_id=broker_account_id,
                listing_id=canonical_listing_id,
                opening_quantity=Quantity(Decimal("0")),
                buys=(Quantity(Decimal("10")),),
                closing_quantity=Quantity(Decimal("9")),
                coverage_complete=True,
            ),
        ),
        cash_bridges=(
            CashBridgeInput(
                account_id=broker_account_id,
                opening_cash=Money(Decimal("0"), currency),
                deposits=(Money(Decimal("10000"), currency),),
                buy_outflows=(Money(Decimal("9000"), currency),),
                closing_cash=Money(Decimal("999"), currency),
                coverage_complete=True,
            ),
        ),
    )
    expected_types = {"quantity_mismatch", "cash_mismatch"}
    if (
        result.status.value != "unreconciled"
        or result.quality_state.value != "unreconciled"
        or {issue.discrepancy_type.value for issue in result.discrepancies} != expected_types
    ):
        raise RuntimeError("synthetic mismatch scenario did not fail closed")

    input_document = {
        "account_id": str(account_id),
        "as_of": observed_at,
        "cash": {"closing": "999", "deposits": ["10000"], "opening": "0"},
        "listing_id": str(listing_id),
        "mapping_version": _MAPPING_VERSION,
        "quantity": {"buys": ["10"], "closing": "9", "opening": "0"},
        "source_record_ids": [str(record.id) for record in source_records],
    }
    input_fingerprint = hashlib.sha256(canonical_json(input_document).encode()).hexdigest()
    run_id = ReconciliationRunId(
        uuid5(_SCENARIO_NAMESPACE, f"reconciliation:{account_id}:{input_fingerprint}")
    )
    provenance = ProvenanceReference(
        source_record_ids=tuple(SourceRecordId(record.id) for record in source_records),
        mapping_version=_MAPPING_VERSION,
        origin=ValueOrigin.DERIVED_DETERMINISTIC,
    )
    run = ReconciliationRun(
        id=run_id,
        broker_account_id=broker_account_id,
        as_of=Instant(observed_at),
        algorithm_version=RECONCILIATION_VERSION,
        tolerance_version=result.tolerance_version,
        status=result.status,
        coverage=Coverage(
            start_at=Instant(
                min(record.source_updated_at or record.observed_at for record in source_records)
            ),
            end_at=Instant(max(record.observed_at for record in source_records)),
            complete=True,
        ),
        discrepancy_count=len(result.discrepancies),
        warnings=result.warnings,
    )
    discrepancies = tuple(
        ReconciliationDiscrepancyWrite(
            discrepancy=ReconciliationDiscrepancy(
                id=DiscrepancyId(
                    uuid5(
                        _SCENARIO_NAMESPACE,
                        f"discrepancy:{run_id}:{issue.discrepancy_type.value}:{issue.scope}",
                    )
                ),
                reconciliation_run_id=run_id,
                broker_account_id=broker_account_id,
                listing_id=issue.listing_id,
                discrepancy_type=issue.discrepancy_type,
                severity=issue.severity,
                resolution_state=ResolutionState.OPEN,
                first_seen_at=Instant(observed_at),
                last_seen_at=Instant(observed_at),
                expected_value=issue.expected,
                observed_value=issue.observed,
                residual=issue.residual,
                tolerance=issue.tolerance,
                currency=issue.currency,
                likely_cause="Deterministic synthetic source mismatch.",
                downstream_effect=issue.downstream_effect,
            ),
            provenance=provenance,
        )
        for issue in result.discrepancies
    )
    persisted = ReconciliationRepository(session).persist_immutable(
        run,
        input_fingerprint=input_fingerprint,
        quality_state=result.quality_state,
        provenance=provenance,
        discrepancies=discrepancies,
    )
    return persisted.reconciliation_run_id


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scenario timestamp must be timezone-aware")
    return value.astimezone(UTC)
