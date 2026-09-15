"""Eight frozen research operations over durable current owner/account authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import research as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_application.sources import SourceServiceError
from trading212_application.views import Page
from trading212_application.xray import XrayServiceError
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.research_notes import ResearchNoteRevision, ResearchReviewAcknowledgment
from trading212_security.principals import AuthorizationError, Authorizer, Principal

from .collection_snapshots import (
    CollectionSnapshotScopeError,
)
from .premium_models import PremiumOwned
from .report_authorization import ReportAuthorization, authorize_report_request
from .research_item_store import ResearchItemStore
from .research_models import (
    ResearchEventModel,
    ResearchItemModel,
    ResearchNoteModel,
    ResearchNoteRevisionModel,
)
from .research_note_page import research_note_page
from .research_page_authorization import ResearchPageAuthority, authorize_research_page
from .research_permissions import ResearchCapabilityAuthority
from .research_source_store import research_error, research_owner_lock
from .research_summary_page import research_summary_page
from .xray_run_store import XrayRunStore


class PostgresResearchService(ResearchItemStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        capability_authority: ResearchCapabilityAuthority | None = None,
    ) -> None:
        super().__init__(sessions=sessions, cursor_signing_key=cursor_signing_key, clock=clock)
        self._research_capabilities = capability_authority
        self._research_xray = XrayRunStore(
            sessions=sessions, cursor_signing_key=cursor_signing_key, clock=self._clock
        )

    async def _research_execute[T](
        self,
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ReportAuthorization], T],
        *,
        write: bool = False,
        resource: tuple[type[PremiumOwned], UUID] | None = None,
        expected_account_id: UUID | None = None,
    ) -> T:
        scopes = app.RESEARCH_WRITE_SCOPES if write else app.RESEARCH_READ_SCOPES
        try:
            for scope in scopes:
                Authorizer().require_scope(principal, scope, now=self._now())
            owner = UUID(principal.owner_id)
        except (AuthorizationError, ValueError):
            raise research_error(app.ResearchErrorCode.ACCESS_DENIED) from None

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    account = account_id
                    if resource is not None:
                        model, identifier = resource
                        if type(identifier) is not UUID:
                            raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
                        account = session.scalar(
                            select(model.account_id).where(
                                model.owner_id == owner, model.id == identifier
                            )
                        )
                        if account is None:
                            raise research_error(app.ResearchErrorCode.NOT_FOUND)
                    if type(account) is not UUID:
                        raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
                    if expected_account_id is not None and account != expected_account_id:
                        raise research_error(app.ResearchErrorCode.NOT_FOUND)
                    auth = authorize_report_request(
                        session,
                        principal,
                        account_id=account,
                        required_scopes=scopes,
                        now=self._now(),
                    )
                    research_owner_lock(session, owner)
                    self.research_authority(session, auth, write=write)
                    value = operation(session, auth)
                    self.research_authority(session, auth, write=write)
                    return value
            except AuthorizationError:
                code = app.ResearchErrorCode.ACCESS_DENIED
            except CollectionSnapshotCapacityError:
                code = app.ResearchErrorCode.RATE_LIMITED
            except CursorValidationError:
                code = app.ResearchErrorCode.CURSOR_INVALID
            except CollectionSnapshotScopeError:
                code = app.ResearchErrorCode.NOT_FOUND
            except (SourceServiceError, XrayServiceError):
                code = app.ResearchErrorCode.SOURCE_UNAVAILABLE
            except DomainError as error:
                code = (
                    app.ResearchErrorCode.INPUT_BOUND_EXCEEDED
                    if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.ResearchErrorCode.VALIDATION_FAILED
                )
            except IntegrityError:
                code = app.ResearchErrorCode.CONFLICT
            except SQLAlchemyError:
                code = app.ResearchErrorCode.SOURCE_UNAVAILABLE
            raise research_error(code)

        return await asyncio.to_thread(execute)

    async def _research_page_execute[T](
        self,
        principal: Principal,
        account_id: UUID | None,
        operation: Callable[[Session, ResearchPageAuthority], T],
        *,
        resource: tuple[type[PremiumOwned], UUID] | None = None,
    ) -> T:
        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    authority = authorize_research_page(
                        session,
                        principal,
                        account_id,
                        now=self._now(),
                        resource=resource,
                    )
                    value = operation(session, authority)
                    final = authorize_research_page(
                        session,
                        principal,
                        authority.auth.account_id,
                        now=self._now(),
                    )
                    if final != authority:
                        raise research_error(app.ResearchErrorCode.CURSOR_INVALID)
                    return value
            except AuthorizationError:
                code = app.ResearchErrorCode.ACCESS_DENIED
            except CursorValidationError:
                code = app.ResearchErrorCode.CURSOR_INVALID
            except DomainError as error:
                code = (
                    app.ResearchErrorCode.INPUT_BOUND_EXCEEDED
                    if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.ResearchErrorCode.VALIDATION_FAILED
                )
            except IntegrityError:
                code = app.ResearchErrorCode.CONFLICT
            except SQLAlchemyError:
                code = app.ResearchErrorCode.SOURCE_UNAVAILABLE
            raise research_error(code)

        return await asyncio.to_thread(execute)

    async def get_research_summary(
        self, principal: Principal, query: app.ResearchSummaryQuery
    ) -> app.ResearchSummary:
        return await self._research_page_execute(
            principal,
            query.account_id,
            lambda s, a: research_summary_page(self, s, a, query),
        )

    async def get_research_item(
        self, principal: Principal, item_id: UUID, *, expected_account_id: UUID | None = None
    ) -> app.ResearchItemView:
        return await self._research_execute(
            principal,
            None,
            lambda s, a: self._get_item(s, a, item_id),
            resource=(ResearchItemModel, item_id),
            expected_account_id=expected_account_id,
        )

    async def list_research_notes(
        self, principal: Principal, account_id: UUID, query: app.ResearchPageQuery
    ) -> Page[ResearchNoteRevision]:
        return await self._research_page_execute(
            principal,
            account_id,
            lambda s, a: research_note_page(s, a, query, now=self._now(), cursors=self._cursors),
        )

    async def create_research_note(
        self, principal: Principal, command: app.CreateResearchNote
    ) -> ResearchNoteRevision:
        return await self._research_execute(
            principal, command.account_id, lambda s, a: self._create_note(s, a, command), write=True
        )

    async def get_research_note(self, principal: Principal, note_id: UUID) -> ResearchNoteRevision:
        def read(session: Session, auth: ReportAuthorization) -> ResearchNoteRevision:
            identifier = session.scalar(
                select(ResearchNoteRevisionModel.id)
                .join(
                    ResearchNoteModel,
                    (ResearchNoteModel.id == ResearchNoteRevisionModel.note_id)
                    & (ResearchNoteModel.revision == ResearchNoteRevisionModel.revision),
                )
                .where(
                    ResearchNoteModel.owner_id == auth.owner_id,
                    ResearchNoteModel.account_id == auth.account_id,
                    ResearchNoteModel.id == note_id,
                )
            )
            if identifier is None:
                raise research_error(app.ResearchErrorCode.NOT_FOUND)
            return self.read_note_revision(session, auth, identifier)

        return await self._research_execute(
            principal, None, read, resource=(ResearchNoteModel, note_id)
        )

    async def list_research_note_versions(
        self, principal: Principal, note_id: UUID, query: app.ResearchPageQuery
    ) -> Page[ResearchNoteRevision]:
        return await self._research_page_execute(
            principal,
            None,
            lambda s, a: research_note_page(
                s, a, query, now=self._now(), cursors=self._cursors, note_id=note_id
            ),
            resource=(ResearchNoteModel, note_id),
        )

    async def create_research_note_version(
        self, principal: Principal, command: app.CreateResearchNoteVersion
    ) -> ResearchNoteRevision:
        return await self._research_execute(
            principal,
            None,
            lambda s, a: self._create_note_version(s, a, command),
            write=True,
            resource=(ResearchNoteModel, command.note_id),
        )

    async def review_research_event(
        self, principal: Principal, command: app.ReviewResearchEvent
    ) -> ResearchReviewAcknowledgment:
        return await self._research_execute(
            principal,
            None,
            lambda s, a: self._review_event(s, a, command),
            write=True,
            resource=(ResearchEventModel, command.event_id),
        )
