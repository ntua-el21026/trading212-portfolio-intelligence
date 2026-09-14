"""Owned immutable risk definitions using existing identity, grant and cursor authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import risk as app
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
)
from trading212_application.views import Page
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.risk import RiskDefinitionContent
from trading212_domain.sources import source_key
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .historical_base import digest
from .premium_models import PremiumAuditModel, PremiumCapacityModel, PremiumOwned
from .report_authorization import ReportAuthorization, authorize_report_request
from .report_models import ApplicationCommandIdentityModel
from .risk_models import RiskDefinitionModel, RiskVersionModel
from .source_models import SourceCalendarModel

LiteralFrequency = Literal["daily", "monthly"]
LiteralReturn = Literal["simple", "log"]
LiteralRegularization = Literal["none", "diagonal_shrinkage"]

RISK_READ_SCOPES = frozenset((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ))
RISK_WRITE_SCOPES = RISK_READ_SCOPES | {Scope.RISK_WRITE}


def risk_error(code: app.RiskErrorCode) -> app.RiskServiceError:
    return app.RiskServiceError(code)


def premium_owner_lock(session: Session, owner: UUID) -> None:
    for namespace in ("sources", "historical", "premium"):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )


class RiskDefinitionStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursor_key = cursor_signing_key
        self._cursors = CursorCodec(cursor_signing_key, clock=self._clock)

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _execute[T](
        self,
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ReportAuthorization], T],
        *,
        write: bool = False,
        resource: tuple[type[PremiumOwned], UUID] | None = None,
    ) -> T:
        scopes = RISK_WRITE_SCOPES if write else RISK_READ_SCOPES
        try:
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._now())
        except AuthorizationError:
            raise risk_error(app.RiskErrorCode.ACCESS_DENIED) from None

        def execute() -> T:
            try:
                owner = UUID(principal.owner_id)
                with self._sessions() as session, session.begin():
                    account = account_id
                    if resource is not None:
                        model, identifier = resource
                        account = session.scalar(
                            select(model.account_id).where(
                                model.owner_id == owner,
                                model.id == identifier,
                            )
                        )
                        if account is None:
                            raise risk_error(app.RiskErrorCode.NOT_FOUND)
                    if type(account) is not UUID:
                        raise risk_error(app.RiskErrorCode.VALIDATION_FAILED)
                    authorization = authorize_report_request(
                        session,
                        principal,
                        account_id=account,
                        required_scopes=scopes,
                        now=self._now(),
                    )
                    premium_owner_lock(session, owner)
                    value = operation(session, authorization)
                    authorization.check(session, now=self._now())
                    return value
            except AuthorizationError:
                raise risk_error(app.RiskErrorCode.ACCESS_DENIED) from None
            except CollectionSnapshotCapacityError:
                raise risk_error(app.RiskErrorCode.RATE_LIMITED) from None
            except CursorValidationError:
                raise risk_error(app.RiskErrorCode.CURSOR_INVALID) from None
            except DomainError as failure:
                code = (
                    app.RiskErrorCode.INPUT_BOUND_EXCEEDED
                    if failure.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.RiskErrorCode.VALIDATION_FAILED
                )
                raise risk_error(code) from None
            except IntegrityError:
                raise risk_error(app.RiskErrorCode.CONFLICT) from None
            except SQLAlchemyError:
                raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE) from None

        return await asyncio.to_thread(execute)

    def _owned[M: PremiumOwned](
        self, session: Session, auth: ReportAuthorization, model: type[M], identifier: UUID
    ) -> M:
        row = session.scalar(
            select(model).where(
                model.id == identifier,
                model.owner_id == auth.owner_id,
                model.account_id == auth.account_id,
            )
        )
        if row is None:
            raise risk_error(app.RiskErrorCode.NOT_FOUND)
        return row

    def _capacity(self, session: Session, auth: ReportAuthorization) -> PremiumCapacityModel:
        return self._capacity_for_owner(session, auth.owner_id)

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
            .where(
                PremiumCapacityModel.owner_id == owner,
            )
            .with_for_update()
        )
        if row is None:
            raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
        return row

    def _prior(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: str,
        key: str,
        command_digest: str,
    ) -> ApplicationCommandIdentityModel | None:
        row = session.scalar(
            select(ApplicationCommandIdentityModel).where(
                ApplicationCommandIdentityModel.owner_id == auth.owner_id,
                ApplicationCommandIdentityModel.command == command,
                ApplicationCommandIdentityModel.idempotency_key == key,
            )
        )
        if row is not None and (
            row.account_id != auth.account_id or row.command_digest != command_digest
        ):
            raise risk_error(app.RiskErrorCode.CONFLICT)
        return row

    def _command(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: str,
        key: str,
        command_digest: str,
        resource_id: UUID,
        correlation: str,
        *,
        cancelled: bool = False,
    ) -> ApplicationCommandIdentityModel:
        row = ApplicationCommandIdentityModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            command=command,
            idempotency_key=key,
            command_digest=command_digest,
            report_job_id=None,
            export_job_id=None,
            premium_resource_id=resource_id,
            premium_actor_id=auth.principal_id,
            premium_correlation_id=correlation,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        session.add(
            PremiumAuditModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                command_id=row.id,
                kind="cancelled" if cancelled else "created",
                created_at=self._now(),
            )
        )
        session.flush()
        return row

    def _calendar(
        self, session: Session, auth: ReportAuthorization, content: RiskDefinitionContent
    ) -> SourceCalendarModel:
        source_key(content.calendar_id, "calendar_id")
        row = session.scalar(
            select(SourceCalendarModel).where(
                SourceCalendarModel.key == content.calendar_id,
                SourceCalendarModel.version == content.calendar_version,
                SourceCalendarModel.owner_id == auth.owner_id,
            )
        )
        if row is None or row.version != content.calendar_version:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        return row

    def _version_view(
        self, session: Session, row: RiskVersionModel, calendar: SourceCalendarModel | None = None
    ) -> app.RiskVersionView:
        calendar = calendar or session.scalar(
            select(SourceCalendarModel).where(
                SourceCalendarModel.id == row.calendar_id,
                SourceCalendarModel.owner_id == row.owner_id,
            )
        )
        if calendar is None:
            raise risk_error(app.RiskErrorCode.SOURCE_UNAVAILABLE)
        content = RiskDefinitionContent(
            name=row.name,
            description=row.description,
            calendar_id=calendar.key,
            calendar_version=calendar.version,
            frequency=cast("LiteralFrequency", row.frequency),
            return_kind=cast("LiteralReturn", row.return_kind),
            annual_risk_free=row.annual_risk_free,
            annual_minimum_acceptable_return=row.annual_minimum_acceptable_return,
            rolling_window=row.rolling_window,
            confidence=row.confidence,
            horizon=row.horizon,
            regularization=cast("LiteralRegularization", row.regularization),
            shrinkage=row.shrinkage,
        )
        if digest(content) != row.content_digest or row.method_version != content.method_version:
            raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
        return app.RiskVersionView(
            id=row.id,
            account_id=row.account_id,
            definition_id=row.definition_id,
            version_number=row.version_number,
            predecessor_id=row.predecessor_id,
            content=content,
            content_digest=row.content_digest,
            created_at=row.created_at,
        )

    def _definition_view(
        self, session: Session, row: RiskDefinitionModel, version_id: UUID | None = None
    ) -> app.RiskDefinitionView:
        version_id = version_id or session.scalar(
            select(RiskVersionModel.id).where(
                RiskVersionModel.owner_id == row.owner_id,
                RiskVersionModel.account_id == row.account_id,
                RiskVersionModel.definition_id == row.id,
                RiskVersionModel.version_number == row.revision,
            )
        )
        if version_id is None:
            raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
        return app.RiskDefinitionView(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            revision=row.revision,
            archived=row.archived,
            current_version_id=version_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _new_version(
        self,
        session: Session,
        auth: ReportAuthorization,
        parent: RiskDefinitionModel,
        content: RiskDefinitionContent,
        predecessor: UUID | None,
    ) -> RiskVersionModel:
        capacity = self._capacity(session, auth)
        if capacity.definition_versions >= 512:
            raise risk_error(app.RiskErrorCode.RATE_LIMITED)
        capacity.definition_versions += 1
        capacity.updated_at = self._now()
        fields = asdict(content)
        fields.pop("calendar_version")
        fields["calendar_id"] = self._calendar(session, auth, content).id
        row = RiskVersionModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            definition_id=parent.id,
            version_number=parent.revision,
            predecessor_id=predecessor,
            created_at=self._now(),
            content_digest=digest(content),
            **fields,
        )
        session.add(row)
        session.flush()
        return row

    async def create_definition(
        self, principal: Principal, command: app.CreateRiskDefinition
    ) -> app.RiskDefinitionView:
        def operation(session: Session, auth: ReportAuthorization) -> app.RiskDefinitionView:
            self._calendar(session, auth, command.content)
            identity = digest((command.account_id, command.content))
            prior = self._prior(
                session, auth, "risk.definition.create.v1", command.idempotency_key, identity
            )
            if prior is not None:
                return self._definition_view(
                    session,
                    self._owned(
                        session, auth, RiskDefinitionModel, cast(UUID, prior.premium_resource_id)
                    ),
                )
            self._capacity(session, auth)
            row = RiskDefinitionModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                name=command.content.name,
                revision=1,
                archived=False,
                created_at=self._now(),
                updated_at=self._now(),
            )
            session.add(row)
            session.flush()
            version = self._new_version(session, auth, row, command.content, None)
            self._command(
                session,
                auth,
                "risk.definition.create.v1",
                command.idempotency_key,
                identity,
                row.id,
                command.correlation_id,
            )
            return self._definition_view(session, row, version.id)

        return await self._execute(principal, command.account_id, operation, write=True)

    async def create_version(
        self, principal: Principal, command: app.CreateRiskVersion
    ) -> app.RiskVersionView:
        def operation(session: Session, auth: ReportAuthorization) -> app.RiskVersionView:
            calendar = self._calendar(session, auth, command.content)
            identity = digest(
                (auth.account_id, command.definition_id, command.expected_revision, command.content)
            )
            prior = self._prior(
                session, auth, "risk.version.create.v1", command.idempotency_key, identity
            )
            if prior is not None:
                return self._version_view(
                    session,
                    self._owned(
                        session, auth, RiskVersionModel, cast(UUID, prior.premium_resource_id)
                    ),
                    calendar,
                )
            parent = self._owned(session, auth, RiskDefinitionModel, command.definition_id)
            if parent.revision != command.expected_revision or parent.archived:
                raise risk_error(app.RiskErrorCode.REVISION_MISMATCH)
            if self._capacity(session, auth).definition_versions >= 512:
                raise risk_error(app.RiskErrorCode.RATE_LIMITED)
            predecessor = self._definition_view(session, parent).current_version_id
            parent.revision += 1
            parent.name = command.content.name
            parent.updated_at = self._now()
            session.flush()
            row = self._new_version(session, auth, parent, command.content, predecessor)
            self._command(
                session,
                auth,
                "risk.version.create.v1",
                command.idempotency_key,
                identity,
                row.id,
                command.correlation_id,
            )
            return self._version_view(session, row, calendar)

        return await self._execute(
            principal,
            None,
            operation,
            write=True,
            resource=(RiskDefinitionModel, command.definition_id),
        )

    async def get_definition(
        self, principal: Principal, definition_id: UUID
    ) -> app.RiskDefinitionView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self._definition_view(
                session, self._owned(session, auth, RiskDefinitionModel, definition_id)
            ),
            resource=(RiskDefinitionModel, definition_id),
        )

    async def get_version(self, principal: Principal, version_id: UUID) -> app.RiskVersionView:
        return await self._execute(
            principal,
            None,
            lambda session, auth: self._version_view(
                session, self._owned(session, auth, RiskVersionModel, version_id)
            ),
            resource=(RiskVersionModel, version_id),
        )

    def _page(
        self,
        session: Session,
        auth: ReportAuthorization,
        resource: CollectionSnapshotResource,
        query: app.RiskPageQuery,
        statement: Select[tuple[UUID]],
        *filters: object,
    ) -> CollectionSnapshotPage:
        definition = CollectionSnapshotDefinition(
            resource=resource,
            owner_id=auth.owner_id,
            broker_account_id=auth.account_id,
            filter_fingerprint=collection_filter_fingerprint(auth.account_id, *filters),
        )
        store = CollectionSnapshotStore(session, self._cursors)
        if query.cursor is not None:
            return store.resume(definition, query.cursor, limit=query.limit)
        return store.materialize(
            definition, lambda: session.scalars(statement.limit(250001)), limit=query.limit
        )

    async def list_definitions(
        self, principal: Principal, account_id: UUID, query: app.RiskPageQuery
    ) -> Page[app.RiskDefinitionView]:
        def operation(session: Session, auth: ReportAuthorization) -> Page[app.RiskDefinitionView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.RISK_DEFINITIONS,
                query,
                select(RiskDefinitionModel.id)
                .where(
                    RiskDefinitionModel.owner_id == auth.owner_id,
                    RiskDefinitionModel.account_id == auth.account_id,
                )
                .order_by(RiskDefinitionModel.created_at.desc(), RiskDefinitionModel.id.desc()),
            )
            records = session.execute(
                select(RiskDefinitionModel, RiskVersionModel.id)
                .join(
                    RiskVersionModel,
                    (RiskVersionModel.definition_id == RiskDefinitionModel.id)
                    & (RiskVersionModel.version_number == RiskDefinitionModel.revision),
                )
                .where(
                    RiskDefinitionModel.owner_id == auth.owner_id,
                    RiskDefinitionModel.account_id == auth.account_id,
                    RiskDefinitionModel.id.in_(page.record_ids),
                )
            ).all()
            rows = {
                row.id: self._definition_view(session, row, version_id)
                for row, version_id in records
            }
            if len(rows) != len(page.record_ids):
                raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
            return Page(
                tuple(rows[x] for x in page.record_ids),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._execute(principal, account_id, operation)

    async def list_versions(
        self, principal: Principal, definition_id: UUID, query: app.RiskPageQuery
    ) -> Page[app.RiskVersionView]:
        def operation(session: Session, auth: ReportAuthorization) -> Page[app.RiskVersionView]:
            page = self._page(
                session,
                auth,
                CollectionSnapshotResource.RISK_VERSIONS,
                query,
                select(RiskVersionModel.id)
                .where(
                    RiskVersionModel.owner_id == auth.owner_id,
                    RiskVersionModel.account_id == auth.account_id,
                    RiskVersionModel.definition_id == definition_id,
                )
                .order_by(RiskVersionModel.version_number.desc(), RiskVersionModel.id.desc()),
                definition_id,
            )
            records = session.execute(
                select(RiskVersionModel, SourceCalendarModel)
                .join(SourceCalendarModel, RiskVersionModel.calendar_id == SourceCalendarModel.id)
                .where(
                    RiskVersionModel.owner_id == auth.owner_id,
                    RiskVersionModel.account_id == auth.account_id,
                    RiskVersionModel.id.in_(page.record_ids),
                )
            ).all()
            rows = {row.id: self._version_view(session, row, calendar) for row, calendar in records}
            if len(rows) != len(page.record_ids):
                raise risk_error(app.RiskErrorCode.RISK_UNAVAILABLE)
            return Page(
                tuple(rows[x] for x in page.record_ids),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._execute(
            principal, None, operation, resource=(RiskDefinitionModel, definition_id)
        )
