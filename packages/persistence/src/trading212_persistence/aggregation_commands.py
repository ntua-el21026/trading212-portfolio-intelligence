"""Semantic replay and complete atomic synchronous aggregate publication."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session, undefer
from trading212_analytics.aggregation import calculate_aggregate_activity, calculate_aggregation
from trading212_application import aggregation as app
from trading212_domain.aggregation_codec import (
    aggregation_record_bytes,
    aggregation_record_digest,
    aggregation_selection_from_json,
)
from trading212_domain.serialization import canonical_json

from . import aggregation_models as m
from .aggregation_activity_capture import capture_activity
from .aggregation_authorization import AggregateAuthorization
from .aggregation_capture import capture_holdings
from .aggregation_publication import publish_aggregate
from .aggregation_retained import read_retained_aggregate
from .premium_models import PremiumCapacityModel
from .report_models import ApplicationCommandIdentityModel


def selection_view(
    session: Session, auth: AggregateAuthorization, root: m.AggregateSelectionModel
) -> app.AggregateSelectionView:
    row = session.scalar(
        select(m.AggregateSelectionPayloadModel)
        .options(undefer("*"))
        .where(
            m.AggregateSelectionPayloadModel.owner_id == auth.owner_id,
            m.AggregateSelectionPayloadModel.selection_id == root.id,
        )
    )
    if row is None:
        raise app.AggregateServiceError(app.AggregateErrorCode.NOT_FOUND)
    return selection_from_payload(auth, root, row.payload)


def selection_from_payload(
    auth: AggregateAuthorization, root: m.AggregateSelectionModel, payload: bytes
) -> app.AggregateSelectionView:
    content = aggregation_selection_from_json(payload, expected_digest=root.content_digest)
    if (
        root.owner_id != auth.owner_id
        or not root.sealed
        or not set(x.account_id for x in content.members) <= set(auth.account_ids)
        or len(content.members) != root.member_count
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.ACCESS_DENIED)
    return app.AggregateSelectionView(
        selection_id=root.id,
        content=content,
        content_digest=root.content_digest,
        revision=root.revision,
        created_at=root.created_at,
    )


def receipt(
    root: m.AggregateRunModel, now: datetime, *, unavailable: bool = False
) -> app.AggregateRunReceipt:
    if not root.sealed or root.holdings_input_digest is None or root.holdings_result_digest is None:
        raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
    return app.AggregateRunReceipt(
        run_id=root.id,
        selection_id=root.selection_id,
        selection_revision=root.selection_revision,
        holdings_input_digest=root.holdings_input_digest,
        holdings_result_digest=root.holdings_result_digest,
        activity_input_digest=root.activity_input_digest,
        activity_result_digest=root.activity_result_digest,
        activity_requested=root.activity_requested,
        state="expired" if root.expires_at <= now or unavailable else "succeeded",
        created_at=root.created_at,
        expires_at=root.expires_at,
    )


def _prior(
    session: Session, auth: AggregateAuthorization, name: str, key: str, digest: str
) -> ApplicationCommandIdentityModel | None:
    row = session.scalar(
        select(ApplicationCommandIdentityModel).where(
            ApplicationCommandIdentityModel.owner_id == auth.owner_id,
            ApplicationCommandIdentityModel.command == name,
            ApplicationCommandIdentityModel.idempotency_key == key,
        )
    )
    if row is not None and (row.account_id != auth.account_ids[0] or row.command_digest != digest):
        raise app.AggregateServiceError(app.AggregateErrorCode.CONFLICT)
    return row


def _record(
    session: Session,
    auth: AggregateAuthorization,
    name: str,
    key: str,
    digest: str,
    resource: UUID,
    correlation: str,
    now: datetime,
) -> UUID:
    identity = ApplicationCommandIdentityModel(
        id=uuid4(),
        owner_id=auth.owner_id,
        account_id=auth.account_ids[0],
        command=name,
        idempotency_key=key,
        command_digest=digest,
        premium_resource_id=resource,
        premium_actor_id=auth.principal_id,
        premium_correlation_id=correlation,
        report_job_id=None,
        export_job_id=None,
        created_at=now,
    )
    session.add(identity)
    session.flush()
    return identity.id


def _admit(
    session: Session, auth: AggregateAuthorization, *, payload_bytes: int, selection: bool
) -> None:
    capacity = session.scalar(
        select(PremiumCapacityModel)
        .where(PremiumCapacityModel.owner_id == auth.owner_id)
        .with_for_update()
    )
    if capacity is not None and (
        capacity.reserved_bytes + capacity.retained_bytes + payload_bytes > 268435456
        or (not selection and capacity.active_jobs >= 2)
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.RATE_LIMITED)
    if selection:
        actual = session.scalar(
            text(
                "SELECT (SELECT count(*) FROM risk_definition_versions WHERE "
                "owner_id=:owner)+(SELECT count(*) FROM "
                "scenario_definition_versions WHERE owner_id=:owner)+(SELECT "
                "count(*) FROM assumption_versions WHERE owner_id=:owner)+(SELECT "
                "count(*) FROM goal_versions WHERE owner_id=:owner)+(SELECT "
                "count(*) FROM research_note_revisions WHERE "
                "owner_id=:owner)+(SELECT count(*) FROM aggregate_selections "
                "WHERE owner_id=:owner)"
            ),
            {"owner": auth.owner_id},
        )
        if max(actual or 0, 0 if capacity is None else capacity.definition_versions) >= 512:
            raise app.AggregateServiceError(app.AggregateErrorCode.RATE_LIMITED)


def create_selection(
    session: Session,
    auth: AggregateAuthorization,
    command: app.CreateAggregateSelection,
    *,
    clock: Callable[[], datetime],
    check: Callable[[], None],
) -> app.AggregateSelectionView:
    check()
    payload = aggregation_record_bytes(command.content)
    digest = aggregation_record_digest(command.content)
    identity = _prior(
        session, auth, "aggregate.selection.create.v1", command.idempotency_key, digest
    )
    if identity is not None:
        root = session.scalar(
            select(m.AggregateSelectionModel).where(
                m.AggregateSelectionModel.owner_id == auth.owner_id,
                m.AggregateSelectionModel.id == identity.premium_resource_id,
                m.AggregateSelectionModel.command_id == identity.id,
            )
        )
        if root is None:
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        return selection_view(session, auth, root)
    _admit(session, auth, payload_bytes=len(payload), selection=True)
    at = clock()
    identifier = uuid4()
    command_id = _record(
        session,
        auth,
        "aggregate.selection.create.v1",
        command.idempotency_key,
        digest,
        identifier,
        command.correlation_id,
        at,
    )
    root = m.AggregateSelectionModel(
        id=identifier,
        owner_id=auth.owner_id,
        actor_id=auth.principal_id,
        command_id=command_id,
        content_digest=digest,
        revision=1,
        member_count=len(command.content.members),
        reporting_currency=str(command.content.reporting_currency),
        source_cutoff_at=command.content.source_cutoff_at,
        identity_policy=command.content.economic_identity_policy,
        sealed=False,
        created_at=at,
    )
    session.add(root)
    session.flush()
    for ordinal, member in enumerate(command.content.members):
        session.add(
            m.AggregateMemberModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                selection_id=identifier,
                ordinal=ordinal,
                account_id=member.account_id,
                snapshot_id=member.portfolio_snapshot_id,
                created_at=at,
            )
        )
    session.add(
        m.AggregateSelectionPayloadModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            selection_id=identifier,
            payload=payload,
            created_at=at,
        )
    )
    session.flush()
    check()
    auth.finish(session, now=clock())
    root.sealed = True
    session.flush()
    return selection_from_payload(auth, root, payload)


def create_run(
    session: Session,
    auth: AggregateAuthorization,
    selected: m.AggregateSelectionModel,
    command: app.CreateAggregateRun,
    *,
    clock: Callable[[], datetime],
    check: Callable[[], None],
) -> app.AggregateRunReceipt:
    content = selection_view(session, auth, selected).content
    semantic = sha256(
        canonical_json(
            {
                "selection": selected.id,
                "selection_digest": selected.content_digest,
                "members": tuple((x.account_id, x.portfolio_snapshot_id) for x in content.members),
                "revision": command.expected_revision,
                "fx": tuple(
                    (x.account_id, str(x.currency), x.fx_observation_id)
                    for x in command.fx_bindings
                ),
                "window": None
                if command.activity_window is None
                else (command.activity_window.start_at, command.activity_window.end_at),
            }
        ).encode()
    ).hexdigest()
    prior = _prior(session, auth, "aggregate.run.create.v1", command.idempotency_key, semantic)
    if prior is not None:
        root = session.scalar(
            select(m.AggregateRunModel).where(
                m.AggregateRunModel.owner_id == auth.owner_id,
                m.AggregateRunModel.id == prior.premium_resource_id,
                m.AggregateRunModel.command_id == prior.id,
            )
        )
        if root is None:
            raise app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)
        # Replays disclose no previously permitted source without current authority.
        read_retained_aggregate(
            session,
            auth,
            root,
            include_activity=root.activity_requested,
            required_copy_use=None,
            clock=clock,
            check_deadline=check,
        )
        return receipt(root, clock())
    if selected.revision != command.expected_revision:
        raise app.AggregateServiceError(app.AggregateErrorCode.REVISION_MISMATCH)
    if (
        command.activity_window is not None
        and command.activity_window.end_at > content.source_cutoff_at
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.VALIDATION_FAILED)
    _admit(session, auth, payload_bytes=33554432, selection=False)
    at = clock()
    identifier = uuid4()
    command_id = _record(
        session,
        auth,
        "aggregate.run.create.v1",
        command.idempotency_key,
        semantic,
        identifier,
        command.correlation_id,
        at,
    )
    root = m.AggregateRunModel(
        id=identifier,
        owner_id=auth.owner_id,
        selection_id=selected.id,
        selection_revision=selected.revision + 1,
        command_id=command_id,
        actor_id=auth.principal_id,
        holdings_input_digest=None,
        holdings_result_digest=None,
        activity_input_digest=None,
        activity_result_digest=None,
        activity_requested=command.activity_window is not None,
        activity_start_at=None
        if command.activity_window is None
        else command.activity_window.start_at,
        activity_end_at=None if command.activity_window is None else command.activity_window.end_at,
        expires_at=at + timedelta(days=30),
        completed_at=None,
        sealed=False,
        reserved_bytes=33554432,
        retained_bytes=0,
        financial_rows=0,
        created_at=at,
    )
    session.add(root)
    session.flush()
    captured = capture_holdings(
        session, auth, content, command.fx_bindings, now=clock(), check_deadline=check
    )
    result = calculate_aggregation(captured.value, check_deadline=check)
    activity = None
    activity_result = None
    if command.activity_window is not None:
        if any(
            command.activity_window.end_at > pin.source_cutoff_at
            for pin in captured.value.snapshots
        ):
            raise app.AggregateServiceError(app.AggregateErrorCode.VALIDATION_FAILED)
        activity = capture_activity(
            session,
            auth,
            holdings_input_digest=aggregation_record_digest(captured.value),
            window=command.activity_window,
            cutoff=content.source_cutoff_at,
            now=clock(),
            check_deadline=check,
        )
        activity_result = calculate_aggregate_activity(activity.value, check_deadline=check)
    deadlines = tuple(
        x
        for x in (
            captured.authority.deadline,
            None if activity is None else activity.authority.deadline,
        )
        if x is not None
    )
    if deadlines:
        root.expires_at = min(root.expires_at, *deadlines)
    session.flush()
    publish_aggregate(
        session,
        auth,
        root,
        holdings_input=captured.value,
        holdings_result=result,
        activity_input=None if activity is None else activity.value,
        activity_result=activity_result,
        now=clock(),
        check_deadline=check,
    )
    captured.authority.finish(session, auth, now=clock(), expires_at=root.expires_at)
    if activity is not None:
        activity.authority.finish(session, auth, now=clock(), expires_at=root.expires_at)
    auth.finish(session, now=clock())
    check()
    # Row-cost triggers own reservation conversion. Refresh after all financial
    # child inserts, so sealing releases only the actual remaining reservation.
    session.refresh(root)
    root.reserved_bytes = 0
    root.completed_at = clock()
    root.sealed = True
    selected.revision += 1
    session.flush()
    check()
    return receipt(root, clock())
