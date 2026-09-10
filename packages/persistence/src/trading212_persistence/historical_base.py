"""Transactional ownership, legal dependencies and fixed historical registration commands."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as app
from trading212_application import sources as source_app
from trading212_application.queries import CursorCodec
from trading212_application.targets import validate_target_idempotency_key
from trading212_domain import historical as domain
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceUse
from trading212_domain.values import require_utc
from trading212_security.principals import Authorizer, Principal, Scope

from . import historical_models as hm
from . import models as legacy
from . import source_models as sm
from .source_service import PostgresSourceService
from .target_models import TargetVersionModel


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def encoded(value: object) -> bytes:
    result = canonical_json(value).encode()
    if len(result) > domain.MAX_HISTORICAL_DOCUMENT_BYTES:
        raise error("RESULT_TOO_LARGE")
    return result


def error(code: str) -> app.HistoricalServiceError:
    return app.HistoricalServiceError(
        app.HistoricalServiceErrorCode[code], "The historical request cannot be completed."
    )


# Closed relation registry: public callers never choose a table or SQL identifier.
REFERENCE_MODELS = {
    "ingestion_run": (legacy.IngestionRunModel, "ingestion_run_id"),
    "broker_source_record": (legacy.SourceRecordModel, "source_record_id"),
    "broker_source_occurrence": (legacy.SourceRecordOccurrenceModel, "source_occurrence_id"),
    "portfolio_snapshot": (legacy.PortfolioSnapshotModel, "portfolio_snapshot_id"),
    "calculation_run": (legacy.CalculationRunModel, "calculation_run_id"),
    "reconciliation_run": (legacy.ReconciliationRunModel, "reconciliation_run_id"),
    "price_snapshot": (sm.PriceSnapshotModel, "price_snapshot_id"),
    "fx_snapshot": (sm.FxSnapshotModel, "fx_snapshot_id"),
    "corporate_action_snapshot": (sm.CorporateActionSnapshotModel, "action_snapshot_id"),
    "provider_benchmark_snapshot": (sm.BenchmarkSnapshotModel, "benchmark_snapshot_id"),
    "instrument_mapping": (sm.MarketDataInstrumentModel, "mapping_id"),
    "calendar_version": (sm.SourceCalendarModel, "calendar_id"),
    "provider_license_version": (sm.ProviderLicenseVersionModel, "license_version_id"),
    "benchmark_version": (sm.BenchmarkVersionModel, "benchmark_version_id"),
    "target_version": (TargetVersionModel, "target_version_id"),
    "classification_evidence": (hm.HistoricalClassificationModel, "classification_id"),
    "historical_evidence": (hm.HistoricalEvidenceModel, "registered_evidence_id"),
}


class HistoricalStoreBase:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
        required_copy_use: SourceUse | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._authorizer = Authorizer()
        self._cursors = CursorCodec(
            cursor_signing_key, clock=self._clock, ttl_seconds=cursor_ttl_seconds
        )
        self._ttl = cursor_ttl_seconds
        self._snapshot_quota = max_active_collection_snapshots_per_owner
        self._member_quota = max_active_collection_members_per_owner
        self._sources = PostgresSourceService(
            sessions=sessions,
            cursor_signing_key=cursor_signing_key,
            clock=self._clock,
            required_copy_use=required_copy_use,
        )

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _run[T](
        self,
        principal: Principal,
        account_id: str | None,
        operation: Callable[[Session, UUID, UUID | None], T],
        *,
        write: bool = False,
        activity: bool = False,
    ) -> T:
        for scope in (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ):
            self._authorizer.require_scope(principal, scope, now=self._now())
        if write:
            self._authorizer.require_scope(principal, Scope.TARGETS_WRITE, now=self._now())
        if activity:
            self._authorizer.require_scope(principal, Scope.ACTIVITY_READ, now=self._now())
        owner = UUID(principal.owner_id)

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    # Source/evidence publication cannot race historical legal checks.
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"sources:{owner}"},
                    )
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"historical:{owner}"},
                    )
                    account = (
                        None if account_id is None else self._account(session, owner, account_id)
                    )
                    return operation(session, owner, account)
            except DomainError as failure:
                rejection = (
                    "RESULT_TOO_LARGE"
                    if failure.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else "VALIDATION_FAILED"
                )
            except IntegrityError:
                rejection = "VALIDATION_FAILED"
            except source_app.SourceServiceError:
                rejection = "ACCESS_DENIED"
            except SQLAlchemyError:
                rejection = "HISTORICAL_UNAVAILABLE"
            # Do not propagate SQL/parameters or chained exception context.
            raise error(rejection)

        return await asyncio.to_thread(execute)

    def _account(self, session: Session, owner: UUID, identifier: str | UUID) -> UUID:
        account = UUID(str(identifier))
        actual = session.scalar(
            select(legacy.BrokerConnectionModel.owner_id)
            .join(legacy.BrokerAccountModel)
            .where(legacy.BrokerAccountModel.id == account)
        )
        if actual != owner:
            raise error("NOT_FOUND")
        return account

    def _owned[T: hm.HistoricalOwned](
        self, session: Session, owner: UUID, model: type[T], identifier: str | UUID
    ) -> T:
        row = session.scalar(
            select(model).where(model.owner_id == owner, model.id == UUID(str(identifier)))
        )
        if row is None:
            raise error("NOT_FOUND")
        return row

    def _reference(
        self, session: Session, owner: UUID, account: UUID, kind: str, identifier: str | UUID
    ) -> domain.HistoricalSourceReference:
        from typing import Any, cast

        model, _ = REFERENCE_MODELS[kind]
        row = session.get(model, UUID(str(identifier)))
        if row is None:
            raise error("NOT_FOUND")
        record = cast(Any, row)
        if hasattr(record, "owner_id") and record.owner_id != owner:
            raise error("NOT_FOUND")
        if hasattr(record, "broker_account_id") and record.broker_account_id != account:
            raise error("NOT_FOUND")
        parent_ids: tuple[str, ...] = ()
        first = getattr(record, "created_at", self._now())
        effective = first
        semantic = getattr(record, "content_digest", None)
        original = None
        derived = None
        if isinstance(row, legacy.IngestionRunModel):
            if row.completed_at is None or row.status != "succeeded":
                raise error("VALIDATION_FAILED")
            first = effective = row.completed_at
            semantic = row.request_fingerprint
        elif isinstance(row, legacy.SourceRecordModel):
            first = row.observed_at
            effective = row.source_updated_at or row.observed_at
            original = row.payload_fingerprint
        elif isinstance(row, legacy.SourceRecordOccurrenceModel):
            parent = session.get(legacy.SourceRecordModel, row.source_record_id)
            if parent is None or parent.broker_account_id != account:
                raise error("NOT_FOUND")
            first = effective = row.observed_at
            parent_ids = (str(row.source_record_id),)
        elif isinstance(row, legacy.PortfolioSnapshotModel):
            effective = row.valuation_at
            parent_ids = (str(row.calculation_run_id),)
        elif isinstance(row, sm.SourceSnapshotFields):
            self._sources._snapshot_permit(session, row)
            first = row.first_observed_at
            effective = row.effective_at
            parent_ids = (str(row.license_version_id),)
        elif isinstance(row, sm.ProviderLicenseVersionModel):
            self._sources._permit(session, owner, row.id, SourceUse.DISPLAY)
            effective = row.effective_at
        elif isinstance(row, sm.MarketDataInstrumentModel):
            effective = row.valid_from
        elif isinstance(row, sm.BenchmarkVersionModel):
            effective = row.effective_at
            first = row.published_at
        elif isinstance(row, TargetVersionModel):
            if row.published_at is None:
                raise error("VALIDATION_FAILED")
            effective = row.effective_at
            first = row.published_at
        elif isinstance(row, hm.HistoricalClassificationModel):
            first = row.first_observed_at
            effective = row.valid_from
            self._sources._permit(session, owner, row.license_version_id, SourceUse.DISPLAY)
        elif isinstance(row, hm.HistoricalEvidenceModel):
            first = effective = row.first_observed_at
        return domain.HistoricalSourceReference(
            kind=cast(Any, kind),
            id=str(identifier),
            effective_at=effective,
            first_observed_at=first,
            semantic_digest=semantic,
            original_fingerprint=original,
            derived_projection_digest=derived,
            parent_ids=parent_ids,
        )

    def _find_reference(
        self, session: Session, owner: UUID, account: UUID, identifier: str
    ) -> domain.HistoricalSourceReference:
        for kind, (model, _) in REFERENCE_MODELS.items():
            if session.get(model, UUID(identifier)) is not None:
                return self._reference(session, owner, account, kind, identifier)
        raise error("NOT_FOUND")

    def _dependency(
        self,
        session: Session,
        owner: UUID,
        reference: domain.HistoricalSourceReference,
        *,
        input_id: UUID | None = None,
        evidence_id: UUID | None = None,
    ) -> hm.HistoricalDependencyModel:
        _, column = REFERENCE_MODELS[reference.kind]
        row = hm.HistoricalDependencyModel(
            id=uuid4(),
            owner_id=owner,
            input_id=input_id,
            evidence_id=evidence_id,
            reference_key=f"{reference.kind}:{reference.id}",
            **{column: UUID(reference.id)},
        )
        session.add(row)
        return row

    def _reauthorize(
        self,
        session: Session,
        owner: UUID,
        account: UUID,
        *,
        input_id: UUID | None = None,
        evidence_id: UUID | None = None,
    ) -> None:
        rows = session.scalars(
            select(hm.HistoricalDependencyModel)
            .where(
                hm.HistoricalDependencyModel.owner_id == owner,
                hm.HistoricalDependencyModel.input_id == input_id
                if input_id is not None
                else hm.HistoricalDependencyModel.evidence_id == evidence_id,
            )
            .limit(domain.MAX_HISTORICAL_SOURCES + 1)
        ).all()
        if len(rows) > domain.MAX_HISTORICAL_SOURCES:
            raise error("RESULT_TOO_LARGE")
        for row in rows:
            kind, identifier = row.reference_key.split(":", 1)
            self._reference(session, owner, account, kind, identifier)
            if row.registered_evidence_id is not None:
                self._reauthorize(session, owner, account, evidence_id=row.registered_evidence_id)

    def _command(
        self, session: Session, owner: UUID, account: UUID, kind: str, key: str, payload: object
    ) -> tuple[hm.HistoricalCommandModel | None, str]:
        validate_target_idempotency_key(key)
        signature = digest((account, kind, payload))
        old = session.scalar(
            select(hm.HistoricalCommandModel).where(
                hm.HistoricalCommandModel.owner_id == owner,
                hm.HistoricalCommandModel.idempotency_key == key,
            )
        )
        if old is not None and (
            old.request_digest != signature or old.kind != kind or old.broker_account_id != account
        ):
            raise error("IDEMPOTENCY_KEY_REUSED")
        return old, signature

    def _record_command(
        self,
        session: Session,
        principal: Principal,
        account: UUID,
        kind: str,
        key: str,
        signature: str,
        correlation_id: str,
        *,
        policy_id: UUID | None = None,
        evidence_id: UUID | None = None,
    ) -> None:
        row = hm.HistoricalCommandModel(
            id=uuid4(),
            owner_id=UUID(principal.owner_id),
            broker_account_id=account,
            kind=kind,
            idempotency_key=key,
            request_digest=signature,
            policy_id=policy_id,
            evidence_id=evidence_id,
            actor_principal_id=principal.principal_id,
            correlation_id=correlation_id,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        session.add(
            hm.HistoricalAuditEventModel(
                owner_id=UUID(principal.owner_id),
                command_id=row.id,
                kind="policy_registered" if policy_id is not None else "evidence_registered",
                actor_principal_id=principal.principal_id,
                correlation_id=correlation_id,
                created_at=self._now(),
            )
        )
