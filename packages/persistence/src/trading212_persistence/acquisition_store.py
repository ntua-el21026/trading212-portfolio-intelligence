"""Short durable transactions surrounding provider I/O; no network or sleeping."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.research import ResearchServiceError
from trading212_application.sources import SourceServiceError
from trading212_domain import require_utc
from trading212_domain.errors import DomainError
from trading212_security.principals import AuthorizationError, Principal

from .acquisition_authority import acquisition_auth, resolve_acquisition
from .acquisition_models import (
    ProviderAcquisitionAttemptModel as Attempt,
)
from .acquisition_models import (
    ProviderAcquisitionDayModel as Day,
)
from .acquisition_models import (
    ProviderAcquisitionRequestModel as Request,
)
from .acquisition_models import (
    ProviderAcquisitionSlotModel as Slot,
)
from .acquisition_records import (
    AcquisitionAttemptReceipt,
    AcquisitionAuthorityBasis,
    AcquisitionCapability,
    AcquisitionOutcome,
    AcquisitionSelection,
    AcquisitionStorageDenied,
    require_digest,
    retry_due,
)


def acquisition_lock(session: Session, owner: UUID, provider: UUID | None = None) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": f"sources:{owner}"}
    )
    if provider is not None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"acquisition:{owner}:{provider}"},
        )


def attempt_receipt(row: Attempt) -> AcquisitionAttemptReceipt:
    return AcquisitionAttemptReceipt(
        id=row.id,
        request_id=row.request_id,
        owner_id=row.owner_id,
        provider_id=row.provider_id,
        request_digest=row.request_digest,
        ordinal=row.ordinal,
        first_started_at=row.first_started_at,
        reserved_at=row.reserved_at,
        deadline=row.deadline,
        lease_expires_at=row.lease_expires_at,
    )


class PostgresAcquisitionStore:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        principal: Principal,
        enabled: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(enabled) is not bool:
            raise AcquisitionStorageDenied()
        self._sessions, self._principal, self._enabled = sessions, principal, enabled
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _execute[T](self, operation: Callable[[Session], T]) -> T:
        def run() -> T:
            try:
                with self._sessions() as session, session.begin():
                    return operation(session)
            except (
                SQLAlchemyError,
                AuthorizationError,
                ValueError,
                DomainError,
                ResearchServiceError,
                SourceServiceError,
            ):
                raise AcquisitionStorageDenied() from None

        return await asyncio.to_thread(run)

    async def resolve(self, selection: AcquisitionSelection) -> AcquisitionAuthorityBasis | None:
        if not self._enabled:
            return None

        def operation(session: Session) -> AcquisitionAuthorityBasis:
            acquisition_lock(session, selection.owner_id)
            return resolve_acquisition(session, self._principal, selection, now=self._now())[1]

        try:
            return await self._execute(operation)
        except AcquisitionStorageDenied:
            return None

    async def recheck(
        self, selection: AcquisitionSelection, basis: AcquisitionAuthorityBasis
    ) -> bool:
        if not self._enabled:
            return False

        def operation(session: Session) -> bool:
            acquisition_lock(session, selection.owner_id)
            resolve_acquisition(session, self._principal, selection, now=self._now(), pinned=basis)
            return True

        try:
            return await self._execute(operation)
        except AcquisitionStorageDenied:
            return False

    @staticmethod
    def _expire_slot(session: Session, slot: Slot, *, now: datetime) -> None:
        if slot.attempt_id is None:
            return
        old = session.scalar(
            select(Attempt)
            .where(Attempt.owner_id == slot.owner_id, Attempt.id == slot.attempt_id)
            .with_for_update()
        )
        if old is None or old.provider_id != slot.provider_id:
            raise AcquisitionStorageDenied()
        if old.finished_at is not None or old.lease_expires_at > now:
            raise AcquisitionStorageDenied()
        request = session.scalar(
            select(Request)
            .where(Request.owner_id == old.owner_id, Request.id == old.request_id)
            .with_for_update()
        )
        if request is None:
            raise AcquisitionStorageDenied()
        # A crashed attempt may already have dispatched. It is never refunded/reissued.
        old.finished_at = now
        old.outcome = AcquisitionOutcome.ATTEMPT_FENCE_LOST.value
        old.retry_at = None
        session.flush()
        request.state = "failed"
        request.retry_at = None
        slot.attempt_id = None
        session.flush()

    async def reserve(
        self,
        selection: AcquisitionSelection,
        basis: AcquisitionAuthorityBasis,
        *,
        request_digest: str,
    ) -> AcquisitionAttemptReceipt | None:
        if not self._enabled:
            return None
        require_digest(request_digest)

        def operation(session: Session) -> AcquisitionAttemptReceipt | None:
            acquisition_lock(session, selection.owner_id, basis.provider_id)
            now = self._now()
            auth, current = resolve_acquisition(
                session, self._principal, selection, now=now, pinned=basis
            )
            slot = session.scalar(
                select(Slot)
                .where(Slot.owner_id == auth.owner_id, Slot.provider_id == current.provider_id)
                .with_for_update()
            )
            if slot is None:
                slot = Slot(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    provider_id=current.provider_id,
                    attempt_id=None,
                    created_at=now,
                )
                session.add(slot)
                session.flush()
            if slot.attempt_id is not None:
                active = session.scalar(
                    select(Attempt).where(
                        Attempt.id == slot.attempt_id, Attempt.owner_id == auth.owner_id
                    )
                )
                if active is None:
                    raise AcquisitionStorageDenied()
                if active.lease_expires_at > now:
                    return None
                self._expire_slot(session, slot, now=now)
            request = session.scalar(
                select(Request).where(Request.id == selection.request_id).with_for_update()
            )
            if request is not None:
                if (
                    request.owner_id,
                    request.account_id,
                    request.principal_id,
                    request.provider_id,
                    request.capability,
                    request.mapping_version_id,
                    request.mapping_digest,
                    request.policy_version_id,
                    request.policy_digest,
                    request.grant_id,
                    request.grant_digest,
                    request.request_digest,
                ) != (
                    auth.owner_id,
                    auth.account_id,
                    auth.principal_id,
                    current.provider_id,
                    current.capability.value,
                    current.mapping_version_id,
                    current.mapping_digest,
                    current.policy_version_id,
                    current.policy_digest,
                    current.grant_id,
                    current.grant_digest,
                    request_digest,
                ):
                    raise AcquisitionStorageDenied()
                if (
                    request.state != "retry"
                    or request.retry_at is None
                    or request.retry_at > now
                    or request.attempt_count >= 3
                    or request.deadline <= now
                ):
                    return None
            day = session.scalar(
                select(Day)
                .where(
                    Day.owner_id == auth.owner_id,
                    Day.provider_id == current.provider_id,
                    Day.utc_day == now.date(),
                )
                .with_for_update()
            )
            if day is None:
                day = Day(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    provider_id=current.provider_id,
                    utc_day=now.date(),
                    charged_attempts=0,
                    created_at=now,
                )
                session.add(day)
                session.flush()
            if day.charged_attempts >= current.daily_allowance:
                return None
            if request is None:
                request = Request(
                    id=selection.request_id,
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    principal_id=auth.principal_id,
                    provider_id=current.provider_id,
                    capability=current.capability.value,
                    mapping_version_id=current.mapping_version_id,
                    mapping_digest=current.mapping_digest,
                    policy_version_id=current.policy_version_id,
                    policy_digest=current.policy_digest,
                    grant_id=current.grant_id,
                    grant_digest=current.grant_digest,
                    request_digest=request_digest,
                    first_started_at=now,
                    deadline=min(now + timedelta(seconds=20), current.expires_at),
                    attempt_count=1,
                    state="inflight",
                    retry_at=None,
                    created_at=now,
                )
                session.add(request)
            else:
                request.attempt_count += 1
                request.state = "inflight"
                request.retry_at = None
            day.charged_attempts += 1
            session.flush()
            attempt = Attempt(
                id=uuid4(),
                owner_id=auth.owner_id,
                request_id=request.id,
                provider_id=current.provider_id,
                day_id=day.id,
                request_digest=request_digest,
                ordinal=request.attempt_count,
                first_started_at=request.first_started_at,
                reserved_at=now,
                deadline=request.deadline,
                lease_expires_at=request.deadline,
                finished_at=None,
                outcome=None,
                retry_at=None,
                created_at=now,
            )
            session.add(attempt)
            session.flush()
            slot.attempt_id = attempt.id
            session.flush()
            return attempt_receipt(attempt)

        try:
            return await self._execute(operation)
        except AcquisitionStorageDenied:
            return None

    async def finish(
        self,
        receipt: AcquisitionAttemptReceipt,
        *,
        outcome: AcquisitionOutcome | None,
        observed_at: datetime,
        retry_at: datetime | None,
    ) -> bool:
        if (
            not self._enabled
            or type(receipt) is not AcquisitionAttemptReceipt
            or (outcome is not None and type(outcome) is not AcquisitionOutcome)
        ):
            return False
        try:
            observed = require_utc(observed_at)
            due = retry_due(
                outcome,
                receipt.ordinal,
                observed_at=observed,
                deadline=receipt.deadline,
                requested=retry_at,
            )
        except (DomainError, AcquisitionStorageDenied):
            return False

        def operation(session: Session) -> bool:
            acquisition_lock(session, receipt.owner_id, receipt.provider_id)
            now = self._now()
            row = session.scalar(
                select(Attempt)
                .where(Attempt.owner_id == receipt.owner_id, Attempt.id == receipt.id)
                .with_for_update()
            )
            if row is None or attempt_receipt(row) != receipt:
                return False
            request = session.scalar(
                select(Request)
                .where(Request.owner_id == receipt.owner_id, Request.id == receipt.request_id)
                .with_for_update()
            )
            if request is None:
                return False
            selection = AcquisitionSelection(
                owner_id=request.owner_id,
                account_id=request.account_id,
                request_id=request.id,
                mapping_version_id=request.mapping_version_id,
                capability=AcquisitionCapability(request.capability),
            )
            auth = acquisition_auth(session, self._principal, selection, now=now)
            if auth.principal_id != request.principal_id:
                return False
            code = None if outcome is None else outcome.value
            if row.finished_at is not None:
                return (row.finished_at, row.outcome, row.retry_at) == (observed, code, due)
            slot = session.scalar(
                select(Slot)
                .where(Slot.owner_id == receipt.owner_id, Slot.provider_id == receipt.provider_id)
                .with_for_update()
            )
            if (
                slot is None
                or slot.attempt_id != row.id
                or request.state != "inflight"
                or request.attempt_count != row.ordinal
                or observed < row.reserved_at
                or observed > now
            ):
                return False
            if now >= row.lease_expires_at or observed >= row.deadline:
                self._expire_slot(session, slot, now=now)
                return False
            # Entitlement is rechecked for success and retry. Failed metadata is safe
            # to finish without acquiring new rights, but never authorizes publication.
            if outcome is None or due is not None:
                _, basis = resolve_acquisition(session, self._principal, selection, now=now)
                if (
                    basis.policy_version_id,
                    basis.policy_digest,
                    basis.grant_id,
                    basis.grant_digest,
                ) != (
                    request.policy_version_id,
                    request.policy_digest,
                    request.grant_id,
                    request.grant_digest,
                ):
                    return False
            row.finished_at = observed
            row.outcome = code
            row.retry_at = due
            session.flush()
            request.state = (
                "succeeded" if outcome is None else ("retry" if due is not None else "failed")
            )
            request.retry_at = due
            slot.attempt_id = None
            session.flush()
            return True

        try:
            return await self._execute(operation)
        except AcquisitionStorageDenied:
            return False
