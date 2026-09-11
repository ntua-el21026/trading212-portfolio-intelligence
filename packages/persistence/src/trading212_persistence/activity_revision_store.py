"""Register and apply explicit revision evidence to real immutable broker records."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics._historical_core import _attested_revision_edges, event_revision_key
from trading212_application import activity_revisions as app
from trading212_domain import historical as d
from trading212_domain.alert_serialization import alert_record_digest
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Principal, Scope

from .activity_revision_models import ActivityRevisionEvidenceModel
from .historical_normalization import normalize_record
from .models import AuditEventModel, SourceRecordModel
from .planning_inputs import digest
from .report_authorization import authorize_report_request
from .source_models import MarketDataInstrumentModel

MAX_REVISION_EDGES = 10000
_SCOPES = frozenset(
    {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.ACTIVITY_READ, Scope.TARGETS_WRITE}
)


def _error(code: app.ActivityRevisionErrorCode) -> app.ActivityRevisionError:
    return app.ActivityRevisionError(code)


def revision_view(row: ActivityRevisionEvidenceModel) -> app.ActivityRevisionEvidence:
    return app.ActivityRevisionEvidence(
        registration=app.ActivityRevisionRegistration(
            id=row.id,
            new_source_record_id=row.new_source_record_id,
            superseded_source_record_id=row.superseded_source_record_id,
            authority=app.ActivityRevisionAuthority(row.authority),
            evidence_key=row.evidence_key,
        ),
        owner_id=row.owner_id,
        account_id=row.broker_account_id,
        principal_id=row.principal_id,
        economic_key=row.economic_key,
        first_observed_at=row.first_observed_at,
        content_digest=row.content_digest,
    )


def revision_digest(value: app.ActivityRevisionEvidence) -> str:
    return digest(
        (
            value.registration,
            value.owner_id,
            value.account_id,
            value.principal_id,
            value.economic_key,
            value.first_observed_at,
        )
    )


def apply_revision_evidence(
    events: tuple[d.HistoricalEvent, ...],
    evidence: tuple[app.ActivityRevisionEvidence, ...],
    *,
    cutoff: datetime,
) -> tuple[d.HistoricalEvent, ...]:
    """Validate known evidence while retaining raw facts; selectors apply edges at their cutoff."""
    cutoff = require_utc(cutoff)
    if len(events) > MAX_REVISION_EDGES or len(evidence) > MAX_REVISION_EDGES:
        raise _error(app.ActivityRevisionErrorCode.INPUT_BOUND_EXCEEDED)
    proofs = {
        str(item.registration.new_source_record_id): item
        for item in evidence
        if item.first_observed_at <= cutoff
    }
    if len(proofs) != sum(item.first_observed_at <= cutoff for item in evidence):
        raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
    by_source = {event.identity.source_record_id: event for event in events}
    for source_id, proof in proofs.items():
        event = by_source.get(source_id)
        if (
            event is None
            or revision_digest(proof) != proof.content_digest
            or event_revision_key(event) != proof.economic_key
        ):
            raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
    try:
        _attested_revision_edges(events, activity_revision_sources(tuple(proofs.values())))
    except DomainError as exc:
        code = (
            app.ActivityRevisionErrorCode.INPUT_BOUND_EXCEEDED
            if exc.code is ErrorCode.INPUT_BOUND_EXCEEDED
            else app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT
        )
        raise _error(code) from exc
    return events


def activity_revision_sources(
    evidence: tuple[app.ActivityRevisionEvidence, ...],
) -> tuple[d.HistoricalSourceReference, ...]:
    """Typed temporal edges from already digest-validated, owner-scoped evidence."""
    return tuple(
        d.HistoricalSourceReference(
            kind="activity_revision_evidence",
            id=str(proof.registration.id),
            effective_at=proof.first_observed_at,
            first_observed_at=proof.first_observed_at,
            semantic_digest=proof.content_digest,
            parent_ids=(
                str(proof.registration.new_source_record_id),
                str(proof.registration.superseded_source_record_id),
            ),
        )
        for proof in evidence
    )


def capture_activity_revisions(
    session: Session,
    *,
    owner_id: UUID,
    account_id: UUID,
    events: tuple[d.HistoricalEvent, ...],
    cutoff: datetime,
) -> tuple[tuple[d.HistoricalEvent, ...], tuple[app.ActivityRevisionEvidence, ...]]:
    rows = list(
        session.scalars(
            select(ActivityRevisionEvidenceModel)
            .where(
                ActivityRevisionEvidenceModel.owner_id == owner_id,
                ActivityRevisionEvidenceModel.broker_account_id == account_id,
                ActivityRevisionEvidenceModel.new_source_record_id.in_(
                    UUID(event.identity.source_record_id) for event in events
                ),
                ActivityRevisionEvidenceModel.first_observed_at <= cutoff,
                ActivityRevisionEvidenceModel.created_at <= cutoff,
            )
            .order_by(ActivityRevisionEvidenceModel.id)
            .limit(MAX_REVISION_EDGES + 1)
        )
    )
    if len(rows) > MAX_REVISION_EDGES:
        raise _error(app.ActivityRevisionErrorCode.INPUT_BOUND_EXCEEDED)
    proofs = tuple(revision_view(row) for row in rows)
    return apply_revision_evidence(events, proofs, cutoff=cutoff), proofs


class PostgresActivityRevisionStore:
    def __init__(
        self, sessions: sessionmaker[Session], *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))

    async def register_activity_revision(
        self,
        principal: Principal,
        account_id: UUID,
        registration: app.ActivityRevisionRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.ActivityRevisionEvidence:
        registration.__post_init__()
        if (
            not re.fullmatch(r"[A-Za-z0-9._:-]{1,180}", idempotency_key)
            or not 1 <= len(correlation_id) <= 100
        ):
            raise _error(app.ActivityRevisionErrorCode.VALIDATION_FAILED)
        request_digest = alert_record_digest(registration)

        def execute() -> app.ActivityRevisionEvidence:
            try:
                with self._sessions() as session, session.begin():
                    now = require_utc(self._clock())
                    authorization = authorize_report_request(
                        session, principal, account_id=account_id, required_scopes=_SCOPES, now=now
                    )
                    for namespace in ("sources", "historical"):
                        session.execute(
                            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                            {"key": f"{namespace}:{authorization.owner_id}"},
                        )
                    old = session.scalar(
                        select(ActivityRevisionEvidenceModel).where(
                            ActivityRevisionEvidenceModel.owner_id == authorization.owner_id,
                            ActivityRevisionEvidenceModel.idempotency_key == idempotency_key,
                        )
                    )
                    if old is not None:
                        if (
                            old.request_digest != request_digest
                            or old.broker_account_id != account_id
                        ):
                            raise _error(app.ActivityRevisionErrorCode.IDEMPOTENCY_KEY_REUSED)
                        authorization.check(session, now=require_utc(self._clock()))
                        return revision_view(old)
                    conflict = session.scalar(
                        select(ActivityRevisionEvidenceModel.id).where(
                            (ActivityRevisionEvidenceModel.id == registration.id)
                            | (
                                (ActivityRevisionEvidenceModel.owner_id == authorization.owner_id)
                                & (
                                    ActivityRevisionEvidenceModel.new_source_record_id
                                    == registration.new_source_record_id
                                )
                            )
                        )
                    )
                    if conflict is not None:
                        raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
                    records = []
                    for identifier in (
                        registration.new_source_record_id,
                        registration.superseded_source_record_id,
                    ):
                        row = session.get(SourceRecordModel, identifier)
                        if (
                            row is None
                            or row.broker_account_id != account_id
                            or max(row.observed_at, row.created_at) > now
                        ):
                            raise _error(app.ActivityRevisionErrorCode.NOT_FOUND)
                        records.append(row)
                    mappings: tuple[MarketDataInstrumentModel, ...] = ()
                    if any(record.capability == "historical_orders" for record in records):
                        mappings = tuple(
                            session.scalars(
                                select(MarketDataInstrumentModel)
                                .where(
                                    MarketDataInstrumentModel.owner_id == authorization.owner_id,
                                    MarketDataInstrumentModel.created_at <= now,
                                    MarketDataInstrumentModel.valid_from <= now,
                                )
                                .order_by(MarketDataInstrumentModel.id)
                                .limit(8193)
                            )
                        )
                        if len(mappings) > 8192:
                            raise _error(app.ActivityRevisionErrorCode.INPUT_BOUND_EXCEEDED)
                    normalized = tuple(
                        normalize_record(record, None, mappings) for record in records
                    )
                    # An unmatched execution has a different canonical event identity.
                    # Never seal a proof that normal mapped capture cannot apply.
                    if any(
                        record.capability == "historical_orders"
                        and not isinstance(event, d.HistoricalExecution)
                        for record, event in zip(records, normalized, strict=True)
                    ):
                        raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
                    new, previous = normalized
                    if (
                        new is None
                        or previous is None
                        or type(new) is not type(previous)
                        or event_revision_key(new) != event_revision_key(previous)
                    ):
                        raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
                    ancestor = registration.superseded_source_record_id
                    seen = {registration.new_source_record_id}
                    for _ in range(MAX_REVISION_EDGES):
                        if ancestor in seen:
                            raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
                        seen.add(ancestor)
                        edge = session.scalar(
                            select(ActivityRevisionEvidenceModel).where(
                                ActivityRevisionEvidenceModel.owner_id == authorization.owner_id,
                                ActivityRevisionEvidenceModel.new_source_record_id == ancestor,
                            )
                        )
                        if edge is None:
                            break
                        if (
                            edge.broker_account_id != account_id
                            or edge.economic_key != event_revision_key(new)
                        ):
                            raise _error(app.ActivityRevisionErrorCode.SOURCE_REVISION_CONFLICT)
                        ancestor = edge.superseded_source_record_id
                    else:
                        raise _error(app.ActivityRevisionErrorCode.INPUT_BOUND_EXCEEDED)
                    observed = require_utc(self._clock())
                    economic = event_revision_key(new)
                    content = digest(
                        (
                            registration,
                            authorization.owner_id,
                            account_id,
                            authorization.principal_id,
                            economic,
                            observed,
                        )
                    )
                    evidence_row = ActivityRevisionEvidenceModel(
                        id=registration.id,
                        owner_id=authorization.owner_id,
                        broker_account_id=account_id,
                        principal_id=authorization.principal_id,
                        new_source_record_id=registration.new_source_record_id,
                        superseded_source_record_id=registration.superseded_source_record_id,
                        authority=registration.authority.value,
                        evidence_key=registration.evidence_key,
                        economic_key=economic,
                        first_observed_at=observed,
                        created_at=observed,
                        content_digest=content,
                        request_digest=request_digest,
                        idempotency_key=idempotency_key,
                    )
                    authorization.check(session, now=observed)
                    session.add(evidence_row)
                    session.flush()
                    session.add(
                        AuditEventModel(
                            owner_id=authorization.owner_id,
                            principal_id=authorization.principal_id,
                            broker_account_id=account_id,
                            action="activity.revision.registered",
                            resource_type="activity_revision_evidence",
                            resource_id=str(evidence_row.id),
                            outcome="success",
                            occurred_at=observed,
                            correlation_id=correlation_id,
                            safe_metadata={
                                "new_source_record_id": str(registration.new_source_record_id),
                                "superseded_source_record_id": str(
                                    registration.superseded_source_record_id
                                ),
                                "authority": registration.authority.value,
                            },
                        )
                    )
                    authorization.check(session, now=require_utc(self._clock()))
                    return revision_view(evidence_row)
            except AuthorizationError:
                code = app.ActivityRevisionErrorCode.ACCESS_DENIED
            except DomainError:
                code = app.ActivityRevisionErrorCode.VALIDATION_FAILED
            except SQLAlchemyError:
                code = app.ActivityRevisionErrorCode.REVISION_UNAVAILABLE
            raise _error(code)

        return await asyncio.to_thread(execute)
