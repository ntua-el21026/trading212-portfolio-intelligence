"""Durable owner layouts with bounded immutable pages and current account authorization."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import owner_layouts as app
from trading212_application.queries import CursorCodec, CursorValidationError
from trading212_domain import owner_layouts as d
from trading212_domain.errors import DomainError
from trading212_domain.owner_layout_codec import owner_layout_bytes, owner_layout_digest
from trading212_domain.serialization import canonical_json
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Principal

from .models import AuditEventModel
from .owner_layout_authorization import (
    LayoutAuthority,
    authorize_layout_owner,
    authorize_layout_references,
    require_layout_references,
)
from .owner_layout_cursor import LayoutPageMember, layout_page_capsule, layout_page_members
from .owner_layout_models import (
    OwnerLayoutCommandModel,
    OwnerLayoutModel,
    SavedLayoutWidgetModel,
    SavedViewVersionModel,
)
from .owner_layout_records import (
    decode_layout_version,
    layout_reference_record,
    layout_widget_models,
)

# A physical owner is capped at 32 retained identities, archived identities included.
# Consequently this indexed cohort never scans an unbounded number of headers; the
# 33rd row is an integrity failure, not a silently discarded page member.
_COHORT = text(
    "\n"
    "SELECT l.id,l.created_at,l.archived_at,v.id "
    "version_id,v.name,v.version_number,v.created_at "
    "version_created_at\n"
    "FROM owner_layouts l JOIN LATERAL (\n"
    " SELECT id,name,version_number,created_at FROM "
    "saved_view_versions v\n"
    " WHERE v.owner_id=l.owner_id AND v.layout_id=l.id AND "
    "v.created_at<=:cutoff\n"
    " ORDER BY v.created_at DESC,v.version_number DESC LIMIT 1\n"
    ") v ON true WHERE l.owner_id=:owner AND l.created_at<=:cutoff\n"
    "ORDER BY l.created_at,l.id LIMIT 33\n"
)

_PINNED_COHORT = text(
    "\n"
    "SELECT l.id,l.created_at,l.archived_at,v.id "
    "version_id,v.name,v.version_number,v.created_at "
    "version_created_at\n"
    "FROM jsonb_to_recordset(CAST(:members AS jsonb)) AS m(id "
    "uuid,version integer,ordinal integer)\n"
    "JOIN owner_layouts l ON l.id=m.id AND l.owner_id=:owner\n"
    "JOIN saved_view_versions v ON v.layout_id=l.id AND "
    "v.owner_id=l.owner_id AND v.version_number=m.version\n"
    "WHERE l.created_at<=:cutoff AND v.created_at<=:cutoff ORDER BY "
    "m.ordinal\n"
)


def _error(code: app.OwnerLayoutErrorCode) -> app.OwnerLayoutServiceError:
    return app.OwnerLayoutServiceError(code)


def _version_header(row: SavedViewVersionModel) -> app.OwnerLayoutVersionHeader:
    return app.OwnerLayoutVersionHeader(
        id=row.id,
        number=row.version_number,
        created_at=row.created_at,
        content_digest=row.content_digest,
    )


def _state(value: str) -> Literal["active", "archived"]:
    if value not in ("active", "archived"):
        raise _error(app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE)
    return cast(Literal["active", "archived"], value)


@dataclass(frozen=True, slots=True)
class _Operation[T]:
    value: T
    references: tuple[dict[str, Any], ...] = ()
    private: bool = True


class PostgresOwnerLayoutService(app.OwnerLayoutService):
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

    async def _execute[T](
        self,
        principal: Principal,
        operation: Callable[[Session, LayoutAuthority], _Operation[T]],
        *,
        write: bool = False,
    ) -> T:
        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    auth = authorize_layout_owner(session, principal, write=write, now=self._now())
                    if write:
                        session.execute(
                            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                            {"key": f"preferences:{auth.owner_id}"},
                        )
                    output = operation(session, auth)
                    final = authorize_layout_owner(session, principal, write=write, now=self._now())
                    if (final.owner_id, final.principal_id) != (auth.owner_id, auth.principal_id):
                        raise AuthorizationError("access denied")
                    reasons = authorize_layout_references(session, final, output.references)
                    if output.private and any(reason is not None for reason in reasons.values()):
                        raise AuthorizationError("access denied")
                    value = output.value
                    if isinstance(value, app.OwnerLayoutPage):
                        # Restriction is current even when page membership/content is pinned.
                        items = tuple(
                            replace(
                                item,
                                availability="restricted",
                                reason=cast(
                                    Literal["account_unavailable", "selection_unavailable"],
                                    reasons[str(item.id)],
                                ),
                            )
                            if reasons.get(str(item.id))
                            else item
                            for item in value.items
                        )
                        value = cast(T, replace(value, items=items))
                    return value
            except AuthorizationError:
                code = app.OwnerLayoutErrorCode.ACCESS_DENIED
            except CursorValidationError:
                code = app.OwnerLayoutErrorCode.CURSOR_INVALID
            except DomainError:
                code = app.OwnerLayoutErrorCode.VALIDATION_FAILED
            except IntegrityError:
                code = app.OwnerLayoutErrorCode.CONFLICT
            except SQLAlchemyError:
                code = app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE
            raise _error(code)

        return await asyncio.to_thread(execute)

    def _root(
        self, session: Session, auth: LayoutAuthority, identifier: UUID, *, lock: bool = False
    ) -> OwnerLayoutModel:
        d.layout_uuid(identifier, "layout_id")
        query = (
            select(OwnerLayoutModel)
            .where(OwnerLayoutModel.owner_id == auth.owner_id, OwnerLayoutModel.id == identifier)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise _error(app.OwnerLayoutErrorCode.NOT_FOUND)
        return row

    def _widgets(
        self, session: Session, auth: LayoutAuthority, version_ids: tuple[UUID, ...]
    ) -> tuple[SavedLayoutWidgetModel, ...]:
        if not version_ids:
            return ()
        if len(version_ids) > d.MAX_OWNER_LAYOUTS:
            raise _error(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
        values = tuple(
            session.scalars(
                select(SavedLayoutWidgetModel)
                .where(
                    SavedLayoutWidgetModel.owner_id == auth.owner_id,
                    SavedLayoutWidgetModel.version_id.in_(version_ids),
                )
                .order_by(SavedLayoutWidgetModel.version_id, SavedLayoutWidgetModel.ordinal)
                .limit(len(version_ids) * d.MAX_LAYOUT_WIDGETS + 1)
            )
        )
        if len(values) > len(version_ids) * d.MAX_LAYOUT_WIDGETS:
            raise _error(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
        return values

    def _detail(
        self,
        session: Session,
        auth: LayoutAuthority,
        root: OwnerLayoutModel,
        version_id: UUID | None = None,
    ) -> _Operation[app.OwnerLayoutView]:
        versions = tuple(
            session.scalars(
                select(SavedViewVersionModel)
                .where(
                    SavedViewVersionModel.owner_id == auth.owner_id,
                    SavedViewVersionModel.layout_id == root.id,
                )
                .order_by(SavedViewVersionModel.version_number)
                .limit(d.MAX_LAYOUT_VERSIONS + 1)
            )
        )
        if not 1 <= len(versions) <= d.MAX_LAYOUT_VERSIONS:
            raise _error(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
        selected = next(
            (value for value in versions if value.id == (version_id or root.current_version_id)),
            None,
        )
        if selected is None:
            raise _error(app.OwnerLayoutErrorCode.NOT_FOUND)
        widgets = self._widgets(session, auth, (selected.id,))
        refs = tuple(
            {"key": str(root.id), **layout_reference_record(selected.account_id, row)}
            for row in widgets
        )
        require_layout_references(session, auth, refs)
        # canonical_content is deferred on all preceding metadata ORM reads.
        payload = session.scalar(
            select(SavedViewVersionModel.canonical_content).where(
                SavedViewVersionModel.owner_id == auth.owner_id,
                SavedViewVersionModel.id == selected.id,
            )
        )
        if payload is None or not widgets:
            raise _error(app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE)
        content = decode_layout_version(selected, payload, widgets)
        return _Operation(
            app.OwnerLayoutView(
                id=root.id,
                revision=root.revision,
                state=_state(root.state),
                version=_version_header(selected),
                content=content,
                versions=tuple(_version_header(value) for value in versions),
            ),
            refs,
        )

    async def get_owner_layout(
        self, principal: Principal, layout_id: UUID, *, version_id: UUID | None = None
    ) -> app.OwnerLayoutView:
        d.layout_uuid(version_id, "version_id", optional=True)
        return await self._execute(
            principal,
            lambda session, auth: self._detail(
                session, auth, self._root(session, auth, layout_id), version_id
            ),
        )

    async def list_owner_layouts(
        self, principal: Principal, query: app.OwnerLayoutPageQuery
    ) -> app.OwnerLayoutPage:
        def read(session: Session, auth: LayoutAuthority) -> _Operation[app.OwnerLayoutPage]:
            binding = canonical_json(
                (
                    str(auth.owner_id),
                    principal.issuer,
                    principal.subject,
                    "owner-layouts-v1",
                    query.limit,
                    query.include_archived,
                )
            )
            cutoff = self._now()
            previous: UUID | None = None
            members: tuple[LayoutPageMember, ...]
            if query.cursor is not None:
                cutoff, keys = self._cursors.decode(
                    query.cursor, resource="owner-layouts-v1", binding=binding, key_size=2
                )
                try:
                    previous = UUID(keys[0])
                except ValueError:
                    raise CursorValidationError("invalid cursor") from None
                members = layout_page_members(keys[1])
                if not query.include_archived and any(member.archived for member in members):
                    raise CursorValidationError("invalid cursor")
                eligible = tuple(
                    session.execute(
                        _PINNED_COHORT,
                        {
                            "owner": auth.owner_id,
                            "cutoff": cutoff,
                            "members": json.dumps(
                                [
                                    {
                                        "id": str(member.layout_id),
                                        "version": member.version,
                                        "ordinal": ordinal,
                                    }
                                    for ordinal, member in enumerate(members)
                                ]
                            ),
                        },
                    ).mappings()
                )
                if tuple(row["id"] for row in eligible) != tuple(
                    member.layout_id for member in members
                ):
                    raise CursorValidationError("invalid cursor")
            else:
                cohort = tuple(
                    session.execute(_COHORT, {"owner": auth.owner_id, "cutoff": cutoff}).mappings()
                )
                if len(cohort) > d.MAX_OWNER_LAYOUTS:
                    raise _error(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
                eligible = tuple(
                    row
                    for row in cohort
                    if query.include_archived
                    or row["archived_at"] is None
                    or row["archived_at"] > cutoff
                )
                members = tuple(
                    LayoutPageMember(
                        layout_id=row["id"],
                        version=row["version_number"],
                        archived=row["archived_at"] is not None and row["archived_at"] <= cutoff,
                    )
                    for row in eligible
                )
            archive_flags = {member.layout_id: member.archived for member in members}
            offset = 0
            if previous is not None:
                found = next(
                    (index for index, row in enumerate(eligible) if row["id"] == previous), None
                )
                if found is None:
                    raise CursorValidationError("invalid cursor")
                offset = found + 1
            selected = eligible[offset : offset + query.limit]
            version_ids = tuple(row["version_id"] for row in selected)
            widgets = self._widgets(session, auth, version_ids)
            # This extra bounded metadata read never loads any canonical content.
            accounts = (
                dict(
                    session.execute(
                        select(SavedViewVersionModel.id, SavedViewVersionModel.account_id).where(
                            SavedViewVersionModel.owner_id == auth.owner_id,
                            SavedViewVersionModel.id.in_(version_ids),
                        )
                    )
                    .tuples()
                    .all()
                )
                if version_ids
                else {}
            )
            keys_by_version = {row["version_id"]: str(row["id"]) for row in selected}
            refs = tuple(
                {
                    "key": keys_by_version[row.version_id],
                    **layout_reference_record(accounts[row.version_id], row),
                }
                for row in widgets
            )
            if set(keys_by_version) != {row.version_id for row in widgets}:
                raise _error(app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE)
            reasons = authorize_layout_references(session, auth, refs)
            items = []
            for row in selected:
                archived = archive_flags[row["id"]]
                if archived and row["archived_at"] is None:
                    raise CursorValidationError("invalid cursor")
                reason = cast(
                    Literal["account_unavailable", "selection_unavailable"] | None,
                    reasons[str(row["id"])],
                )
                items.append(
                    app.OwnerLayoutSummary(
                        id=row["id"],
                        name=row["name"],
                        revision=row["version_number"] + int(archived),
                        state="archived" if archived else "active",
                        created_at=row["created_at"],
                        updated_at=row["archived_at"] if archived else row["version_created_at"],
                        availability="available" if reason is None else "restricted",
                        reason=reason,
                    )
                )
            next_cursor = None
            if selected and offset + len(selected) < len(eligible):
                next_cursor = self._cursors.encode(
                    resource="owner-layouts-v1",
                    binding=binding,
                    read_cutoff=cutoff,
                    key=(str(selected[-1]["id"]), layout_page_capsule(members)),
                )
            return _Operation(
                app.OwnerLayoutPage(
                    items=tuple(items),
                    total=len(eligible),
                    limit=query.limit,
                    next_cursor=next_cursor,
                    read_cutoff_at=cutoff,
                ),
                refs,
                False,
            )

        return await self._execute(principal, read)

    def _command_digest(self, name: str, command: app.LayoutCommand) -> str:
        if isinstance(command, app.UpdateOwnerLayout):
            shape: object = (
                name,
                command.layout_id,
                command.expected_revision,
                owner_layout_digest(command.content),
            )
        elif isinstance(command, app.CreateOwnerLayout):
            shape = (name, owner_layout_digest(command.content))
        elif isinstance(command, app.ArchiveOwnerLayout):
            shape = (name, command.layout_id, command.expected_revision)
        else:
            raise _error(app.OwnerLayoutErrorCode.VALIDATION_FAILED)
        return hashlib.sha256(
            b"owner-layout-command-v1\0" + canonical_json(shape).encode()
        ).hexdigest()

    def _prior(
        self, session: Session, auth: LayoutAuthority, name: str, command: app.LayoutCommand
    ) -> OwnerLayoutCommandModel | None:
        row = session.scalar(
            select(OwnerLayoutCommandModel).where(
                OwnerLayoutCommandModel.owner_id == auth.owner_id,
                OwnerLayoutCommandModel.command == name,
                OwnerLayoutCommandModel.idempotency_key == command.idempotency_key,
            )
        )
        if row is not None and row.command_digest != self._command_digest(name, command):
            raise _error(app.OwnerLayoutErrorCode.CONFLICT)
        return row

    def _record(
        self,
        session: Session,
        auth: LayoutAuthority,
        root: OwnerLayoutModel,
        version_id: UUID,
        name: str,
        command: app.LayoutCommand,
        at: datetime,
    ) -> None:
        audit_id = uuid4()
        session.add(
            AuditEventModel(
                id=audit_id,
                owner_id=auth.owner_id,
                principal_id=auth.principal_id,
                broker_account_id=None,
                action=name,
                resource_type="owner_layout",
                resource_id=str(root.id),
                outcome="success",
                occurred_at=at,
                correlation_id=command.correlation_id,
                safe_metadata={"revision": root.revision, "version_id": str(version_id)},
            )
        )
        # The audit FK is immediate, so persist its row before the receipt.
        session.flush()
        session.add(
            OwnerLayoutCommandModel(
                owner_id=auth.owner_id,
                layout_id=root.id,
                version_id=version_id,
                command=name,
                idempotency_key=command.idempotency_key,
                command_digest=self._command_digest(name, command),
                actor_id=auth.principal_id,
                correlation_id=command.correlation_id,
                result_revision=root.revision,
                audit_id=audit_id,
                created_at=at,
            )
        )

    def _new_version(
        self,
        session: Session,
        auth: LayoutAuthority,
        root: OwnerLayoutModel,
        content: d.OwnerLayoutContent,
        *,
        parent: UUID | None,
        number: int,
        at: datetime,
    ) -> SavedViewVersionModel:
        version_id = uuid4()
        widgets = layout_widget_models(
            content, owner=auth.owner_id, layout=root.id, version=version_id, at=at
        )
        refs = tuple(
            {"key": str(root.id), **layout_reference_record(content.account_id, row)}
            for row in widgets
        )
        require_layout_references(session, auth, refs)
        version = SavedViewVersionModel(
            id=version_id,
            owner_id=auth.owner_id,
            layout_id=root.id,
            version_number=number,
            parent_version_id=parent,
            schema_version=1,
            actor_id=auth.principal_id,
            account_id=content.account_id,
            name=content.name,
            description=content.description,
            columns=content.columns,
            density=content.density,
            content_digest=owner_layout_digest(content),
            canonical_content=owner_layout_bytes(content),
            created_at=at,
        )
        root.current_version_id = version_id
        root.updated_at = at
        root.actor_id = auth.principal_id
        # These mappings deliberately have no ORM relationships. Persist parents
        # explicitly before their immediate FKs and row guards consume them; the
        # current-version cycle and complete-document checks remain deferred.
        session.flush()
        session.add(version)
        session.flush()
        session.add_all(widgets)
        session.flush()
        return version

    async def create_owner_layout(
        self, principal: Principal, command: app.CreateOwnerLayout
    ) -> app.OwnerLayoutView:
        def create(session: Session, auth: LayoutAuthority) -> _Operation[app.OwnerLayoutView]:
            name = "preferences.layout.create.v1"
            prior = self._prior(session, auth, name, command)
            if prior is not None:
                return self._detail(
                    session, auth, self._root(session, auth, prior.layout_id), prior.version_id
                )
            count = session.scalar(
                select(func.count())
                .select_from(OwnerLayoutModel)
                .where(OwnerLayoutModel.owner_id == auth.owner_id)
            )
            if count is None or count >= d.MAX_OWNER_LAYOUTS:
                raise _error(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
            at = self._now()
            root = OwnerLayoutModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                current_version_id=uuid4(),
                revision=1,
                state="active",
                actor_id=auth.principal_id,
                created_at=at,
                updated_at=at,
                archived_at=None,
            )
            session.add(root)
            # Disable autoflush until both sides of the deferred current-version FK exist.
            with session.no_autoflush:
                version = self._new_version(
                    session, auth, root, command.content, parent=None, number=1, at=at
                )
                self._record(session, auth, root, version.id, name, command, at)
            session.flush()
            return self._detail(session, auth, root)

        return await self._execute(principal, create, write=True)

    async def update_owner_layout(
        self, principal: Principal, command: app.UpdateOwnerLayout
    ) -> app.OwnerLayoutView:
        def update(session: Session, auth: LayoutAuthority) -> _Operation[app.OwnerLayoutView]:
            name = "preferences.layout.update.v1"
            prior = self._prior(session, auth, name, command)
            if prior is not None:
                return self._detail(
                    session, auth, self._root(session, auth, prior.layout_id), prior.version_id
                )
            root = self._root(session, auth, command.layout_id, lock=True)
            if root.revision != command.expected_revision:
                raise _error(app.OwnerLayoutErrorCode.REVISION_MISMATCH)
            if root.state != "active":
                raise _error(app.OwnerLayoutErrorCode.CONFLICT)
            if root.revision >= d.MAX_LAYOUT_VERSIONS:
                raise _error(app.OwnerLayoutErrorCode.INPUT_BOUND_EXCEEDED)
            old = session.scalar(
                select(SavedViewVersionModel).where(
                    SavedViewVersionModel.owner_id == auth.owner_id,
                    SavedViewVersionModel.id == root.current_version_id,
                )
            )
            if old is None or old.content_digest == owner_layout_digest(command.content):
                raise _error(app.OwnerLayoutErrorCode.CONFLICT)
            at = self._now()
            if at < old.created_at:
                raise _error(app.OwnerLayoutErrorCode.CONFLICT)
            with session.no_autoflush:
                root.revision += 1
                version = self._new_version(
                    session, auth, root, command.content, parent=old.id, number=root.revision, at=at
                )
                self._record(session, auth, root, version.id, name, command, at)
            session.flush()
            return self._detail(session, auth, root)

        return await self._execute(principal, update, write=True)

    async def archive_owner_layout(
        self, principal: Principal, command: app.ArchiveOwnerLayout
    ) -> app.OwnerLayoutArchiveReceipt:
        def archive(
            session: Session, auth: LayoutAuthority
        ) -> _Operation[app.OwnerLayoutArchiveReceipt]:
            name = "preferences.layout.archive.v1"
            prior = self._prior(session, auth, name, command)
            root = self._root(session, auth, command.layout_id, lock=True)
            if prior is None:
                if root.revision != command.expected_revision:
                    raise _error(app.OwnerLayoutErrorCode.REVISION_MISMATCH)
                if root.state != "active":
                    raise _error(app.OwnerLayoutErrorCode.CONFLICT)
                at = self._now()
                if at < root.updated_at:
                    raise _error(app.OwnerLayoutErrorCode.CONFLICT)
                root.state = "archived"
                root.archived_at = at
                root.updated_at = at
                root.actor_id = auth.principal_id
                root.revision += 1
                if root.current_version_id is None:
                    raise _error(app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE)
                self._record(session, auth, root, root.current_version_id, name, command, at)
                session.flush()
            if root.archived_at is None:
                raise _error(app.OwnerLayoutErrorCode.SOURCE_UNAVAILABLE)
            # Archiving an inaccessible pointer needs owner preferences authority only.
            return _Operation(
                app.OwnerLayoutArchiveReceipt(
                    id=root.id,
                    revision=root.revision,
                    state="archived",
                    archived_at=root.archived_at,
                )
            )

        return await self._execute(principal, archive, write=True)
