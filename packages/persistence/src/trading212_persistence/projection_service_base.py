"""Projection transaction, durable authority and stable metadata collection boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as history_app
from trading212_application import projection as app
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_application.projection_calendar import ProjectionCalendarError
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
)
from trading212_application.targets import TargetServiceError
from trading212_domain.errors import DomainError, ErrorCode
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotScopeError,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .premium_models import PremiumOwned
from .projection_capture_codec import ProjectionCodecError
from .projection_definition_store import READ_SCOPES, ProjectionStorageError, projection_owner_lock
from .projection_result_store import ProjectionResultStore
from .report_authorization import ReportAuthorization, authorize_report_request


def projection_error(code: app.ProjectionErrorCode) -> app.ProjectionServiceError:
    return app.ProjectionServiceError(code)


class ProjectionServiceBase(ProjectionResultStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
        )
        self._cursors = CursorCodec(cursor_signing_key, clock=self._clock)

    async def _execute[T](
        self,
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ReportAuthorization], T],
        *,
        write: Literal["assumption", "goal", "run"] | None = None,
        resource: tuple[type[PremiumOwned], UUID] | None = None,
        expected_account_id: UUID | None = None,
    ) -> T:
        scopes = READ_SCOPES
        if write == "goal":
            scopes = scopes | {Scope.GOALS_WRITE}
        elif write in ("assumption", "run"):
            scopes = scopes | {Scope.PROJECTIONS_WRITE}
        elif write is not None:
            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)
        if expected_account_id is not None and type(expected_account_id) is not UUID:
            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)
        try:
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._now())
            owner = UUID(principal.owner_id)
        except (AuthorizationError, ValueError):
            raise projection_error(app.ProjectionErrorCode.ACCESS_DENIED) from None

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    account = account_id
                    if resource is not None:
                        model, identifier = resource
                        if type(identifier) is not UUID:
                            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)
                        # Only owned account metadata is read before durable account authority.
                        account = session.scalar(
                            select(model.account_id).where(
                                model.owner_id == owner, model.id == identifier
                            )
                        )
                        if account is None:
                            raise projection_error(app.ProjectionErrorCode.NOT_FOUND)
                    if type(account) is not UUID:
                        raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)
                    if expected_account_id is not None and account != expected_account_id:
                        raise projection_error(app.ProjectionErrorCode.NOT_FOUND)
                    auth = authorize_report_request(
                        session,
                        principal,
                        account_id=account,
                        required_scopes=scopes,
                        now=self._now(),
                    )
                    projection_owner_lock(session, owner)
                    auth.check(session, now=self._now())
                    result = operation(session, auth)
                    auth.check(session, now=self._now())
                    return result
            except AuthorizationError:
                rejection = app.ProjectionErrorCode.ACCESS_DENIED
            except ProjectionStorageError as error:
                rejection = app.ProjectionErrorCode(error.code.value)
            except ProjectionCodecError as error:
                rejection = app.ProjectionErrorCode(error.code.value)
            except ProjectionCalendarError as error:
                rejection = app.ProjectionErrorCode(error.code.value)
            except CollectionSnapshotCapacityError:
                rejection = app.ProjectionErrorCode.RATE_LIMITED
            except CursorValidationError:
                rejection = app.ProjectionErrorCode.CURSOR_INVALID
            except CollectionSnapshotScopeError:
                rejection = app.ProjectionErrorCode.NOT_FOUND
            except (
                source_app.SourceServiceError,
                xray_app.XrayServiceError,
                history_app.HistoricalServiceError,
            ):
                rejection = app.ProjectionErrorCode.SOURCE_UNAVAILABLE
            except TargetServiceError:
                rejection = app.ProjectionErrorCode.VALIDATION_FAILED
            except DomainError as error:
                rejection = (
                    app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED
                    if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.ProjectionErrorCode.VALIDATION_FAILED
                )
            except IntegrityError:
                rejection = app.ProjectionErrorCode.CONFLICT
            except SQLAlchemyError:
                rejection = app.ProjectionErrorCode.PROJECTION_UNAVAILABLE
            # Raise outside the handler: no raw SQL/provider exception is chained or exposed.
            raise projection_error(rejection)

        return await asyncio.to_thread(execute)

    def _page(
        self,
        session: Session,
        auth: ReportAuthorization,
        resource: CollectionSnapshotResource,
        query: app.ProjectionPageQuery,
        statement: Select[tuple[UUID]],
        *filters: object,
    ) -> CollectionSnapshotPage:
        if type(query) is not app.ProjectionPageQuery:
            raise projection_error(app.ProjectionErrorCode.VALIDATION_FAILED)
        auth.check(session, now=self._now())
        definition = CollectionSnapshotDefinition(
            resource=resource,
            owner_id=auth.owner_id,
            broker_account_id=auth.account_id,
            # A refreshed token retains its stable identity; a different principal cannot resume.
            filter_fingerprint=collection_filter_fingerprint(
                "projection.metadata.v1",
                auth.issuer,
                auth.subject,
                auth.account_id,
                query.limit,
                *filters,
            ),
        )
        store = CollectionSnapshotStore(session, self._cursors)
        if query.cursor is not None:
            return store.resume(definition, query.cursor, limit=query.limit)
        return store.materialize(
            definition, lambda: session.scalars(statement.limit(250001)), limit=query.limit
        )
