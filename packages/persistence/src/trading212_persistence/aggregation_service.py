"""Six bounded operations over saved aggregate identities and original source proof."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import TypeVar
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import aggregation as app
from trading212_application.aggregation_views import AggregateRunPage
from trading212_application.queries import CursorCodec, CursorValidationError
from trading212_application.views import Page
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal

from . import aggregation_models as m
from .aggregation_authorization import AggregateAuthorization, authorize_aggregate_members
from .aggregation_commands import create_run, create_selection, selection_view
from .aggregation_pages import get_run_page, list_runs, list_selections

_T = TypeVar("_T")


class AggregateDeadline:
    """One original monotonic ceiling, including database timeout setup and commit."""

    def __init__(self) -> None:
        self.expires = monotonic() + 20.0

    def check(self) -> None:
        if monotonic() >= self.expires:
            raise app.AggregateServiceError(app.AggregateErrorCode.DEADLINE_EXCEEDED)

    def configure(self, session: Session) -> None:
        # transaction_timeout starts with the transaction itself; use the remaining
        # original budget, never a new allowance per statement or retry.
        self.check()
        milliseconds = max(1, int((self.expires - monotonic()) * 1000))
        session.execute(
            text("SELECT set_config('transaction_timeout', :timeout, true)"),
            {"timeout": f"{milliseconds}ms"},
        )
        self.check()
        milliseconds = max(1, int((self.expires - monotonic()) * 1000))
        session.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{milliseconds}ms"},
        )
        self.check()


class PostgresAggregateService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursors = CursorCodec(cursor_signing_key, clock=self._clock)

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _execute(
        self,
        principal: Principal,
        operation: Callable[[Session, AggregateDeadline, UUID], _T],
        *,
        write: bool = False,
    ) -> _T:
        scopes = app.AGGREGATE_WRITE_SCOPES if write else app.AGGREGATE_READ_SCOPES
        try:
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._now())
            owner = UUID(principal.owner_id)
        except (AuthorizationError, ValueError):
            raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED) from None

        def execute() -> _T:
            deadline = AggregateDeadline()
            try:
                with self._sessions() as session:
                    try:
                        with session.begin():
                            deadline.configure(session)
                            result = operation(session, deadline, owner)
                            deadline.check()
                        return result
                    except DBAPIError as error:
                        # PG18 transaction_timeout may terminate the connection. Do
                        # not return it to the pool; replay remains a new authorized
                        # semantic command transaction, never a blind internal retry.
                        if error.connection_invalidated or monotonic() >= deadline.expires:
                            session.invalidate()
                        raise
            except app.AggregateServiceError:
                raise
            except AuthorizationError:
                code = app.AggregateErrorCode.ACCESS_DENIED
            except CursorValidationError:
                code = app.AggregateErrorCode.CURSOR_INVALID
            except DomainError as error:
                code = (
                    app.AggregateErrorCode.INPUT_BOUND_EXCEEDED
                    if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.AggregateErrorCode.VALIDATION_FAILED
                )
            except IntegrityError as error:
                detail = getattr(getattr(error.orig, "diag", None), "message_primary", "")
                code = (
                    app.AggregateErrorCode.INPUT_BOUND_EXCEEDED
                    if detail == "aggregate reserved capacity exhausted"
                    else app.AggregateErrorCode.RATE_LIMITED
                    if detail
                    in (
                        "aggregate owner capacity exceeded",
                        "aggregate owner active capacity exceeded",
                        "aggregate shared definition capacity exceeded",
                    )
                    else app.AggregateErrorCode.CONFLICT
                )
            except SQLAlchemyError as error:
                state = getattr(getattr(error, "orig", None), "sqlstate", None)
                code = (
                    app.AggregateErrorCode.DEADLINE_EXCEEDED
                    if state in ("57014", "25P04") or monotonic() >= deadline.expires
                    else app.AggregateErrorCode.RATE_LIMITED
                    if state == "55P03"
                    else app.AggregateErrorCode.SOURCE_UNAVAILABLE
                )
            raise app.AggregateServiceError(code)

        return await asyncio.to_thread(execute)

    def _selection_authority(
        self,
        session: Session,
        principal: Principal,
        owner: UUID,
        selection_id: UUID,
        *,
        write: bool = False,
        activity: bool = False,
    ) -> tuple[m.AggregateSelectionModel, AggregateAuthorization]:
        from trading212_security.principals import Scope

        selected = session.scalar(
            select(m.AggregateSelectionModel).where(
                m.AggregateSelectionModel.owner_id == owner,
                m.AggregateSelectionModel.id == selection_id,
            )
        )
        if selected is None or not selected.sealed:
            raise app.AggregateServiceError(app.AggregateErrorCode.NOT_FOUND)
        accounts = tuple(
            session.scalars(
                select(m.AggregateMemberModel.account_id)
                .where(
                    m.AggregateMemberModel.owner_id == owner,
                    m.AggregateMemberModel.selection_id == selection_id,
                )
                .order_by(m.AggregateMemberModel.ordinal)
            )
        )
        if len(accounts) != selected.member_count:
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        scopes = app.AGGREGATE_WRITE_SCOPES if write else app.AGGREGATE_READ_SCOPES
        if activity:
            scopes |= {Scope.ACTIVITY_READ}
        auth = authorize_aggregate_members(
            session, principal, accounts, now=self._now(), scopes=scopes
        )
        if write:
            # Metadata was located before the owner lock; a concurrent admitted
            # run may have advanced only the operational revision meanwhile.
            session.refresh(selected, with_for_update=True)
        return selected, auth

    async def create_selection(
        self, principal: Principal, command: app.CreateAggregateSelection
    ) -> app.AggregateSelectionView:
        def operation(
            session: Session, deadline: AggregateDeadline, owner: UUID
        ) -> app.AggregateSelectionView:
            auth = authorize_aggregate_members(
                session,
                principal,
                tuple(x.account_id for x in command.content.members),
                now=self._now(),
                scopes=app.AGGREGATE_WRITE_SCOPES,
            )
            result = create_selection(session, auth, command, clock=self._now, check=deadline.check)
            auth.finish(session, now=self._now())
            return result

        return await self._execute(principal, operation, write=True)

    async def get_selection(
        self, principal: Principal, selection_id: UUID
    ) -> app.AggregateSelectionView:
        def operation(
            session: Session, deadline: AggregateDeadline, owner: UUID
        ) -> app.AggregateSelectionView:
            selected, auth = self._selection_authority(session, principal, owner, selection_id)
            result = selection_view(session, auth, selected)
            auth.finish(session, now=self._now())
            deadline.check()
            return result

        return await self._execute(principal, operation)

    async def list_selections(
        self, principal: Principal, query: app.AggregatePageQuery
    ) -> Page[app.AggregateSelectionView]:
        return await self._execute(
            principal,
            lambda session, deadline, owner: list_selections(
                session,
                principal,
                owner,
                query,
                cursors=self._cursors,
                clock=self._now,
                check=deadline.check,
            ),
        )

    async def list_runs(
        self, principal: Principal, selection_id: UUID, query: app.AggregatePageQuery
    ) -> Page[app.AggregateRunReceipt]:
        def operation(
            session: Session, deadline: AggregateDeadline, owner: UUID
        ) -> Page[app.AggregateRunReceipt]:
            selected, auth = self._selection_authority(session, principal, owner, selection_id)
            result = list_runs(
                session, auth, selected, query, cursors=self._cursors, clock=self._now
            )
            auth.finish(session, now=self._now())
            deadline.check()
            return result

        return await self._execute(principal, operation)

    async def create_run(
        self, principal: Principal, command: app.CreateAggregateRun
    ) -> app.AggregateRunReceipt:
        def operation(
            session: Session, deadline: AggregateDeadline, owner: UUID
        ) -> app.AggregateRunReceipt:
            # The global lock always precedes owner locks. Premium workers use the
            # same key; synchronous aggregation cannot overlap a premium worker.
            admitted = session.scalar(
                text(
                    "SELECT "
                    "pg_try_advisory_xact_lock(hashtextextended('premium:single-execu"
                    "tion-slot',0)) AND NOT EXISTS(SELECT 1 FROM premium_jobs WHERE "
                    "state='running')"
                )
            )
            if admitted is not True:
                raise app.AggregateServiceError(app.AggregateErrorCode.RATE_LIMITED)
            selected, auth = self._selection_authority(
                session,
                principal,
                owner,
                command.selection_id,
                write=True,
                activity=command.activity_window is not None,
            )
            result = create_run(
                session, auth, selected, command, clock=self._now, check=deadline.check
            )
            auth.finish(session, now=self._now())
            return result

        return await self._execute(principal, operation, write=True)

    async def get_run(
        self, principal: Principal, run_id: UUID, query: app.AggregateRunQuery
    ) -> AggregateRunPage:
        def operation(
            session: Session, deadline: AggregateDeadline, owner: UUID
        ) -> AggregateRunPage:
            root = session.scalar(
                select(m.AggregateRunModel).where(
                    m.AggregateRunModel.owner_id == owner, m.AggregateRunModel.id == run_id
                )
            )
            if root is None or not root.sealed:
                raise app.AggregateServiceError(app.AggregateErrorCode.NOT_FOUND)
            selected, auth = self._selection_authority(
                session,
                principal,
                owner,
                root.selection_id,
                activity=query.view.value == "transfers",
            )
            result = get_run_page(
                session,
                auth,
                selected,
                root,
                query,
                cursors=self._cursors,
                clock=self._now,
                check=deadline.check,
            )
            auth.finish(session, now=self._now())
            return result

        return await self._execute(principal, operation)
