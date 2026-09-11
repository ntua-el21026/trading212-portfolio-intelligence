"""Current authorization over pinned retained intelligence and stable visible sources."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import intelligence_quality as q
from trading212_application.queries import CursorCodec, CursorValidationError
from trading212_domain.serialization import canonical_json
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Principal, Scope

from .collection_snapshots import (
    CollectionSnapshot,
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .intelligence_quality_models import (
    IntelligenceQualityCollectionBindingModel as Binding,
)
from .intelligence_quality_models import (
    IntelligenceQualityCollectionSourceModel as Member,
)
from .intelligence_quality_projection import decode_metrics, empty_metrics, overlay_sources
from .intelligence_quality_selection import RetainedSelection, dependency_inventory, select_retained
from .intelligence_quality_sources import QualitySourceReader
from .models import CollectionQuerySnapshotModel, ReconciliationRunModel
from .report_authorization import authorize_report_request

BASE_SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ})
FAMILY_SCOPE = {
    q.IntelligenceKind.ACTUAL_VS_TARGET: Scope.TARGETS_READ,
    q.IntelligenceKind.DRIFT: Scope.TARGETS_READ,
    q.IntelligenceKind.INCOME: Scope.ACTIVITY_READ,
    q.IntelligenceKind.CASH_FLOW: Scope.ACTIVITY_READ,
}


class PostgresIntelligenceDataQualityService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursors = CursorCodec(
            cursor_signing_key, clock=self._clock, ttl_seconds=cursor_ttl_seconds
        )
        self._ttl = cursor_ttl_seconds
        self._snapshot_quota = max_active_collection_snapshots_per_owner
        self._member_quota = max_active_collection_members_per_owner

    async def get_intelligence_data_quality(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: q.IntelligenceDataQualityQuery,
    ) -> q.IntelligenceQualityResult:
        account = UUID(account_id)
        if str(account) != account_id:
            raise ValueError("A canonical account UUID is required.")
        return await asyncio.to_thread(self._read, principal, account, query)

    def _read(
        self, principal: Principal, account: UUID, query: q.IntelligenceDataQualityQuery
    ) -> q.IntelligenceQualityResult:
        with self._sessions() as session, session.begin():
            checked_at = require_utc(self._clock())
            # Reuse the existing durable request checker with the requesting
            # principal unchanged; never call its synthetic delegation helper.
            authorization = authorize_report_request(
                session, principal, account_id=account, required_scopes=BASE_SCOPES, now=checked_at
            )
            scopes = set(BASE_SCOPES)
            optional = []
            for scope in (Scope.ACTIVITY_READ, Scope.TARGETS_READ):
                try:
                    granted = authorize_report_request(
                        session,
                        principal,
                        account_id=account,
                        required_scopes=BASE_SCOPES | {scope},
                        now=checked_at,
                    )
                except AuthorizationError:
                    continue
                scopes.add(scope)
                optional.append(granted)
            required = FAMILY_SCOPE.get(query.analytics_kind)
            if required is not None and required not in scopes:
                # This branch precedes *all* family lookups, IDs, counts and cursors.
                authorization.check(session, now=require_utc(self._clock()))
                return q.IntelligenceQualityPermissionRequired(
                    account_id=account,
                    analytics_kind=query.analytics_kind,
                    checked_at=checked_at,
                    missing_scope=required,
                )
            granted_scopes = frozenset(scopes)
            owner = authorization.owner_id
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"sources:{owner}"},
            )
            definition = CollectionSnapshotDefinition(
                resource=CollectionSnapshotResource.INTELLIGENCE_QUALITY_SOURCES,
                owner_id=owner,
                broker_account_id=account,
                filter_fingerprint=collection_filter_fingerprint(
                    "intelligence-quality-v1",
                    query.analytics_kind.value,
                    authorization.principal_id,
                    *(
                        scope.value
                        for scope in sorted(granted_scopes, key=lambda value: value.value)
                    ),
                ),
            )
            store = CollectionSnapshotStore(
                session,
                self._cursors,
                ttl_seconds=self._ttl,
                max_active_snapshots_per_owner=self._snapshot_quota,
                max_active_members_per_owner=self._member_quota,
            )
            page = None
            selection_at = checked_at
            if query.cursor is not None:
                page = store.resume(definition, query.cursor, limit=query.limit)
                binding = session.scalar(
                    select(Binding).where(
                        Binding.collection_id == page.snapshot_id,
                        Binding.owner_id == owner,
                        Binding.account_id == account,
                        Binding.analytics_kind == query.analytics_kind.value,
                    )
                )
                if binding is None:
                    raise CursorValidationError("invalid cursor")
                selection_at = binding.selection_at
                selected = select_retained(
                    session,
                    owner,
                    account,
                    query.analytics_kind,
                    selection_at,
                    granted_scopes,
                    identifier=binding.valuation_snapshot_id or binding.analytics_run_id,
                )
                if (
                    selected is None
                    or selected.view.content_digest != binding.content_digest
                    or (
                        selected.view.input_id
                        != (binding.historical_input_id or binding.xray_input_id)
                    )
                ):
                    raise CursorValidationError("invalid cursor")
            else:
                selected = select_retained(
                    session, owner, account, query.analytics_kind, selection_at, granted_scopes
                )
            if selected is None:
                authorization.check(session, now=require_utc(self._clock()))
                return self._result(
                    account,
                    query,
                    checked_at,
                    selection_at,
                    None,
                    empty_metrics(query.analytics_kind, q.QualityReason.NOT_CALCULATED),
                    (),
                    None,
                    granted_scopes,
                )

            identities = dependency_inventory(
                session, owner, account, query.analytics_kind, selected, granted_scopes
            )
            sources = tuple(
                QualitySourceReader(session, owner, account, checked_at).read(identity)
                for identity in identities
            )
            if page is None:
                page, selection_at = self._materialize(
                    session, store, definition, query, selected, selection_at, identities
                )
            members = self._members(session, owner, page.snapshot_id)
            if tuple(identity for _, identity in members) != identities or page.exact_total != len(
                identities
            ):
                raise CursorValidationError("invalid cursor")

            blocked = tuple(source for source in sources if source.current_usability != "usable")
            if not selected.retained:
                metrics = empty_metrics(
                    query.analytics_kind, q.QualityReason.SOURCE_PURGED, blocked=True
                )
            elif blocked:
                metrics = empty_metrics(query.analytics_kind, blocked[0].reasons[0], blocked=True)
            else:
                try:
                    metrics = decode_metrics(
                        session, owner, account, query.analytics_kind, selected
                    )
                except q.IntelligenceQualityError as exc:
                    if exc.code == "RESULT_TOO_LARGE":
                        raise
                    metrics = empty_metrics(
                        query.analytics_kind, q.QualityReason.INTEGRITY_MISMATCH, blocked=True
                    )

            # The same source-owner lock serializes retention/license publication.
            # Time may still cross an expiry boundary during decoding: recheck at seal.
            sealed_at = require_utc(self._clock())
            authorization.check(session, now=sealed_at)
            for granted in optional:
                granted.check(session, now=sealed_at)
            sources = tuple(
                QualitySourceReader(session, owner, account, sealed_at).read(identity)
                for identity in identities
            )
            blocked = tuple(source for source in sources if source.current_usability != "usable")
            if blocked:
                metrics = empty_metrics(query.analytics_kind, blocked[0].reasons[0], blocked=True)
            metrics = overlay_sources(metrics, sources)
            values = dict(zip((identifier for identifier, _ in members), sources, strict=True))
            visible_page = tuple(values[identifier] for identifier in page.record_ids)
            result = self._result(
                account,
                query,
                sealed_at,
                selection_at,
                selected,
                metrics,
                visible_page,
                page,
                granted_scopes,
            )
            reconciliation = self._reconciliation(session, account, identities, granted_scopes)
            result = replace(result, reconciliation=reconciliation)
            if len(canonical_json(result).encode()) > q.MAX_QUALITY_BYTES:
                raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
            return result

    @staticmethod
    def _members(
        session: Session, owner: UUID, collection: UUID
    ) -> tuple[tuple[UUID, q.QualitySourceIdentity], ...]:
        rows = session.execute(
            select(Member.id, Member.source_kind, Member.source_id, Member.parent_id)
            .where(Member.owner_id == owner, Member.collection_id == collection)
            .order_by(Member.ordinal)
            .limit(q.MAX_QUALITY_SOURCES + 1)
        ).all()
        if len(rows) > q.MAX_QUALITY_SOURCES:
            raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
        return tuple(
            (
                row.id,
                q.QualitySourceIdentity(
                    kind=q.QualitySourceKind(row.source_kind),
                    id=row.source_id,
                    parent_id=row.parent_id,
                ),
            )
            for row in rows
        )

    def _materialize(
        self,
        session: Session,
        store: CollectionSnapshotStore,
        definition: CollectionSnapshotDefinition,
        query: q.IntelligenceDataQualityQuery,
        selected: RetainedSelection,
        at: datetime,
        identities: tuple[q.QualitySourceIdentity, ...],
    ) -> tuple[CollectionSnapshotPage, datetime]:
        collection = CollectionQuerySnapshotModel
        selected_column = (
            Binding.valuation_snapshot_id
            if selected.view.kind == "valuation"
            else Binding.analytics_run_id
        )
        old = session.execute(
            select(collection, Binding.selection_at)
            .join(Binding, Binding.collection_id == collection.id)
            .where(
                collection.owner_id == definition.owner_id,
                collection.broker_account_id == definition.broker_account_id,
                collection.resource == definition.resource.value,
                collection.filter_fingerprint == definition.filter_fingerprint,
                collection.expires_at > func.clock_timestamp(),
                Binding.owner_id == definition.owner_id,
                Binding.account_id == definition.broker_account_id,
                Binding.analytics_kind == query.analytics_kind.value,
                selected_column == selected.view.id,
                Binding.content_digest == selected.view.content_digest,
            )
            .order_by(collection.created_at.desc(), collection.id.desc())
            .limit(1)
        ).first()
        if old is not None:
            retained, selection_at = old
            if (
                tuple(
                    identity
                    for _, identity in self._members(session, definition.owner_id, retained.id)
                )
                != identities
            ):
                raise CursorValidationError("invalid cursor")
            page = store._read_page(
                CollectionSnapshot(
                    retained.id,
                    definition,
                    retained.exact_total,
                    retained.created_at,
                    retained.expires_at,
                ),
                after_ordinal=0,
                limit=query.limit,
            )
            return page, selection_at

        def records(collection_id: UUID) -> Iterable[UUID]:
            session.add(
                Binding(
                    collection_id=collection_id,
                    owner_id=definition.owner_id,
                    account_id=definition.broker_account_id,
                    analytics_kind=query.analytics_kind.value,
                    selection_at=at,
                    content_digest=selected.view.content_digest,
                    valuation_snapshot_id=selected.view.id
                    if selected.view.kind == "valuation"
                    else None,
                    analytics_run_id=selected.view.id
                    if selected.view.kind == "analytics"
                    else None,
                    historical_input_id=selected.view.input_id
                    if selected.view.input_kind == "historical"
                    else None,
                    xray_input_id=selected.view.input_id
                    if selected.view.input_kind == "xray"
                    else None,
                )
            )
            session.flush()
            for ordinal, identity in enumerate(identities, 1):
                identifier = uuid4()
                session.add(
                    Member(
                        id=identifier,
                        owner_id=definition.owner_id,
                        collection_id=collection_id,
                        ordinal=ordinal,
                        source_kind=identity.kind.value,
                        source_id=identity.id,
                        parent_id=identity.parent_id,
                    )
                )
                yield identifier
            session.flush()

        return store.materialize_generated(
            definition, exact_total=len(identities), create_records=records, limit=query.limit
        ), at

    @staticmethod
    def _reconciliation(
        session: Session,
        account: UUID,
        identities: tuple[q.QualitySourceIdentity, ...],
        scopes: frozenset[Scope],
    ) -> q.QualityReconciliation:
        if Scope.ACTIVITY_READ not in scopes:
            return q.QualityReconciliation(visibility="permission_required")
        ids = {
            identity.id
            for identity in identities
            if identity.kind is q.QualitySourceKind.RECONCILIATION
        }
        if len(ids) != 1:
            return q.QualityReconciliation(
                visibility="visible", reason=q.QualityReason.RECONCILIATION_MISSING
            )
        row = session.execute(
            select(
                ReconciliationRunModel.id,
                ReconciliationRunModel.as_of,
                ReconciliationRunModel.status,
                ReconciliationRunModel.coverage_complete,
                ReconciliationRunModel.discrepancy_count,
            ).where(
                ReconciliationRunModel.id == next(iter(ids)),
                ReconciliationRunModel.broker_account_id == account,
            )
        ).one_or_none()
        if row is None or row.status not in {"reconciled", "unreconciled", "partial", "failed"}:
            return q.QualityReconciliation(
                visibility="visible", reason=q.QualityReason.METADATA_UNAVAILABLE
            )
        return q.QualityReconciliation(
            visibility="visible",
            id=row.id,
            as_of=row.as_of,
            status=row.status,
            complete=row.coverage_complete,
            discrepancy_count=row.discrepancy_count,
            reason=None if row.coverage_complete else q.QualityReason.RECONCILIATION_INCOMPLETE,
        )

    @staticmethod
    def _result(
        account: UUID,
        query: q.IntelligenceDataQualityQuery,
        checked: datetime,
        selection_at: datetime,
        selected: RetainedSelection | None,
        metrics: tuple[q.MetricQuality, ...],
        sources: tuple[q.QualitySource, ...],
        page: CollectionSnapshotPage | None,
        scopes: frozenset[Scope],
    ) -> q.IntelligenceDataQuality:
        return q.IntelligenceDataQuality(
            account_id=account,
            analytics_kind=query.analytics_kind,
            checked_at=checked,
            selection_at=selection_at,
            selection=None if selected is None else selected.view,
            selection_state="not_available"
            if selected is None
            else "unavailable"
            if any(metric.current_usability == "blocked" for metric in metrics)
            else "retained",
            metrics=metrics,
            reconciliation=q.QualityReconciliation(
                visibility="visible" if Scope.ACTIVITY_READ in scopes else "permission_required"
            ),
            sources=q.QualitySourcePage(
                items=sources,
                exact_total=0 if page is None else page.exact_total,
                limit=query.limit,
                next_cursor=None if page is None else page.next_cursor,
                expires_at=None if page is None else page.expires_at,
            ),
            activity_visibility="visible"
            if Scope.ACTIVITY_READ in scopes
            else "permission_required",
            targets_visibility="visible" if Scope.TARGETS_READ in scopes else "permission_required",
        )
