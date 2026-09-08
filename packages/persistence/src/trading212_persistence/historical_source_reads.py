"""Closed composite benchmark reads with current authorization of immutable dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import sources as app
from trading212_application.queries import CursorValidationError
from trading212_domain.errors import DomainError
from trading212_domain.historical_results import CompositeBenchmarkPoint, CompositeBenchmarkSnapshot
from trading212_domain.historical_serialization import historical_value_from_json
from trading212_domain.sources import SourceUse
from trading212_security.principals import Principal, Scope

from . import historical_models as hm
from . import source_models as sm
from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    collection_filter_fingerprint,
)
from .historical_publication import composite_snapshot_header
from .planning_models import AnalyticsRunModel
from .source_store import error

if TYPE_CHECKING:
    from .source_reads import SourceReads


def authorized_composite(
    service: SourceReads,
    session: Session,
    principal: Principal,
    owner: UUID,
    snapshot: sm.BenchmarkSnapshotModel,
    account_id: str | None,
) -> app.CompositeBenchmarkSnapshotHeaderView:
    service._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=service._now())
    link = session.scalar(
        select(hm.HistoricalCompositeModel)
        .where(
            hm.HistoricalCompositeModel.owner_id == owner,
            hm.HistoricalCompositeModel.snapshot_id == snapshot.id,
        )
        .order_by(hm.HistoricalCompositeModel.created_at, hm.HistoricalCompositeModel.id)
        .limit(1)
    )
    if link is None:
        raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
    run = session.get(hm.HistoricalRunModel, link.run_id)
    assert run is not None
    # Detail authorization needs the capture account, not its full input document.
    capture_account = session.scalar(
        select(hm.HistoricalInputModel.broker_account_id).where(
            hm.HistoricalInputModel.id == run.input_id,
            hm.HistoricalInputModel.owner_id == owner,
        )
    )
    if capture_account is None:
        raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
    actual = service._account(session, principal, str(capture_account))
    if account_id is not None and str(actual) != account_id:
        raise error(app.SourceServiceErrorCode.NOT_FOUND)
    if snapshot.expires_at <= service._now():
        raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
    dependencies = session.scalars(
        select(hm.HistoricalDependencyModel)
        .where(
            hm.HistoricalDependencyModel.owner_id == owner,
            hm.HistoricalDependencyModel.input_id == run.input_id,
        )
        .limit(100001)
    ).all()
    if len(dependencies) > 100000:
        raise error(app.SourceServiceErrorCode.RESULT_TOO_LARGE)
    # Every immutable economic and license parent remains retained and currently usable.
    for dependency in dependencies:
        if dependency.license_version_id is not None:
            service._permit(session, owner, dependency.license_version_id, SourceUse.DISPLAY)
        for identifier, model in (
            (dependency.price_snapshot_id, sm.PriceSnapshotModel),
            (dependency.fx_snapshot_id, sm.FxSnapshotModel),
            (dependency.action_snapshot_id, sm.CorporateActionSnapshotModel),
            (dependency.benchmark_snapshot_id, sm.BenchmarkSnapshotModel),
        ):
            if identifier is not None:
                parent = session.get(model, identifier)
                if parent is None or parent.owner_id != owner:
                    raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
                service._snapshot_permit(session, parent)
    stored_kind = session.scalar(
        select(AnalyticsRunModel.kind).where(
            AnalyticsRunModel.id == run.analytics_run_id,
            AnalyticsRunModel.owner_id == owner,
        )
    )
    if stored_kind != "benchmark" or run.kind != "benchmark" or not run.sealed:
        raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
    # Publication retains this exact composite separately from the full calculation.
    # Decode and authenticate that bounded value without materializing unrelated
    # result/source-use evidence or either full analytics input/result blob.
    try:
        composite = historical_value_from_json(link.canonical_composite, CompositeBenchmarkSnapshot)
    except DomainError:
        raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE) from None
    header = composite_snapshot_header(snapshot, composite)
    if header.content_digest != snapshot.content_digest:
        raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
    return header


def composite_page(
    service: SourceReads,
    session: Session,
    principal: Principal,
    owner: UUID,
    snapshot: sm.BenchmarkSnapshotModel,
    query: app.SourceObservationQuery,
) -> app.CompositeBenchmarkObservationPageView:
    header = authorized_composite(service, session, principal, owner, snapshot, query.account_id)
    definition = CollectionSnapshotDefinition(
        CollectionSnapshotResource.COMPOSITE_BENCHMARK_POINTS,
        owner,
        None if query.account_id is None else UUID(query.account_id),
        collection_filter_fingerprint(snapshot.id, snapshot.content_digest),
    )
    identifiers = (
        ()
        if query.cursor
        else tuple(
            session.scalars(
                select(hm.BenchmarkCompositePointModel.id)
                .where(
                    hm.BenchmarkCompositePointModel.snapshot_id == snapshot.id,
                    hm.BenchmarkCompositePointModel.owner_id == owner,
                )
                .order_by(hm.BenchmarkCompositePointModel.ordinal)
                .limit(3662)
            )
        )
    )
    if len(identifiers) > 3661:
        raise error(app.SourceServiceErrorCode.RESULT_TOO_LARGE)
    page = service._page(session, definition, identifiers, cursor=query.cursor, limit=query.limit)
    rows = []
    for identifier in page.record_ids:
        row = session.get(hm.BenchmarkCompositePointModel, identifier)
        if row is None or row.owner_id != owner or row.snapshot_id != snapshot.id:
            raise CursorValidationError("The retained composite membership is invalid.")
        rows.append(historical_value_from_json(row.canonical_point, CompositeBenchmarkPoint))
    if page.exact_total != header.observation_count:
        raise CursorValidationError("The retained composite membership is invalid.")
    return app.CompositeBenchmarkObservationPageView(
        items=tuple(rows),
        next_cursor=page.next_cursor,
        limit=page.limit,
        total=page.exact_total,
        snapshot_id=str(snapshot.id),
    )
