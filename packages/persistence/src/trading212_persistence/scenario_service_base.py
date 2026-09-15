"""Scenario transaction, durable authority and stable metadata collection boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as history_app
from trading212_application import scenario as app
from trading212_application import sources as source_app
from trading212_application import xray as xray_app
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
)
from trading212_application.targets import TargetServiceError
from trading212_domain.errors import DomainError, ErrorCode
from trading212_security.principals import AuthorizationError, Authorizer, Principal

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotScopeError,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .premium_models import PremiumCapacityModel, PremiumOwned
from .report_authorization import ReportAuthorization, authorize_report_request
from .scenario_definition_store import READ_SCOPES, WRITE_SCOPES, scenario_owner_lock
from .scenario_input_store import ScenarioReplayResolver
from .scenario_result_store import ScenarioResultStore
from .scenario_store_types import ScenarioStorageError


def scenario_error(code: app.ScenarioErrorCode) -> app.ScenarioServiceError:
    return app.ScenarioServiceError(code)


class ScenarioServiceBase(ScenarioResultStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        replay_resolver: ScenarioReplayResolver | None = None,
    ) -> None:
        super().__init__(
            sessions,
            cursor_signing_key=cursor_signing_key,
            clock=clock,
            replay_resolver=replay_resolver,
        )
        self._cursors = CursorCodec(cursor_signing_key, clock=self._clock)

    async def _execute[T](
        self,
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ReportAuthorization], T],
        *,
        write: bool = False,
        resource: tuple[type[PremiumOwned], UUID] | None = None,
    ) -> T:
        scopes = WRITE_SCOPES if write else READ_SCOPES
        try:
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._now())
            owner = UUID(principal.owner_id)
        except (AuthorizationError, ValueError):
            raise scenario_error(app.ScenarioErrorCode.ACCESS_DENIED) from None

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    account = account_id
                    if resource is not None:
                        model, identifier = resource
                        if type(identifier) is not UUID:
                            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)
                        # Only owned account metadata is read before durable account authority.
                        account = session.scalar(
                            select(model.account_id).where(
                                model.owner_id == owner, model.id == identifier
                            )
                        )
                        if account is None:
                            raise scenario_error(app.ScenarioErrorCode.NOT_FOUND)
                    if type(account) is not UUID:
                        raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)
                    auth = authorize_report_request(
                        session,
                        principal,
                        account_id=account,
                        required_scopes=scopes,
                        now=self._now(),
                    )
                    scenario_owner_lock(session, owner)
                    auth.check(session, now=self._now())
                    result = operation(session, auth)
                    auth.check(session, now=self._now())
                    return result
            except AuthorizationError:
                rejection = app.ScenarioErrorCode.ACCESS_DENIED
            except ScenarioStorageError as error:
                rejection = app.ScenarioErrorCode(error.code.value)
            except CollectionSnapshotCapacityError:
                rejection = app.ScenarioErrorCode.RATE_LIMITED
            except CursorValidationError:
                rejection = app.ScenarioErrorCode.CURSOR_INVALID
            except CollectionSnapshotScopeError:
                rejection = app.ScenarioErrorCode.NOT_FOUND
            except (
                source_app.SourceServiceError,
                xray_app.XrayServiceError,
                history_app.HistoricalServiceError,
            ):
                rejection = app.ScenarioErrorCode.SOURCE_UNAVAILABLE
            except TargetServiceError:
                rejection = app.ScenarioErrorCode.VALIDATION_FAILED
            except DomainError as error:
                rejection = (
                    app.ScenarioErrorCode.INPUT_BOUND_EXCEEDED
                    if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.ScenarioErrorCode.VALIDATION_FAILED
                )
            except IntegrityError:
                rejection = app.ScenarioErrorCode.CONFLICT
            except SQLAlchemyError:
                rejection = app.ScenarioErrorCode.SCENARIO_UNAVAILABLE
            # Raise outside the handler: no raw SQL/provider exception is chained or exposed.
            raise scenario_error(rejection)

        return await asyncio.to_thread(execute)

    def _page(
        self,
        session: Session,
        auth: ReportAuthorization,
        resource: CollectionSnapshotResource,
        query: app.ScenarioPageQuery,
        statement: Select[tuple[UUID]],
        *filters: object,
    ) -> CollectionSnapshotPage:
        if type(query) is not app.ScenarioPageQuery:
            raise scenario_error(app.ScenarioErrorCode.VALIDATION_FAILED)
        auth.check(session, now=self._now())
        definition = CollectionSnapshotDefinition(
            resource=resource,
            owner_id=auth.owner_id,
            broker_account_id=auth.account_id,
            # A refreshed token retains its stable identity; a different principal cannot resume.
            filter_fingerprint=collection_filter_fingerprint(
                "scenario.metadata.v1",
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

    def _capacity_for_owner(self, session: Session, owner: UUID) -> PremiumCapacityModel:
        session.execute(
            insert(PremiumCapacityModel)
            .values(
                owner_id=owner,
                reserved_bytes=0,
                retained_bytes=0,
                active_jobs=0,
                definition_versions=0,
                updated_at=self._now(),
            )
            .on_conflict_do_nothing(index_elements=["owner_id"])
        )
        row = session.scalar(
            select(PremiumCapacityModel)
            .where(PremiumCapacityModel.owner_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise scenario_error(app.ScenarioErrorCode.SCENARIO_UNAVAILABLE)
        return row
