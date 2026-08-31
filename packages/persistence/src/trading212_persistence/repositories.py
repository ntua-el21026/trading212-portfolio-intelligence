"""Owner-scoped and idempotent repositories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from trading212_domain import (
    CurrencyCode,
    Instant,
    ListingId,
    PortfolioSnapshot,
    ProvenanceReference,
    QualityState,
    ReconciliationDiscrepancy,
    ReconciliationRun,
    ReconciliationStatus,
    ResolutionState,
    to_primitive,
)

from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CalculationRunModel,
    IngestionCheckpointModel,
    PortfolioSnapshotModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _owned_query(owner_id: UUID) -> Select[tuple[BrokerAccountModel]]:
        return (
            select(BrokerAccountModel)
            .join(
                BrokerConnectionModel,
                BrokerConnectionModel.id == BrokerAccountModel.connection_id,
            )
            .where(BrokerConnectionModel.owner_id == owner_id)
        )

    def get_owned(self, owner_id: UUID, account_id: UUID) -> BrokerAccountModel | None:
        query = self._owned_query(owner_id).where(BrokerAccountModel.id == account_id)
        return self._session.scalar(query)

    def list_owned(self, owner_id: UUID, *, limit: int = 100) -> tuple[BrokerAccountModel, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("account list limit must be between 1 and 100")
        query = self._owned_query(owner_id).order_by(BrokerAccountModel.id).limit(limit)
        return tuple(self._session.scalars(query))


class SourceRecordRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_idempotent(self, values: dict[str, Any]) -> tuple[UUID, bool]:
        """Insert once by account/capability/fingerprint and return `(id, created)`."""

        values.setdefault("id", uuid4())
        statement = (
            insert(SourceRecordModel)
            .values(**values)
            .on_conflict_do_nothing()
            .returning(SourceRecordModel.id)
        )
        inserted = self._session.scalar(statement)
        if inserted is not None:
            return inserted, True
        identity_predicate = (
            SourceRecordModel.provider_record_id == values["provider_record_id"]
            if values.get("provider_record_id") is not None
            else SourceRecordModel.provider_record_id.is_(None)
        )
        existing = self._session.scalar(
            select(SourceRecordModel.id).where(
                SourceRecordModel.broker_account_id == values["broker_account_id"],
                SourceRecordModel.capability == values["capability"],
                identity_predicate,
                SourceRecordModel.payload_fingerprint == values["payload_fingerprint"],
            )
        )
        if existing is None:
            raise RuntimeError("source record conflict did not resolve to an existing row")
        return existing, False


class CheckpointRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_update(self, account_id: UUID, capability: str) -> IngestionCheckpointModel | None:
        return self._session.scalar(
            select(IngestionCheckpointModel)
            .where(
                IngestionCheckpointModel.broker_account_id == account_id,
                IngestionCheckpointModel.capability == capability,
            )
            .with_for_update()
        )

    def advance(
        self,
        *,
        account_id: UUID,
        capability: str,
        state: dict[str, Any],
        run_id: UUID,
        coverage_start_at: datetime | None,
        coverage_end_at: datetime | None,
        coverage_complete: bool,
    ) -> IngestionCheckpointModel:
        checkpoint = self.get_for_update(account_id, capability)
        if checkpoint is None:
            checkpoint = IngestionCheckpointModel(
                broker_account_id=account_id,
                capability=capability,
                state=state,
                version=1,
                coverage_start_at=coverage_start_at,
                coverage_end_at=coverage_end_at,
                coverage_complete=coverage_complete,
                advanced_by_run_id=run_id,
            )
            self._session.add(checkpoint)
        else:
            checkpoint.state = state
            checkpoint.version += 1
            checkpoint.coverage_start_at = coverage_start_at
            checkpoint.coverage_end_at = coverage_end_at
            checkpoint.coverage_complete = coverage_complete
            checkpoint.advanced_by_run_id = run_id
        self._session.flush()
        return checkpoint


@dataclass(frozen=True, slots=True)
class SnapshotWriteContext:
    input_schema_version: str
    output_schema_version: str
    input_fingerprint: str
    output_fingerprint: str
    position_currencies: Mapping[ListingId, CurrencyCode]
    position_provenance: Mapping[ListingId, ProvenanceReference]
    cash_provenance: Mapping[CurrencyCode, ProvenanceReference]


@dataclass(frozen=True, slots=True)
class SnapshotPersistenceResult:
    calculation_run_id: UUID
    snapshot_id: UUID
    calculation_run_created: bool
    snapshot_created: bool


@dataclass(frozen=True, slots=True)
class ReconciliationDiscrepancyWrite:
    discrepancy: ReconciliationDiscrepancy
    provenance: ProvenanceReference
    resolved_at: Instant | None = None
    resolved_by_principal_id: UUID | None = None

    def __post_init__(self) -> None:
        resolved = self.discrepancy.resolution_state is not ResolutionState.OPEN
        has_resolution_metadata = (
            self.resolved_at is not None or self.resolved_by_principal_id is not None
        )
        if not resolved and has_resolution_metadata:
            raise ValueError("open discrepancy cannot contain resolution metadata")
        if resolved and (
            self.discrepancy.resolution_reason is None
            or self.resolved_at is None
            or self.resolved_by_principal_id is None
        ):
            raise ValueError(
                "accepted/resolved discrepancy requires reason, time, and responsible principal"
            )
        if self.resolved_at is not None and self.resolved_at < self.discrepancy.last_seen_at:
            raise ValueError("discrepancy resolution cannot precede last observation")


@dataclass(frozen=True, slots=True)
class ReconciliationPersistenceResult:
    reconciliation_run_id: UUID
    created: bool
    discrepancy_count: int


def _validate_token(value: str, *, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{field} must contain 1..{maximum} safe characters")


def _json_object(value: object) -> dict[str, Any]:
    primitive = to_primitive(value)
    if not isinstance(primitive, dict):
        raise TypeError("expected a JSON object")
    return cast(dict[str, Any], primitive)


def _warning_objects(values: tuple[object, ...]) -> list[dict[str, Any]]:
    return [_json_object(value) for value in values]


def _assert_model_matches(
    model: object,
    expected: Mapping[str, object],
    *,
    label: str,
    ignored: frozenset[str] = frozenset(),
) -> None:
    mismatched = tuple(
        key
        for key, expected_value in expected.items()
        if key not in ignored and getattr(model, key) != expected_value
    )
    if mismatched:
        raise ValueError(f"immutable {label} conflict in fields: {', '.join(mismatched)}")


class SnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_idempotent(self, values: dict[str, Any]) -> tuple[UUID, bool]:
        values.setdefault("id", uuid4())
        statement = (
            insert(PortfolioSnapshotModel)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_portfolio_snapshots_reproducible_key")
            .returning(PortfolioSnapshotModel.id)
        )
        inserted = self._session.scalar(statement)
        if inserted is not None:
            return inserted, True
        existing = self._session.scalar(
            select(PortfolioSnapshotModel.id).where(
                PortfolioSnapshotModel.broker_account_id == values["broker_account_id"],
                PortfolioSnapshotModel.valuation_at == values["valuation_at"],
                PortfolioSnapshotModel.source_cutoff_at == values["source_cutoff_at"],
                PortfolioSnapshotModel.calculation_version == values["calculation_version"],
            )
        )
        if existing is None:
            raise RuntimeError("snapshot conflict did not resolve to an existing row")
        return existing, False

    def _persist_calculation_run(
        self,
        snapshot: PortfolioSnapshot,
        context: SnapshotWriteContext,
    ) -> tuple[UUID, bool]:
        metadata = snapshot.calculation
        for field, value in (
            ("input_schema_version", context.input_schema_version),
            ("output_schema_version", context.output_schema_version),
            ("input_fingerprint", context.input_fingerprint),
            ("output_fingerprint", context.output_fingerprint),
        ):
            _validate_token(value, field=field, maximum=128 if "fingerprint" in field else 32)
        values: dict[str, object] = {
            "id": metadata.run_id,
            "broker_account_id": snapshot.broker_account_id,
            "calculation_name": metadata.calculation_name,
            "version": metadata.version,
            "input_schema_version": context.input_schema_version,
            "output_schema_version": context.output_schema_version,
            "input_fingerprint": context.input_fingerprint,
            "output_fingerprint": context.output_fingerprint,
            "calculated_at": metadata.calculated_at.value,
            "valuation_at": metadata.valuation_at.value,
            "source_cutoff_at": metadata.source_cutoff_at.value,
            "reporting_currency": metadata.reporting_currency.value,
            "method": metadata.method,
            "assumptions": list(metadata.assumptions),
            "options": dict(metadata.options or {}),
            "input_ids": [str(value) for value in metadata.input_ids],
            "quality_state": metadata.data_quality.state.value,
            "coverage": _json_object(metadata.data_quality.coverage),
            "warnings": _warning_objects(cast(tuple[object, ...], metadata.data_quality.warnings)),
            "missing_inputs": list(metadata.data_quality.missing_inputs),
        }
        statement = (
            insert(CalculationRunModel)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_calculation_runs_reproducible_input")
            .returning(CalculationRunModel.id)
        )
        inserted = self._session.scalar(statement)
        if inserted is not None:
            return inserted, True
        existing = self._session.scalar(
            select(CalculationRunModel).where(
                CalculationRunModel.broker_account_id == snapshot.broker_account_id,
                CalculationRunModel.calculation_name == metadata.calculation_name,
                CalculationRunModel.version == metadata.version,
                CalculationRunModel.input_fingerprint == context.input_fingerprint,
            )
        )
        if existing is None:
            raise RuntimeError("calculation conflict did not resolve to an existing row")
        _assert_model_matches(
            existing,
            values,
            label="calculation run",
            ignored=frozenset(("id", "calculated_at")),
        )
        return existing.id, False

    @staticmethod
    def _validate_component_context(
        snapshot: PortfolioSnapshot,
        context: SnapshotWriteContext,
    ) -> None:
        metadata = snapshot.calculation
        if (
            metadata.valuation_at != snapshot.valuation_at
            or metadata.source_cutoff_at != snapshot.source_cutoff_at
            or metadata.reporting_currency != snapshot.reporting_currency
            or metadata.data_quality != snapshot.quality
        ):
            raise ValueError("snapshot calculation metadata does not match snapshot contract")
        listing_ids = tuple(position.listing_id for position in snapshot.positions)
        if len(set(listing_ids)) != len(listing_ids):
            raise ValueError("snapshot contains duplicate position listings")
        if set(context.position_currencies) != set(listing_ids):
            raise ValueError("position currency context does not exactly match snapshot positions")
        if set(context.position_provenance) != set(listing_ids):
            raise ValueError("position provenance does not exactly match snapshot positions")
        cash_currencies = tuple(component.amount.currency for component in snapshot.cash_components)
        if len(set(cash_currencies)) != len(cash_currencies):
            raise ValueError("snapshot contains duplicate cash currencies")
        if set(context.cash_provenance) != set(cash_currencies):
            raise ValueError("cash provenance does not exactly match snapshot cash currencies")

        for position in snapshot.positions:
            currency = context.position_currencies[position.listing_id]
            monetary = (position.market_value, position.cost_basis, position.unrealized_pnl)
            if any(value is not None and value.currency != currency for value in monetary):
                raise ValueError("position persistence currency disagrees with monetary value")
            if (
                position.current_price is not None
                and position.current_price.quote_currency != currency
            ):
                raise ValueError("position persistence currency disagrees with current price")

    @staticmethod
    def _position_values(
        snapshot_id: UUID,
        snapshot: PortfolioSnapshot,
        context: SnapshotWriteContext,
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "snapshot_id": snapshot_id,
                "listing_id": position.listing_id,
                "quantity": position.quantity.value,
                "current_price": (
                    None if position.current_price is None else position.current_price.value
                ),
                "market_value": (
                    None if position.market_value is None else position.market_value.amount
                ),
                "cost_basis": None if position.cost_basis is None else position.cost_basis.amount,
                "unrealized_pnl": (
                    None if position.unrealized_pnl is None else position.unrealized_pnl.amount
                ),
                "currency": context.position_currencies[position.listing_id].value,
                "quality_state": position.quality.value,
                "value_origin": position.origin.value,
                "provenance": _json_object(context.position_provenance[position.listing_id]),
            }
            for position in sorted(snapshot.positions, key=lambda item: str(item.listing_id))
        )

    @staticmethod
    def _cash_values(
        snapshot_id: UUID,
        snapshot: PortfolioSnapshot,
        context: SnapshotWriteContext,
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "snapshot_id": snapshot_id,
                "amount": component.amount.amount,
                "currency": component.amount.currency.value,
                "quality_state": component.quality.value,
                "value_origin": component.origin.value,
                "provenance": _json_object(context.cash_provenance[component.amount.currency]),
            }
            for component in sorted(
                snapshot.cash_components, key=lambda item: str(item.amount.currency)
            )
        )

    def _assert_existing_children(
        self,
        snapshot_id: UUID,
        expected_positions: tuple[dict[str, object], ...],
        expected_cash: tuple[dict[str, object], ...],
    ) -> None:
        positions = tuple(
            self._session.scalars(
                select(SnapshotPositionModel)
                .where(SnapshotPositionModel.snapshot_id == snapshot_id)
                .order_by(SnapshotPositionModel.listing_id)
            )
        )
        cash = tuple(
            self._session.scalars(
                select(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == snapshot_id)
                .order_by(SnapshotCashModel.currency)
            )
        )
        if len(positions) != len(expected_positions) or len(cash) != len(expected_cash):
            raise ValueError("immutable snapshot conflict in component cardinality")
        for position_model, expected in zip(positions, expected_positions, strict=True):
            _assert_model_matches(position_model, expected, label="snapshot position")
        for cash_model, expected in zip(cash, expected_cash, strict=True):
            _assert_model_matches(cash_model, expected, label="snapshot cash")

    def persist_immutable(
        self,
        snapshot: PortfolioSnapshot,
        *,
        context: SnapshotWriteContext,
    ) -> SnapshotPersistenceResult:
        """Atomically persist a complete snapshot graph or verify an exact retry."""

        self._validate_component_context(snapshot, context)
        calculation_run_id, calculation_created = self._persist_calculation_run(snapshot, context)
        values: dict[str, object] = {
            "id": snapshot.id,
            "broker_account_id": snapshot.broker_account_id,
            "calculation_run_id": calculation_run_id,
            "valuation_at": snapshot.valuation_at.value,
            "source_cutoff_at": snapshot.source_cutoff_at.value,
            "reporting_currency": snapshot.reporting_currency.value,
            "cash_total": None if snapshot.cash_total is None else snapshot.cash_total.amount,
            "invested_total": (
                None if snapshot.invested_total is None else snapshot.invested_total.amount
            ),
            "portfolio_total": (
                None if snapshot.portfolio_total is None else snapshot.portfolio_total.amount
            ),
            "net_contributions": (
                None if snapshot.net_contributions is None else snapshot.net_contributions.amount
            ),
            "calculation_version": snapshot.calculation.version,
            "quality_state": snapshot.quality.state.value,
            "coverage": _json_object(snapshot.quality.coverage),
            "warnings": _warning_objects(cast(tuple[object, ...], snapshot.warnings)),
        }
        statement = (
            insert(PortfolioSnapshotModel)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_portfolio_snapshots_reproducible_key")
            .returning(PortfolioSnapshotModel.id)
        )
        inserted = self._session.scalar(statement)
        if inserted is None:
            existing = self._session.scalar(
                select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.broker_account_id == snapshot.broker_account_id,
                    PortfolioSnapshotModel.valuation_at == snapshot.valuation_at.value,
                    PortfolioSnapshotModel.source_cutoff_at == snapshot.source_cutoff_at.value,
                    PortfolioSnapshotModel.calculation_version == snapshot.calculation.version,
                )
            )
            if existing is None:
                raise RuntimeError("snapshot conflict did not resolve to an existing row")
            _assert_model_matches(
                existing,
                values,
                label="portfolio snapshot",
                ignored=frozenset(("id",)),
            )
            snapshot_id = existing.id
            expected_positions = self._position_values(snapshot_id, snapshot, context)
            expected_cash = self._cash_values(snapshot_id, snapshot, context)
            self._assert_existing_children(snapshot_id, expected_positions, expected_cash)
            return SnapshotPersistenceResult(
                calculation_run_id=calculation_run_id,
                snapshot_id=snapshot_id,
                calculation_run_created=calculation_created,
                snapshot_created=False,
            )

        expected_positions = self._position_values(inserted, snapshot, context)
        expected_cash = self._cash_values(inserted, snapshot, context)
        self._session.add_all(
            [SnapshotPositionModel(**values) for values in expected_positions]
            + [SnapshotCashModel(**values) for values in expected_cash]
        )
        self._session.flush()
        return SnapshotPersistenceResult(
            calculation_run_id=calculation_run_id,
            snapshot_id=inserted,
            calculation_run_created=calculation_created,
            snapshot_created=True,
        )


class ReconciliationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _run_values(
        run: ReconciliationRun,
        *,
        input_fingerprint: str,
        quality_state: QualityState,
        provenance: ProvenanceReference,
    ) -> dict[str, object]:
        if run.coverage.start_at is None or run.coverage.end_at is None:
            raise ValueError("persisted reconciliation requires explicit coverage boundaries")
        expected_status = {
            QualityState.FAILED: ReconciliationStatus.FAILED,
            QualityState.UNRECONCILED: ReconciliationStatus.UNRECONCILED,
            QualityState.PARTIAL: ReconciliationStatus.PARTIAL,
            QualityState.ESTIMATED: ReconciliationStatus.RECONCILED,
            QualityState.STALE: ReconciliationStatus.RECONCILED,
            QualityState.FRESH: ReconciliationStatus.RECONCILED,
        }[quality_state]
        if run.status is not expected_status:
            raise ValueError("reconciliation status and quality state are inconsistent")
        if run.status is ReconciliationStatus.RECONCILED and run.discrepancy_count:
            raise ValueError("reconciled run cannot persist discrepancies")
        _validate_token(input_fingerprint, field="input_fingerprint", maximum=128)
        return {
            "id": run.id,
            "broker_account_id": run.broker_account_id,
            "as_of": run.as_of.value,
            "algorithm_version": run.algorithm_version,
            "tolerance_version": run.tolerance_version,
            "input_fingerprint": input_fingerprint,
            "status": run.status.value,
            "quality_state": quality_state.value,
            "coverage_start_at": run.coverage.start_at.value,
            "coverage_end_at": run.coverage.end_at.value,
            "coverage_complete": run.coverage.complete,
            "coverage_gaps": list(run.coverage.gaps),
            "discrepancy_count": run.discrepancy_count,
            "warnings": _warning_objects(cast(tuple[object, ...], run.warnings)),
            "provenance": _json_object(provenance),
        }

    @staticmethod
    def _discrepancy_values(
        item: ReconciliationDiscrepancyWrite,
        *,
        persisted_run_id: UUID,
    ) -> dict[str, object]:
        value = item.discrepancy
        return {
            "id": value.id,
            "reconciliation_run_id": persisted_run_id,
            "broker_account_id": value.broker_account_id,
            "listing_id": value.listing_id,
            "discrepancy_type": value.discrepancy_type.value,
            "severity": value.severity.value,
            "resolution_state": value.resolution_state.value,
            "expected_value": value.expected_value,
            "observed_value": value.observed_value,
            "residual": value.residual,
            "tolerance": value.tolerance,
            "currency": None if value.currency is None else value.currency.value,
            "first_seen_at": value.first_seen_at.value,
            "last_seen_at": value.last_seen_at.value,
            "likely_cause": value.likely_cause,
            "downstream_effect": value.downstream_effect,
            "resolution_reason": value.resolution_reason,
            "resolved_at": None if item.resolved_at is None else item.resolved_at.value,
            "resolved_by_principal_id": item.resolved_by_principal_id,
            "provenance": _json_object(item.provenance),
        }

    @staticmethod
    def _discrepancy_signature(values: Mapping[str, object]) -> tuple[object, ...]:
        fields = (
            "broker_account_id",
            "listing_id",
            "discrepancy_type",
            "severity",
            "resolution_state",
            "expected_value",
            "observed_value",
            "residual",
            "tolerance",
            "currency",
            "first_seen_at",
            "last_seen_at",
            "likely_cause",
            "downstream_effect",
            "resolution_reason",
            "resolved_at",
            "resolved_by_principal_id",
        )
        return (
            *tuple(values[field] for field in fields),
            json.dumps(values["provenance"], sort_keys=True),
        )

    def _assert_existing_discrepancies(
        self,
        run_id: UUID,
        expected: tuple[dict[str, object], ...],
    ) -> None:
        existing = tuple(
            self._session.scalars(
                select(ReconciliationDiscrepancyModel).where(
                    ReconciliationDiscrepancyModel.reconciliation_run_id == run_id
                )
            )
        )
        fields = (
            "broker_account_id",
            "listing_id",
            "discrepancy_type",
            "severity",
            "resolution_state",
            "expected_value",
            "observed_value",
            "residual",
            "tolerance",
            "currency",
            "first_seen_at",
            "last_seen_at",
            "likely_cause",
            "downstream_effect",
            "resolution_reason",
            "resolved_at",
            "resolved_by_principal_id",
            "provenance",
        )
        actual_values = tuple({key: getattr(model, key) for key in fields} for model in existing)
        expected_signatures = sorted(
            (self._discrepancy_signature(value) for value in expected),
            key=repr,
        )
        actual_signatures = sorted(
            (self._discrepancy_signature(value) for value in actual_values),
            key=repr,
        )
        if actual_signatures != expected_signatures:
            raise ValueError("immutable reconciliation conflict in discrepancies")

    def persist_immutable(
        self,
        run: ReconciliationRun,
        *,
        input_fingerprint: str,
        quality_state: QualityState,
        provenance: ProvenanceReference,
        discrepancies: tuple[ReconciliationDiscrepancyWrite, ...],
    ) -> ReconciliationPersistenceResult:
        """Atomically persist a reconciliation run and its immutable discrepancy set."""

        if run.discrepancy_count != len(discrepancies):
            raise ValueError("reconciliation discrepancy count does not match supplied records")
        if any(
            item.discrepancy.reconciliation_run_id != run.id
            or item.discrepancy.broker_account_id != run.broker_account_id
            for item in discrepancies
        ):
            raise ValueError("reconciliation discrepancy scope does not match run")
        ids = tuple(item.discrepancy.id for item in discrepancies)
        if len(set(ids)) != len(ids):
            raise ValueError("reconciliation contains duplicate discrepancy IDs")

        values = self._run_values(
            run,
            input_fingerprint=input_fingerprint,
            quality_state=quality_state,
            provenance=provenance,
        )
        statement = (
            insert(ReconciliationRunModel)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_reconciliation_runs_reproducible_key")
            .returning(ReconciliationRunModel.id)
        )
        inserted = self._session.scalar(statement)
        if inserted is None:
            existing = self._session.scalar(
                select(ReconciliationRunModel).where(
                    ReconciliationRunModel.broker_account_id == run.broker_account_id,
                    ReconciliationRunModel.as_of == run.as_of.value,
                    ReconciliationRunModel.algorithm_version == run.algorithm_version,
                    ReconciliationRunModel.input_fingerprint == input_fingerprint,
                )
            )
            if existing is None:
                raise RuntimeError("reconciliation conflict did not resolve to an existing row")
            _assert_model_matches(
                existing,
                values,
                label="reconciliation run",
                ignored=frozenset(("id",)),
            )
            persisted_id = existing.id
            expected = tuple(
                self._discrepancy_values(item, persisted_run_id=persisted_id)
                for item in discrepancies
            )
            self._assert_existing_discrepancies(persisted_id, expected)
            return ReconciliationPersistenceResult(
                reconciliation_run_id=persisted_id,
                created=False,
                discrepancy_count=len(expected),
            )

        child_values = tuple(
            self._discrepancy_values(item, persisted_run_id=inserted) for item in discrepancies
        )
        self._session.add_all(ReconciliationDiscrepancyModel(**child) for child in child_values)
        self._session.flush()
        return ReconciliationPersistenceResult(
            reconciliation_run_id=inserted,
            created=True,
            discrepancy_count=len(child_values),
        )
