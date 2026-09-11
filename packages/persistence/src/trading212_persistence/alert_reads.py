"""Bounded alert collections, current authorization and historical event membership."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Exists
from trading212_application import alerts as app
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
)
from trading212_domain.alert_serialization import decode_alert_input, decode_alert_result
from trading212_domain.alerts import (
    AlertEvaluationOutcome,
    AlertExecutionIntent,
    AlertLifecycle,
    AlertNotificationState,
    AlertResolutionReason,
    AlertSeverity,
)
from trading212_security.principals import AuthorizationError, Principal

from .alert_authorization import AlertAuthorization, authorize_alert_request
from .alert_base import AlertStore, alert_owner_lock, fail, rule_version
from .alert_models import (
    AlertAcknowledgmentModel,
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertEventTransitionModel,
    AlertInputSnapshotModel,
    AlertRuleModel,
    AlertRuleVersionModel,
    InAppNotificationModel,
    NotificationDeliveryJobModel,
    NotificationDestinationModel,
    NotificationDestinationVersionModel,
)
from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .models import CollectionQuerySnapshotMemberModel


def acknowledged(event_id: object, cutoff: datetime) -> Exists:
    return exists(
        select(AlertAcknowledgmentModel.id).where(
            AlertAcknowledgmentModel.event_id == event_id,
            AlertAcknowledgmentModel.acknowledged_at <= cutoff,
        )
    )


def resolved(event_id: object, cutoff: datetime) -> Exists:
    return exists(
        select(AlertEventTransitionModel.id).where(
            AlertEventTransitionModel.event_id == event_id,
            AlertEventTransitionModel.kind == "resolved",
            AlertEventTransitionModel.occurred_at <= cutoff,
        )
    )


class AlertReads(AlertStore):
    def _page(
        self,
        session: Session,
        authorization: AlertAuthorization,
        *,
        resource: CollectionSnapshotResource,
        filters: tuple[object, ...],
        statement: Select[tuple[UUID]],
        cursor: str | None,
        limit: int,
    ) -> CollectionSnapshotPage:
        definition = CollectionSnapshotDefinition(
            resource=resource,
            owner_id=authorization.owner_id,
            broker_account_id=authorization.account_id,
            filter_fingerprint=collection_filter_fingerprint(*filters),
        )
        collections = CollectionSnapshotStore(
            session,
            CursorCodec(self._cursor_signing_key),
            ttl_seconds=self._cursor_ttl_seconds,
            max_active_snapshots_per_owner=self._max_collections,
            max_active_members_per_owner=self._max_members,
        )
        try:
            if cursor is not None:
                return collections.resume(definition, cursor, limit=limit)
            return collections.materialize(
                definition,
                lambda: session.scalars(statement.limit(self._max_members + 1)),
                limit=limit,
            )
        except CursorValidationError:
            fail(app.AlertServiceErrorCode.CURSOR_INVALID)
        except CollectionSnapshotCapacityError:
            fail(app.AlertServiceErrorCode.RESULT_TOO_LARGE)
        raise AssertionError("unreachable")

    def _evaluation_view(
        self, session: Session, authorization: AlertAuthorization, row: AlertEvaluationModel
    ) -> app.AlertEvaluationView:
        from .alert_sources import authorize_alert_sources

        job = session.get(AlertEvaluationJobModel, row.job_id)
        assert job is not None
        reproducibility = app.AlertReproducibility.EXPIRED
        result = None
        captured = None
        version = session.get(AlertRuleVersionModel, row.rule_version_id)
        assert version is not None
        if row.purged_at is None and row.expires_at > self._now():
            try:
                authorize_alert_sources(
                    session, authorization, input_id=row.input_id, now=self._now()
                )
                payload = row.payload
                if payload is None or hashlib.sha256(payload).hexdigest() != row.content_digest:
                    fail(app.AlertServiceErrorCode.ALERTS_UNAVAILABLE)
                assert payload is not None
                snapshot = session.get(AlertInputSnapshotModel, row.input_id)
                if snapshot is None or snapshot.purged_at is not None:
                    fail(app.AlertServiceErrorCode.ALERTS_UNAVAILABLE)
                assert snapshot is not None
                input_payload = snapshot.payload
                if (
                    input_payload is None
                    or len(input_payload) != snapshot.byte_length
                    or hashlib.sha256(input_payload).hexdigest() != row.input_digest
                ):
                    fail(app.AlertServiceErrorCode.ALERTS_UNAVAILABLE)
                assert input_payload is not None
                captured = decode_alert_input(input_payload)
                result = decode_alert_result(payload)
                reproducibility = app.AlertReproducibility.RETAINED
            except AuthorizationError:
                reproducibility = app.AlertReproducibility.SOURCE_RESTRICTED
        authorization.check(session, now=self._now())
        return app.AlertEvaluationView(
            id=row.id,
            job_id=job.id,
            rule_id=job.rule_id,
            rule_version_id=row.rule_version_id,
            account_id=row.account_id,
            input_digest=row.input_digest,
            result_digest=row.content_digest,
            rule_content_digest=version.content_digest,
            definition=captured.version.definition if captured is not None else None,
            source_references=captured.source_references if captured is not None else (),
            canonical_bindings=captured.canonical_bindings if captured is not None else (),
            licenses=captured.licenses if captured is not None else (),
            scheduled_for=row.scheduled_for,
            evaluated_at=row.evaluated_at,
            outcome=AlertEvaluationOutcome(row.outcome),
            execution_intent=AlertExecutionIntent(job.execution_intent),
            result=result,
            reproducibility=reproducibility,
            expires_at=row.expires_at,
        )

    def _rule_detail(
        self,
        session: Session,
        authorization: AlertAuthorization,
        row: AlertRuleModel,
        query: app.AlertRuleDetailQuery,
    ) -> app.AlertRuleDetail:
        statement = (
            select(AlertEvaluationModel.id)
            .join(
                AlertEvaluationJobModel, AlertEvaluationJobModel.id == AlertEvaluationModel.job_id
            )
            .where(
                AlertEvaluationModel.owner_id == row.owner_id,
                AlertEvaluationJobModel.rule_id == row.id,
            )
            .order_by(AlertEvaluationModel.created_at.desc(), AlertEvaluationModel.id.desc())
        )
        ids, total, next_cursor = self._history_membership(
            session,
            authorization,
            resource=CollectionSnapshotResource.ALERT_EVALUATIONS,
            rule_id=row.id,
            statement=statement,
            cursor=query.evaluation_cursor,
            limit=query.evaluation_limit,
        )
        items = tuple(
            self._evaluation_view(session, authorization, self._evaluation_row(session, identifier))
            for identifier in ids
        )
        versions = (
            select(AlertRuleVersionModel.id)
            .where(
                AlertRuleVersionModel.rule_id == row.id,
                AlertRuleVersionModel.owner_id == row.owner_id,
            )
            .order_by(AlertRuleVersionModel.created_at.desc(), AlertRuleVersionModel.id.desc())
        )
        version_ids, version_total, version_cursor = self._history_membership(
            session,
            authorization,
            resource=CollectionSnapshotResource.ALERT_VERSIONS,
            rule_id=row.id,
            statement=versions,
            cursor=query.version_cursor,
            limit=query.version_limit,
        )
        version_values = tuple(
            rule_version(self._version(session, row, identifier)) for identifier in version_ids
        )
        newest = session.scalar(statement.limit(1))
        latest = (
            self._evaluation_view(session, authorization, self._evaluation_row(session, newest))
            if newest
            else None
        )
        return app.AlertRuleDetail(
            id=row.id,
            account_id=row.account_id,
            revision=row.revision,
            lifecycle=AlertLifecycle(row.lifecycle),
            created_at=row.created_at,
            updated_at=row.updated_at,
            latest_version=rule_version(self._version(session, row)),
            active_version=rule_version(self._version(session, row, row.active_version_id))
            if row.active_version_id
            else None,
            next_scheduled_for=row.next_scheduled_for,
            latest_evaluation=latest,
            evaluation_page=app.AlertEvaluationPage(
                items=items, total=total, limit=query.evaluation_limit, next_cursor=next_cursor
            ),
            version_page=app.AlertRuleVersionPage(
                items=version_values,
                total=version_total,
                limit=query.version_limit,
                next_cursor=version_cursor,
            ),
        )

    def _history_membership(
        self,
        session: Session,
        authorization: AlertAuthorization,
        *,
        resource: CollectionSnapshotResource,
        rule_id: UUID,
        statement: Select[tuple[UUID]],
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[UUID, ...], int, str | None]:
        if cursor is None:
            # A fully returned small history needs no durable continuation or capacity slot.
            ids = tuple(session.scalars(statement.limit(limit + 1)))
            if len(ids) <= limit:
                return ids, len(ids), None
        page = self._page(
            session,
            authorization,
            resource=resource,
            filters=(str(rule_id),),
            statement=statement,
            cursor=cursor,
            limit=limit,
        )
        return page.record_ids, page.exact_total, page.next_cursor

    @staticmethod
    def _evaluation_row(session: Session, identifier: UUID) -> AlertEvaluationModel:
        row = session.get(AlertEvaluationModel, identifier)
        if row is None:
            fail(app.AlertServiceErrorCode.NOT_FOUND)
        assert row is not None
        return row

    async def get_rule(
        self, principal: Principal, rule_id: UUID, *, query: app.AlertRuleDetailQuery
    ) -> app.AlertRuleDetail:
        def execute() -> app.AlertRuleDetail:
            with self._sessions() as session, session.begin():
                row, authorization = self._rule(session, principal, rule_id)
                return self._rule_detail(session, authorization, row, query)

        return await self._run(execute)

    async def list_rules(
        self, principal: Principal, *, query: app.AlertRuleListQuery
    ) -> app.AlertRulePage:
        def execute() -> app.AlertRulePage:
            with self._sessions() as session, session.begin():
                authorization = authorize_alert_request(
                    session, principal, account_id=query.account_id, now=self._now()
                )
                alert_owner_lock(session, authorization.owner_id)
                statement = select(AlertRuleModel.id).where(
                    AlertRuleModel.owner_id == authorization.owner_id,
                    AlertRuleModel.account_id == query.account_id,
                )
                if query.state is not None:
                    statement = statement.where(AlertRuleModel.lifecycle == query.state.value)
                if query.family is not None:
                    statement = statement.join(
                        AlertRuleVersionModel,
                        AlertRuleVersionModel.id == AlertRuleModel.latest_version_id,
                    ).where(AlertRuleVersionModel.family == query.family.value)
                page = self._page(
                    session,
                    authorization,
                    resource=CollectionSnapshotResource.ALERT_RULES,
                    filters=(
                        query.state.value if query.state else None,
                        query.family.value if query.family else None,
                    ),
                    statement=statement.order_by(
                        AlertRuleModel.created_at.desc(), AlertRuleModel.id.desc()
                    ),
                    cursor=query.cursor,
                    limit=query.limit,
                )
                items = []
                for identifier in page.record_ids:
                    row = session.get(AlertRuleModel, identifier)
                    assert row is not None
                    items.append(
                        self._rule_detail(session, authorization, row, app.AlertRuleDetailQuery())
                    )
                return app.AlertRulePage(
                    items=tuple(items),
                    total=page.exact_total,
                    limit=page.limit,
                    next_cursor=page.next_cursor,
                )

        return await self._run(execute)

    def _ack_view(self, row: AlertAcknowledgmentModel, revision: int) -> app.AlertAcknowledgment:
        return app.AlertAcknowledgment(
            id=row.id,
            event_id=row.event_id,
            principal_id=row.principal_id,
            acknowledged_at=row.acknowledged_at,
            event_revision=revision,
            note=row.note,
        )

    def _event_detail(
        self,
        session: Session,
        authorization: AlertAuthorization,
        row: AlertEventModel,
        *,
        cutoff: datetime | None = None,
    ) -> app.AlertEventDetail:
        cutoff = cutoff or self._now()
        evaluation = self._evaluation_row(session, row.evaluation_id)
        notification = session.scalar(
            select(InAppNotificationModel).where(InAppNotificationModel.event_id == row.id)
        )
        assert notification is not None
        ack = session.scalar(
            select(AlertAcknowledgmentModel)
            .where(
                AlertAcknowledgmentModel.event_id == row.id,
                AlertAcknowledgmentModel.acknowledged_at <= cutoff,
            )
            .order_by(
                AlertAcknowledgmentModel.acknowledged_at.desc(), AlertAcknowledgmentModel.id.desc()
            )
            .limit(1)
        )
        transitions = tuple(
            session.scalars(
                select(AlertEventTransitionModel)
                .where(
                    AlertEventTransitionModel.event_id == row.id,
                    AlertEventTransitionModel.occurred_at <= cutoff,
                )
                .order_by(AlertEventTransitionModel.sequence)
            )
        )
        resolution = next((t for t in reversed(transitions) if t.kind == "resolved"), None)
        external = []
        for job, destination in session.execute(
            select(NotificationDeliveryJobModel, NotificationDestinationVersionModel)
            .join(
                NotificationDestinationVersionModel,
                NotificationDeliveryJobModel.destination_version_id
                == NotificationDestinationVersionModel.id,
            )
            .where(NotificationDeliveryJobModel.event_id == row.id)
            .order_by(NotificationDeliveryJobModel.id)
        ):
            state = (
                "unavailable"
                if job.failure_code == "not_configured"
                else "cancelled"
                if job.state == "expired"
                else job.state
            )
            external.append(
                app.AlertDeliveryView(
                    id=job.id,
                    destination_id=destination.destination_id,
                    destination_version_id=destination.id,
                    channel=app.NotificationChannel(job.channel),
                    state=app.AlertDeliveryState(state),
                    attempts=job.consumer_attempts,
                    reason=job.failure_code,
                )
            )
        version = session.get(AlertRuleVersionModel, row.rule_version_id)
        assert version is not None
        return app.AlertEventDetail(
            id=row.id,
            account_id=row.account_id,
            rule_id=row.rule_id,
            rule_version_id=row.rule_version_id,
            evaluation_id=row.evaluation_id,
            revision=row.revision,
            deduplication_digest=row.dedup_digest,
            severity=AlertSeverity(row.severity),
            episode_state=app.AlertEventState.RESOLVED if resolution else app.AlertEventState.OPEN,
            occurred_at=row.occurred_at,
            recorded_at=row.created_at,
            updated_at=transitions[-1].occurred_at if transitions else row.created_at,
            evaluation=self._evaluation_view(session, authorization, evaluation),
            delivery=app.AlertDeliverySummary(
                in_app_notification_id=notification.id,
                created_at=notification.created_at,
                notification_state=AlertNotificationState(row.notification_state),
                external=tuple(external),
            ),
            acknowledgment=self._ack_view(ack, row.revision) if ack else None,
            resolved_at=resolution.occurred_at if resolution else None,
            resolution_reason=AlertResolutionReason(resolution.reason)
            if resolution and resolution.reason
            else None,
            correction_of=row.correction_of_id,
            episode_ordinal=row.episode_ordinal,
            remediation=rule_version(version).definition.remediation,
        )

    def _event(
        self, session: Session, principal: Principal, event_id: UUID, *, write: bool = False
    ) -> tuple[AlertEventModel, AlertAuthorization]:
        owner = UUID(principal.owner_id)
        alert_owner_lock(session, owner)
        row = session.scalar(
            select(AlertEventModel)
            .where(AlertEventModel.id == event_id, AlertEventModel.owner_id == owner)
            .with_for_update()
        )
        if row is None:
            fail(app.AlertServiceErrorCode.NOT_FOUND)
        assert row is not None
        authorization = authorize_alert_request(
            session, principal, account_id=row.account_id, now=self._now(), write=write
        )
        return row, authorization

    async def get_event(self, principal: Principal, event_id: UUID) -> app.AlertEventDetail:
        def execute() -> app.AlertEventDetail:
            with self._sessions() as session, session.begin():
                row, authorization = self._event(session, principal, event_id)
                return self._event_detail(session, authorization, row)

        return await self._run(execute)

    def _event_statement(
        self,
        authorization: AlertAuthorization,
        *,
        cutoff: datetime,
        state: app.AlertStateFilter,
        severity: app.AlertSeverityFilter,
        rule_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Select[tuple[UUID]]:
        statement = select(AlertEventModel.id).where(
            AlertEventModel.owner_id == authorization.owner_id,
            AlertEventModel.account_id == authorization.account_id,
            AlertEventModel.created_at <= cutoff,
        )
        if rule_id:
            statement = statement.where(AlertEventModel.rule_id == rule_id)
        if severity is not app.AlertSeverityFilter.ALL:
            statement = statement.where(AlertEventModel.severity == severity.value)
        if state is app.AlertStateFilter.OPEN:
            statement = statement.where(~resolved(AlertEventModel.id, cutoff))
        elif state is app.AlertStateFilter.RESOLVED:
            statement = statement.where(resolved(AlertEventModel.id, cutoff))
        elif state is app.AlertStateFilter.ACKNOWLEDGED:
            statement = statement.where(acknowledged(AlertEventModel.id, cutoff))
        if start is not None and end is not None:
            statement = statement.where(
                AlertEventModel.occurred_at >= start, AlertEventModel.occurred_at < end
            )
        return statement.order_by(AlertEventModel.created_at.desc(), AlertEventModel.id.desc())

    def _counts(
        self, session: Session, statement: Select[tuple[UUID]], cutoff: datetime
    ) -> app.AlertSummaryCounts:
        ids = statement.order_by(None).subquery()
        total = session.scalar(select(func.count()).select_from(ids)) or 0
        closed = (
            session.scalar(select(func.count()).select_from(ids).where(resolved(ids.c.id, cutoff)))
            or 0
        )
        ack = (
            session.scalar(
                select(func.count()).select_from(ids).where(acknowledged(ids.c.id, cutoff))
            )
            or 0
        )
        return app.AlertSummaryCounts(
            total_count=total,
            open_count=total - closed,
            resolved_count=closed,
            acknowledged_count=ack,
        )

    async def list_events(
        self, principal: Principal, *, query: app.AlertEventListQuery
    ) -> app.AlertEventPage:
        def execute() -> app.AlertEventPage:
            with self._sessions() as session, session.begin():
                authorization = authorize_alert_request(
                    session, principal, account_id=query.account_id, now=self._now()
                )
                alert_owner_lock(session, authorization.owner_id)
                statement = self._event_statement(
                    authorization,
                    cutoff=self._now(),
                    state=query.state,
                    severity=query.severity,
                    rule_id=query.rule_id,
                    start=datetime.combine(query.start_date, time.min, UTC)
                    if query.start_date
                    else None,
                    end=datetime.combine(query.end_date + timedelta(days=1), time.min, UTC)
                    if query.end_date
                    else None,
                )
                page = self._page(
                    session,
                    authorization,
                    resource=CollectionSnapshotResource.ALERT_EVENTS,
                    filters=(
                        str(query.rule_id),
                        query.state.value,
                        query.severity.value,
                        str(query.start_date),
                        str(query.end_date),
                    ),
                    statement=statement,
                    cursor=query.cursor,
                    limit=query.limit,
                )
                return self._event_page(session, authorization, page)

        return await self._run(execute)

    def _event_page(
        self,
        session: Session,
        authorization: AlertAuthorization,
        page: CollectionSnapshotPage,
        *,
        cutoff: datetime | None = None,
    ) -> app.AlertEventPage:
        items = []
        for identifier in page.record_ids:
            row = session.get(AlertEventModel, identifier)
            assert row is not None
            items.append(self._event_detail(session, authorization, row, cutoff=cutoff))
        return app.AlertEventPage(
            items=tuple(items),
            total=page.exact_total,
            limit=page.limit,
            next_cursor=page.next_cursor,
        )

    async def get_summary(
        self,
        principal: Principal,
        account_id: UUID,
        *,
        query: app.AlertSummaryTopQuery | app.AlertSummaryWindowQuery,
    ) -> app.AlertSummary | app.AlertSummaryPage:
        def execute() -> app.AlertSummary | app.AlertSummaryPage:
            with self._sessions() as session, session.begin():
                authorization = authorize_alert_request(
                    session, principal, account_id=account_id, now=self._now()
                )
                alert_owner_lock(session, authorization.owner_id)
                cutoff = (
                    query.source_cutoff_at
                    if isinstance(query, app.AlertSummaryWindowQuery)
                    else self._now()
                )
                if cutoff > self._now():
                    fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
                statement = self._event_statement(
                    authorization,
                    cutoff=cutoff,
                    state=query.state,
                    severity=query.severity,
                    start=datetime.combine(query.start_date, time.min, UTC)
                    if isinstance(query, app.AlertSummaryWindowQuery)
                    else None,
                    end=datetime.combine(query.end_date + timedelta(days=1), time.min, UTC)
                    if isinstance(query, app.AlertSummaryWindowQuery)
                    else None,
                )
                if isinstance(query, app.AlertSummaryTopQuery):
                    counts = self._counts(session, statement, cutoff)
                    top_items = []
                    for identifier in session.scalars(statement.limit(query.top_n)):
                        event = session.get(AlertEventModel, identifier)
                        assert event is not None
                        top_items.append(
                            self._event_detail(session, authorization, event, cutoff=cutoff)
                        )
                    items = tuple(top_items)
                    return app.AlertSummary(
                        account_id=account_id,
                        source_cutoff_at=cutoff,
                        counts=counts,
                        items=items,
                        top_n=query.top_n,
                        returned_count=len(items),
                        omitted_count=counts.total_count - len(items),
                    )
                page = self._page(
                    session,
                    authorization,
                    resource=CollectionSnapshotResource.ALERT_EVENTS,
                    filters=(
                        "window",
                        query.start_date.isoformat(),
                        query.end_date.isoformat(),
                        cutoff.isoformat(),
                        query.state.value,
                        query.severity.value,
                    ),
                    statement=statement,
                    cursor=query.cursor,
                    limit=query.limit,
                )
                membership = select(CollectionQuerySnapshotMemberModel.record_id.label("id")).where(
                    CollectionQuerySnapshotMemberModel.snapshot_id == page.snapshot_id
                )
                counts = self._counts(session, membership, cutoff)
                return app.AlertSummaryPage(
                    account_id=account_id,
                    source_cutoff_at=cutoff,
                    counts=counts,
                    page=self._event_page(session, authorization, page, cutoff=cutoff),
                )

        return await self._run(execute)

    async def list_notification_destinations(
        self, principal: Principal, account_id: UUID, *, query: app.AlertPageQuery
    ) -> app.NotificationDestinationPage:
        def execute() -> app.NotificationDestinationPage:
            with self._sessions() as session, session.begin():
                authorization = authorize_alert_request(
                    session, principal, account_id=account_id, now=self._now()
                )
                alert_owner_lock(session, authorization.owner_id)
                statement = (
                    select(NotificationDestinationModel.id)
                    .where(
                        NotificationDestinationModel.owner_id == authorization.owner_id,
                        NotificationDestinationModel.account_id == account_id,
                    )
                    .order_by(
                        NotificationDestinationModel.created_at.desc(),
                        NotificationDestinationModel.id.desc(),
                    )
                )
                page = self._page(
                    session,
                    authorization,
                    resource=CollectionSnapshotResource.NOTIFICATION_DESTINATIONS,
                    filters=(),
                    statement=statement,
                    cursor=query.cursor,
                    limit=query.limit,
                )
                items = []
                for identifier in page.record_ids:
                    row = session.get(NotificationDestinationModel, identifier)
                    assert row is not None
                    version = session.get(
                        NotificationDestinationVersionModel, row.current_version_id
                    )
                    assert version is not None
                    items.append(
                        app.NotificationDestination(
                            id=row.id,
                            channel=app.NotificationChannel(version.channel),
                            label=version.label,
                            state=app.NotificationDestinationState(row.state),
                        )
                    )
                return app.NotificationDestinationPage(
                    items=tuple(items),
                    total=page.exact_total,
                    limit=page.limit,
                    next_cursor=page.next_cursor,
                )

        return await self._run(execute)
