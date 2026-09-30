"""Whole-row saved aggregate pages; no full result decode for a small web page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session
from trading212_application import aggregation as app
from trading212_application import aggregation_views as views
from trading212_application.queries import CursorCodec, CursorValidationError, cursor_binding
from trading212_application.views import Page
from trading212_domain import aggregation_codec as codec
from trading212_domain.aggregation import AggregateReason
from trading212_domain.serialization import canonical_json
from trading212_security.principals import Principal

from . import aggregation_models as m
from .aggregation_authorization import AggregateAuthorization, authorize_aggregate_members
from .aggregation_commands import receipt, selection_from_payload
from .aggregation_sources import authorize_aggregate_sources


def _unavailable() -> app.AggregateServiceError:
    return app.AggregateServiceError(app.AggregateErrorCode.SOURCE_UNAVAILABLE)


def list_selections(
    session: Session,
    principal: Principal,
    owner: UUID,
    query: app.AggregatePageQuery,
    *,
    cursors: CursorCodec,
    clock: Callable[[], datetime],
    check: Callable[[], None],
) -> Page[app.AggregateSelectionView]:
    roots = tuple(
        session.scalars(
            select(m.AggregateSelectionModel)
            .where(m.AggregateSelectionModel.owner_id == owner, m.AggregateSelectionModel.sealed)
            .order_by(m.AggregateSelectionModel.created_at, m.AggregateSelectionModel.id)
            .limit(513)
        )
    )
    if len(roots) > 512:
        raise _unavailable()
    cohort = sha256(canonical_json(tuple(x.id for x in roots)).encode()).hexdigest()
    binding = cursor_binding(
        owner, principal.issuer, principal.subject, "aggregate-selections", cohort, query.limit
    )
    at = clock()
    offset = 0
    if query.cursor is not None:
        at, key = cursors.decode(
            query.cursor, resource="aggregate-selections", binding=binding, key_size=1
        )
        try:
            offset = int(key[0])
        except ValueError:
            raise CursorValidationError("invalid cursor") from None
        if str(offset) != key[0] or not 0 < offset < len(roots):
            raise CursorValidationError("invalid cursor")
    chosen = roots[offset : offset + query.limit]
    ids = tuple(x.id for x in chosen)
    members = tuple(
        session.execute(
            select(m.AggregateMemberModel.selection_id, m.AggregateMemberModel.account_id)
            .where(
                m.AggregateMemberModel.owner_id == owner,
                m.AggregateMemberModel.selection_id.in_(ids),
            )
            .order_by(m.AggregateMemberModel.selection_id, m.AggregateMemberModel.ordinal)
        ).all()
    )
    auth = authorize_aggregate_members(
        session, principal, tuple(sorted({row[1] for row in members})), now=clock()
    )
    if any(sum(row[0] == root.id for row in members) != root.member_count for root in chosen):
        raise _unavailable()
    payloads: dict[UUID, bytes] = dict(
        session.execute(
            select(
                m.AggregateSelectionPayloadModel.selection_id,
                m.AggregateSelectionPayloadModel.payload,
            ).where(
                m.AggregateSelectionPayloadModel.owner_id == owner,
                m.AggregateSelectionPayloadModel.selection_id.in_(ids),
            )
        )
        .tuples()
        .all()
    )
    if set(payloads) != set(ids):
        raise _unavailable()
    result = tuple(selection_from_payload(auth, root, payloads[root.id]) for root in chosen)
    auth.finish(session, now=clock())
    check()
    next_offset = offset + len(chosen)
    next_cursor = (
        None
        if next_offset == len(roots)
        else cursors.encode(
            resource="aggregate-selections",
            binding=binding,
            read_cutoff=at,
            key=(str(next_offset),),
        )
    )
    return Page(items=result, next_cursor=next_cursor, limit=query.limit, total=len(roots))


def list_runs(
    session: Session,
    auth: AggregateAuthorization,
    selected: m.AggregateSelectionModel,
    query: app.AggregatePageQuery,
    *,
    cursors: CursorCodec,
    clock: Callable[[], datetime],
) -> Page[app.AggregateRunReceipt]:
    binding = cursor_binding(
        auth.owner_id,
        auth.principal_id,
        auth.fingerprint,
        selected.id,
        selected.content_digest,
        query.limit,
    )
    maximum, after, at = selected.revision, 1, clock()
    if query.cursor is not None:
        at, key = cursors.decode(
            query.cursor, resource="aggregate-runs", binding=binding, key_size=2
        )
        try:
            maximum, after = map(int, key)
        except ValueError:
            raise CursorValidationError("invalid cursor") from None
        if key != (str(maximum), str(after)) or not 1 < after < maximum <= selected.revision:
            raise CursorValidationError("invalid cursor")
    # Revisions are immutable and contiguous; the pinned maximum freezes exact
    # membership even when multiple runs have identical application timestamps.
    rows = session.execute(
        select(m.AggregateRunModel, m.AggregateRetentionModel.id)
        .outerjoin(
            m.AggregateRetentionModel,
            (m.AggregateRetentionModel.owner_id == m.AggregateRunModel.owner_id)
            & (m.AggregateRetentionModel.run_id == m.AggregateRunModel.id),
        )
        .where(
            m.AggregateRunModel.owner_id == auth.owner_id,
            m.AggregateRunModel.selection_id == selected.id,
            m.AggregateRunModel.sealed,
            m.AggregateRunModel.selection_revision > after,
            m.AggregateRunModel.selection_revision <= maximum,
        )
        .order_by(m.AggregateRunModel.selection_revision)
        .limit(query.limit + 1)
    ).all()
    page = rows[: query.limit]
    more = len(rows) > query.limit
    token = (
        None
        if not more
        else cursors.encode(
            resource="aggregate-runs",
            binding=binding,
            read_cutoff=at,
            key=(str(maximum), str(page[-1][0].selection_revision)),
        )
    )
    return Page(
        items=tuple(
            receipt(root, clock(), unavailable=marker is not None) for root, marker in page
        ),
        next_cursor=token,
        limit=query.limit,
        total=maximum - 1,
    )


def get_run_page(
    session: Session,
    auth: AggregateAuthorization,
    selected: m.AggregateSelectionModel,
    root: m.AggregateRunModel,
    query: app.AggregateRunQuery,
    *,
    cursors: CursorCodec,
    clock: Callable[[], datetime],
    check: Callable[[], None],
) -> views.AggregateRunPage:
    check()
    view = query.view.value
    # Metadata arrays contain only authority-bearing FX/evidence parent IDs, never
    # the potentially much larger source-record/projection payload inventory.
    metadata = session.execute(
        text(
            "\n"
            "      SELECT EXISTS(SELECT 1 FROM aggregate_retention_work WHERE "
            "owner_id=:owner AND run_id=:run),\n"
            "       ARRAY(SELECT DISTINCT source_id FROM aggregate_sources "
            "WHERE owner_id=:owner AND run_id=:run AND source_kind='fx'),\n"
            "       ARRAY(SELECT DISTINCT source_id FROM aggregate_sources "
            "WHERE owner_id=:owner AND run_id=:run AND "
            "source_kind='coverage_parent' AND :activity)\n"
            "    "
        ),
        {"owner": auth.owner_id, "run": root.id, "activity": view == "transfers"},
    ).one()
    public = receipt(root, clock(), unavailable=metadata[0])
    if public.state == "expired":
        return views.AggregateRunPage(
            run=public,
            page=None,
            view_digest=sha256(
                canonical_json((public.run_id, view, "expired")).encode()
            ).hexdigest(),
        )
    authority = authorize_aggregate_sources(
        session,
        auth,
        fx_ids=tuple(metadata[1]),
        evidence_ids=tuple(metadata[2]),
        cutoff=selected.source_cutoff_at,
        now=clock(),
    )
    if authority.deadline is not None and root.expires_at > authority.deadline:
        raise _unavailable()
    binding = cursor_binding(
        auth.owner_id,
        auth.principal_id,
        auth.fingerprint,
        root.id,
        view,
        root.holdings_input_digest,
        root.holdings_result_digest,
        root.activity_result_digest if view == "transfers" else None,
        authority.fingerprint,
        query.limit,
    )
    offset, at = 0, clock()
    if query.cursor is not None:
        at, key = cursors.decode(
            query.cursor, resource="aggregate-run", binding=binding, key_size=1
        )
        try:
            offset = int(key[0])
        except ValueError:
            raise CursorValidationError("invalid cursor") from None
        if str(offset) != key[0] or not 0 < offset < 10256:
            raise CursorValidationError("invalid cursor")
    page: (
        views.AggregateHoldingPage
        | views.AggregateComponentPage
        | views.AggregateAccountPage
        | views.AggregateTransferPage
    )
    if view == "transfers":
        page = _transfers(session, auth, root, query.limit, offset, cursors, binding, at)
    else:
        page = _holdings(session, auth, root, view, query.limit, offset, cursors, binding, at)
    check()
    authority.finish(session, auth, now=clock(), expires_at=root.expires_at)
    if len(canonical_json(page).encode()) > 2097152 - 8192:
        # Whole rows are never silently truncated to meet transport limits.
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    return views.AggregateRunPage(
        run=public,
        page=page,
        view_digest=sha256(canonical_json((public, page)).encode()).hexdigest(),
    )


def _next(
    cursors: CursorCodec, binding: str, at: datetime, offset: int, count: int, total: int
) -> str | None:
    if offset >= total and offset != 0:
        raise CursorValidationError("invalid cursor")
    return (
        None
        if offset + count == total
        else cursors.encode(
            resource="aggregate-run", binding=binding, read_cutoff=at, key=(str(offset + count),)
        )
    )


def _holdings(
    session: Session,
    auth: AggregateAuthorization,
    root: m.AggregateRunModel,
    view: str,
    limit: int,
    offset: int,
    cursors: CursorCodec,
    binding: str,
    at: datetime,
) -> views.AggregateHoldingPage | views.AggregateComponentPage | views.AggregateAccountPage:
    saved = session.execute(
        select(
            m.AggregateHoldingsPayloadModel.summary_payload,
            m.AggregateHoldingsPayloadModel.summary_digest,
        ).where(
            m.AggregateHoldingsPayloadModel.owner_id == auth.owner_id,
            m.AggregateHoldingsPayloadModel.run_id == root.id,
            func.octet_length(m.AggregateHoldingsPayloadModel.summary_payload) <= 1048576,
        )
    ).one_or_none()
    if saved is None:
        raise _unavailable()
    summary = codec.aggregation_holdings_summary_from_json(saved[0], expected_digest=saved[1])
    if summary.input_digest != root.holdings_input_digest or root.holdings_result_digest is None:
        raise _unavailable()
    context = views.AggregateHoldingsContext(
        input_digest=summary.input_digest,
        result_digest=root.holdings_result_digest,
        reporting_currency=summary.reporting_currency,
        source_cutoff_at=summary.source_cutoff_at,
        snapshots=summary.snapshots,
        securities=summary.securities,
        cash=summary.cash,
        total=summary.total,
        rounding_residual=summary.rounding_residual,
    )
    model = (
        m.AggregateHoldingModel
        if view == "holdings"
        else m.AggregateComponentModel
        if view == "components"
        else m.AggregateAccountTotalModel
    )
    total = (
        summary.holding_count
        if view == "holdings"
        else summary.component_count
        if view == "components"
        else len(summary.snapshots)
    )
    admitted = func.sum(func.octet_length(model.payload)).over() <= 2097152 - 8192 - len(saved[0])
    rows = session.execute(
        select(model.ordinal, case((admitted, model.payload), else_=None), model.content_digest)
        .where(
            model.owner_id == auth.owner_id,
            model.run_id == root.id,
            model.ordinal >= offset,
            model.ordinal < offset + limit,
        )
        .order_by(model.ordinal)
    ).all()
    if any(row[1] is None for row in rows):
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    if tuple(row[0] for row in rows) != tuple(range(offset, min(offset + limit, total))):
        raise _unavailable()
    if sum(len(row[1]) for row in rows) + len(saved[0]) > 2097152 - 8192:
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    token = _next(cursors, binding, at, offset, len(rows), total)
    if view == "holdings":
        return views.AggregateHoldingPage(
            context=context,
            items=tuple(
                codec.aggregation_holding_from_json(row[1], expected_digest=row[2]) for row in rows
            ),
            total=total,
            next_cursor=token,
        )
    if view == "components":
        return views.AggregateComponentPage(
            context=context,
            items=tuple(
                codec.aggregation_component_from_json(row[1], expected_digest=row[2])
                for row in rows
            ),
            total=total,
            next_cursor=token,
        )
    return views.AggregateAccountPage(
        context=context,
        items=tuple(
            codec.aggregation_account_from_json(row[1], expected_digest=row[2]) for row in rows
        ),
        total=total,
        next_cursor=token,
    )


def _transfers(
    session: Session,
    auth: AggregateAuthorization,
    root: m.AggregateRunModel,
    limit: int,
    offset: int,
    cursors: CursorCodec,
    binding: str,
    at: datetime,
) -> views.AggregateTransferPage:
    if root.holdings_input_digest is None:
        raise _unavailable()
    if not root.activity_requested:
        if offset:
            raise CursorValidationError("invalid cursor")
        return views.AggregateTransferPage(
            holdings_input_digest=root.holdings_input_digest,
            input_digest=None,
            result_digest=None,
            window=None,
            items=(),
            currency_totals=(),
            complete=False,
            reasons=(AggregateReason.NOT_REQUESTED,),
            candidate_count=0,
            selected_count=0,
            total=0,
            next_cursor=None,
        )
    saved = session.execute(
        select(
            m.AggregateActivityPayloadModel.summary_payload,
            m.AggregateActivityPayloadModel.summary_digest,
        ).where(
            m.AggregateActivityPayloadModel.owner_id == auth.owner_id,
            m.AggregateActivityPayloadModel.run_id == root.id,
            func.octet_length(m.AggregateActivityPayloadModel.summary_payload) <= 1048576,
        )
    ).one_or_none()
    if saved is None:
        raise _unavailable()
    summary = codec.aggregation_activity_summary_from_json(saved[0], expected_digest=saved[1])
    if (
        summary.input_digest != root.activity_input_digest
        or summary.holdings_input_digest != root.holdings_input_digest
    ):
        raise _unavailable()
    leg, match = m.AggregateFlowModel, m.AggregateTransferModel
    admitted = func.sum(
        func.octet_length(leg.payload) + func.coalesce(func.octet_length(match.payload), 0)
    ).over() <= 2097152 - 8192 - len(saved[0])
    rows = session.execute(
        select(
            leg.ordinal,
            case((admitted, leg.payload), else_=None),
            leg.content_digest,
            case((admitted, match.payload), else_=None),
            match.content_digest,
        )
        .outerjoin(
            match,
            (match.owner_id == leg.owner_id)
            & (match.run_id == leg.run_id)
            & (
                (match.outgoing_record_id == leg.source_record_id)
                | (match.incoming_record_id == leg.source_record_id)
            ),
        )
        .where(
            leg.owner_id == auth.owner_id,
            leg.run_id == root.id,
            leg.ordinal >= offset,
            leg.ordinal < offset + limit,
        )
        .order_by(leg.ordinal)
    ).all()
    if any(row[1] is None for row in rows):
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    if tuple(row[0] for row in rows) != tuple(
        range(offset, min(offset + limit, summary.selected_count))
    ):
        raise _unavailable()
    if (
        sum(len(row[1]) + (0 if row[3] is None else len(row[3])) for row in rows) + len(saved[0])
        > 2097152 - 8192
    ):
        raise app.AggregateServiceError(app.AggregateErrorCode.INPUT_BOUND_EXCEEDED)
    items = tuple(
        views.AggregateTransferRow(
            leg=codec.aggregation_flow_from_json(row[1], expected_digest=row[2]),
            match=None
            if row[3] is None
            else codec.aggregation_transfer_from_json(row[3], expected_digest=row[4]),
        )
        for row in rows
    )
    return views.AggregateTransferPage(
        holdings_input_digest=root.holdings_input_digest,
        input_digest=root.activity_input_digest,
        result_digest=root.activity_result_digest,
        window=summary.window,
        items=items,
        currency_totals=summary.currency_totals,
        complete=summary.complete,
        reasons=summary.reasons,
        candidate_count=summary.candidate_count,
        selected_count=summary.selected_count,
        total=summary.selected_count,
        next_cursor=_next(cursors, binding, at, offset, len(items), summary.selected_count),
    )
