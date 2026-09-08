"""Sealed calculation publication, exact source uses and bounded immutable pages."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session
from trading212_application import historical as app
from trading212_application import sources as source_app
from trading212_application.queries import CursorValidationError
from trading212_application.views import Page
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import (
    historical_result_digest,
    historical_result_from_json,
)
from trading212_domain.historical_validation import validate_historical_input
from trading212_domain.source_details import CorporateActionSnapshot
from trading212_domain.sources import BenchmarkSnapshot, FxSnapshot, PriceSnapshot
from trading212_security.principals import Principal, Scope

from . import historical_models as hm
from . import source_models as sm
from .collection_snapshots import (
    CollectionSnapshot,
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .historical_base import digest, encoded, error
from .models import CollectionQuerySnapshotMemberModel, CollectionQuerySnapshotModel
from .planning_models import AnalyticsRunModel, AnalyticsSourceModel

if TYPE_CHECKING:
    from .historical_service import PostgresHistoricalService, Query


def amount(value: d.HistoricalMoneyMetric) -> Decimal | None:
    return None if value.value is None else value.value.amount


def read_historical_result(
    service: PostgresHistoricalService,
    session: Session,
    principal: Principal,
    owner: UUID,
    account: UUID,
    query: Query,
    family: str,
) -> tuple[
    app.HistoricalCaptureView, hm.HistoricalRunModel, AnalyticsRunModel, r.HistoricalCalculation
]:
    from trading212_analytics import historical as analytics

    # A pinned capture is decoded, hashed and legally checked once within this
    # owner-locked transaction, then reused for selection and result validation.
    capture = None
    if query.input_snapshot_id is not None:
        row = service._owned(session, owner, hm.HistoricalInputModel, query.input_snapshot_id)
        if row.broker_account_id != account:
            raise error("NOT_FOUND")
        capture = service._capture_view(session, owner, row)
    request = service._request(
        session,
        owner,
        account,
        query,
        pinned=None if capture is None else capture.input.selection,
    )
    if capture is None:
        capture = service._capture(session, principal, owner, account, request)
    else:
        pinned = capture.input.selection
        if (
            pinned.window,
            pinned.benchmark_version_id,
            pinned.target_version_id,
            pinned.grouping_policy,
        ) != (
            request.window,
            request.benchmark_version_id,
            request.target_version_id,
            request.grouping_policy,
        ):
            raise error("INPUT_SNAPSHOT_MISMATCH")
        for needed in request.support_windows:
            if not any(
                x.reason == needed.reason
                and x.start_at <= needed.start_at
                and x.end_at >= needed.end_at
                for x in pinned.support_windows
            ):
                raise error("INPUT_SNAPSHOT_MISMATCH")
        if pinned.target_version_id is not None:
            service._authorizer.require_scope(principal, Scope.TARGETS_READ, now=service._now())
    options_digest = digest(query.options)
    run = session.scalar(
        select(hm.HistoricalRunModel).where(
            hm.HistoricalRunModel.owner_id == owner,
            hm.HistoricalRunModel.input_id == UUID(capture.id),
            hm.HistoricalRunModel.kind == family,
            hm.HistoricalRunModel.options_digest == options_digest,
        )
    )
    if run is not None:
        stored = session.get(AnalyticsRunModel, run.analytics_run_id)
        if stored is None or not run.sealed:
            raise error("HISTORICAL_UNAVAILABLE")
        result = historical_result_from_json(stored.canonical_result)
        if (
            historical_result_digest(result) != stored.content_digest
            or result.context.input_digest != capture.input_digest
        ):
            raise error("HISTORICAL_UNAVAILABLE")
        return capture, run, stored, result
    value = validate_historical_input(capture.input)
    if isinstance(query, (app.PerformanceSeriesQuery, app.PerformanceSummaryQuery)):
        result = analytics.calculate_performance(value, options=query.options)
    elif isinstance(query, app.BenchmarkComparisonQuery):
        result = analytics.calculate_benchmark_comparison(value, options=query.options)
    elif isinstance(query, app.AttributionQuery):
        result = analytics.calculate_attribution(value, options=query.options)
    elif isinstance(query, app.DividendIntelligenceQuery):
        result = analytics.calculate_income(value, options=query.options)
    else:
        result = analytics.calculate_cash_flows(value, options=query.options)
    analytics.verify_historical_result(value, result)
    if result.context.input_digest != capture.input_digest:
        raise error("HISTORICAL_UNAVAILABLE")
    service._reauthorize(session, owner, account, input_id=UUID(capture.id))
    stored = AnalyticsRunModel(
        id=uuid4(),
        owner_id=owner,
        broker_account_id=account,
        kind=family,
        input_digest=digest((capture.input_digest, query.options)),
        content_digest=historical_result_digest(result),
        method_version=result.context.method.version,
        reporting_currency=request.window.reporting_currency.value,
        valuation_at=request.window.end_at,
        source_cutoff_at=request.window.source_cutoff_at,
        canonical_input=encoded(value),
        canonical_result=encoded(result),
        created_at=service._now(),
    )
    session.add(stored)
    session.flush()
    run = hm.HistoricalRunModel(
        id=uuid4(),
        owner_id=owner,
        input_id=UUID(capture.id),
        analytics_run_id=stored.id,
        kind=family,
        options_digest=options_digest,
        sealed=False,
        created_at=stored.created_at,
    )
    session.add(run)
    session.flush()
    session.add(
        AnalyticsSourceModel(
            owner_id=owner,
            run_id=stored.id,
            historical_input_id=UUID(capture.id),
            digest=capture.input_digest,
        )
    )
    persist_result_rows(session, owner, run, result)
    persist_uses(session, owner, run, value, result)
    if isinstance(result, r.BenchmarkCalculation) and result.composite is not None:
        persist_composite(session, owner, run, result.composite, stored.created_at)
    session.flush()
    run.sealed = True
    session.add(
        hm.HistoricalAuditEventModel(
            owner_id=owner,
            run_id=run.id,
            kind="result_published",
            actor_principal_id=principal.principal_id,
            created_at=service._now(),
        )
    )
    session.flush()
    return capture, run, stored, result


def persist_result_rows(
    session: Session, owner: UUID, run: hm.HistoricalRunModel, result: r.HistoricalCalculation
) -> None:
    if isinstance(result, r.PerformanceCalculation):
        for i, row in enumerate(result.points):
            session.add(
                hm.PerformancePointModel(
                    owner_id=owner,
                    run_id=run.id,
                    ordinal=i,
                    row_key=str(row.ordinal),
                    canonical_row=encoded(row),
                    date=row.date,
                    valuation_at=row.valuation_at,
                    portfolio_value=amount(row.portfolio_value),
                    cash_value=amount(row.cash_value),
                    wealth=row.twr_wealth.value,
                    period_return=row.interval_return.value,
                )
            )
        for i, period in enumerate((*result.rolling_returns, *result.calendar_returns)):
            session.add(
                hm.PerformancePeriodModel(
                    owner_id=owner,
                    run_id=run.id,
                    ordinal=i,
                    row_key=f"{period.kind}:{period.period_start_at.isoformat()}",
                    canonical_row=encoded(period),
                    period_kind=period.kind,
                    period_start=period.period_start_at.date(),
                    period_end=period.period_end_at.date(),
                    period_return=period.value.value,
                )
            )
    elif isinstance(result, r.IncomeCalculation):
        ordinal = 0
        for kind, rows in (("holding", result.instrument_rows), ("group", result.group_rows)):
            for income_row in rows:
                session.add(
                    hm.HistoricalIncomeRowModel(
                        owner_id=owner,
                        run_id=run.id,
                        ordinal=ordinal,
                        row_key=income_row.key,
                        canonical_row=encoded(income_row),
                        row_kind=kind,
                        currency=income_row.currency.value,
                        net=amount(income_row.net),
                        gross=amount(income_row.gross),
                        withholding=amount(income_row.withholding),
                    )
                )
                ordinal += 1
        for income_period in result.period_rows:
            session.add(
                hm.HistoricalIncomeRowModel(
                    owner_id=owner,
                    run_id=run.id,
                    ordinal=ordinal,
                    row_key=income_period.start_date.isoformat(),
                    canonical_row=encoded(income_period),
                    row_kind="period",
                    currency=None
                    if income_period.reporting_net.value is None
                    else income_period.reporting_net.value.currency.value,
                    net=amount(income_period.reporting_net),
                    gross=None,
                    withholding=None,
                )
            )
            ordinal += 1
    elif isinstance(result, r.AttributionCalculation):
        for i, attribution_row in enumerate(result.rows):
            session.add(
                hm.HistoricalAttributionRowModel(
                    owner_id=owner,
                    run_id=run.id,
                    ordinal=i,
                    row_key=attribution_row.key,
                    canonical_row=encoded(attribution_row),
                    currency=None
                    if attribution_row.currency is None
                    else attribution_row.currency.value,
                    gain=amount(attribution_row.amount),
                    return_contribution=attribution_row.return_contribution.value,
                )
            )
    elif isinstance(result, r.CashFlowCalculation):
        for i, flow_row in enumerate(result.events):
            session.add(
                hm.HistoricalCashFlowRowModel(
                    owner_id=owner,
                    run_id=run.id,
                    ordinal=i,
                    row_key=flow_row.event_revision_id,
                    canonical_row=encoded(flow_row),
                    economic_at=flow_row.economic_at,
                    kind=flow_row.kind.value,
                    currency=None
                    if flow_row.native_amount.value is None
                    else flow_row.native_amount.value.currency.value,
                    amount=amount(flow_row.native_amount),
                )
            )


def persist_uses(
    session: Session,
    owner: UUID,
    run: hm.HistoricalRunModel,
    value: d.HistoricalInput,
    result: r.HistoricalCalculation,
) -> None:
    dependencies = {
        x.reference_key.split(":", 1)[1]: x
        for x in session.scalars(
            select(hm.HistoricalDependencyModel).where(
                hm.HistoricalDependencyModel.input_id == run.input_id
            )
        )
    }
    evidence_anchors = {
        x.anchor_key: x
        for x in session.scalars(
            select(hm.HistoricalAnchorModel)
            .where(hm.HistoricalAnchorModel.id.in_([UUID(x.id) for x in value.valuation_anchors]))
            .limit(10001)
        )
    }
    snapshots: dict[
        str, PriceSnapshot | FxSnapshot | BenchmarkSnapshot | CorporateActionSnapshot
    ] = {}
    snapshots.update({x.id: x for x in value.price_snapshots})
    snapshots.update({x.id: x for x in value.fx_snapshots})
    snapshots.update({x.id: x for x in value.action_snapshots})
    if value.benchmark_input is not None:
        snapshots.update({x.id: x for x in value.benchmark_input.price_snapshots})
        snapshots.update({x.id: x for x in value.benchmark_input.benchmark_snapshots})
    uses: dict[str, UUID] = {}
    pending: list[dict[str, object]] = []
    # Fixed-size executemany batches avoid giant RETURNING statements and ORM
    # identity bookkeeping for immutable rows whose IDs are already assigned.
    # Every database scope, source-use and sealing trigger still runs per row.
    statement = insert(hm.HistoricalSourceUseModel).execution_options(render_nulls=True)
    for use in result.source_uses:
        dependency = None
        index = None
        if isinstance(use, r.HistoricalObservationUse):
            source = snapshots.get(use.snapshot_id)
            if source is None or not 0 <= use.observation_index < len(source.observations):
                raise error("HISTORICAL_UNAVAILABLE")
            dependency = dependencies.get(use.snapshot_id)
            index = use.observation_index
        elif isinstance(use, r.HistoricalEvidenceUse):
            dependency = dependencies.get(use.reference_id)
            if dependency is None and use.reference_kind == "opening":
                anchor = evidence_anchors.get(use.reference_id)
                if anchor is not None:
                    dependency = dependencies.get(str(anchor.evidence_id))
            if dependency is None:
                raise error("HISTORICAL_UNAVAILABLE")
        elif any(x not in snapshots for x in use.candidate_snapshot_ids):
            raise error("HISTORICAL_UNAVAILABLE")
        if use.kind != "missing" and dependency is None:
            raise error("HISTORICAL_UNAVAILABLE")
        identifier = uuid4()
        row: dict[str, object] = dict(
            id=identifier,
            owner_id=owner,
            run_id=run.id,
            use_key=use.use_key,
            kind=use.kind,
            role=use.role,
            use_at=use.use_at,
            knowledge_cutoff_at=use.knowledge_cutoff_at,
            dependency_id=None if dependency is None else dependency.id,
            observation_index=index,
            consumer_kind=use.consumer.kind,
            listing_id=None if use.consumer.listing_id is None else UUID(use.consumer.listing_id),
            instrument_id=None
            if use.consumer.instrument_id is None
            else UUID(use.consumer.instrument_id),
            event_revision_id=None
            if use.consumer.event_revision_id is None
            else UUID(use.consumer.event_revision_id),
            group_key=use.consumer.group_key,
            component_source_id=None
            if use.consumer.component_source_id is None
            else UUID(use.consumer.component_source_id),
            expected_series_id=UUID(use.expected.series_id)
            if isinstance(use, r.HistoricalMissingUse)
            and isinstance(use.expected, r.HistoricalExpectedSeries)
            else None,
            expected_base=use.expected.base.value
            if isinstance(use, r.HistoricalMissingUse)
            and isinstance(use.expected, r.HistoricalExpectedFx)
            else None,
            expected_quote=use.expected.quote.value
            if isinstance(use, r.HistoricalMissingUse)
            and isinstance(use.expected, r.HistoricalExpectedFx)
            else None,
            calendar_id=session.scalar(
                select(sm.SourceCalendarModel.id).where(
                    sm.SourceCalendarModel.owner_id == owner,
                    sm.SourceCalendarModel.key == use.calendar_ref.id,
                    sm.SourceCalendarModel.version == use.calendar_ref.version,
                )
            )
            if isinstance(use, r.HistoricalMissingUse)
            else None,
            expected_session=use.expected_session
            if isinstance(use, r.HistoricalMissingUse)
            else None,
            reason=use.reason.value if isinstance(use, r.HistoricalMissingUse) else None,
            canonical_use=encoded(use),
        )
        pending.append(row)
        uses[use.use_key] = identifier
        if len(pending) == 256:
            session.execute(statement, pending)
            pending.clear()
    if pending:
        session.execute(statement, pending)
    session.flush()
    for missing in result.source_uses:
        if isinstance(missing, r.HistoricalMissingUse):
            for candidate in missing.candidate_snapshot_ids:
                session.add(
                    hm.HistoricalUseCandidateModel(
                        owner_id=owner,
                        source_use_id=uses[missing.use_key],
                        dependency_id=dependencies[candidate].id,
                    )
                )
    for conversion in result.conversions:
        session.add(
            hm.HistoricalConversionModel(
                owner_id=owner,
                run_id=run.id,
                conversion_key=conversion.conversion_key,
                use_at=conversion.use_at,
                base=conversion.base.value,
                quote=conversion.quote.value,
                operation=conversion.operation.value,
                rate=conversion.rate,
            )
        )
    for use in result.source_uses:
        if isinstance(use, r.HistoricalObservationUse) and use.conversion_leg is not None:
            leg = use.conversion_leg
            session.add(
                hm.HistoricalConversionLegModel(
                    owner_id=owner,
                    run_id=run.id,
                    source_use_id=uses[use.use_key],
                    conversion_key=leg.conversion_key,
                    ordinal=leg.ordinal,
                    direction=leg.direction,
                    base=leg.base.value,
                    quote=leg.quote.value,
                )
            )


def persist_composite(
    session: Session,
    owner: UUID,
    run: hm.HistoricalRunModel,
    composite: r.CompositeBenchmarkSnapshot,
    calculated_at: datetime,
) -> None:
    content = digest(composite)
    old = session.scalar(
        select(sm.BenchmarkSnapshotModel).where(
            sm.BenchmarkSnapshotModel.owner_id == owner,
            sm.BenchmarkSnapshotModel.content_digest == content,
        )
    )
    if old is None:
        dependencies = session.scalars(
            select(hm.HistoricalDependencyModel).where(
                hm.HistoricalDependencyModel.input_id == run.input_id
            )
        ).all()
        by_id = {x.reference_key.split(":", 1)[1]: x for x in dependencies}
        expiry = []
        synthetic = []
        for dependency in dependencies:
            for column, model in (
                ("price_snapshot_id", sm.PriceSnapshotModel),
                ("fx_snapshot_id", sm.FxSnapshotModel),
                ("benchmark_snapshot_id", sm.BenchmarkSnapshotModel),
            ):
                identifier = getattr(dependency, column)
                if identifier is not None:
                    snapshot = session.get(model, identifier)
                    assert snapshot is not None
                    expiry.append(snapshot.expires_at)
                    synthetic.append(snapshot.synthetic)
        if not expiry:
            raise error("HISTORICAL_UNAVAILABLE")
        # No provider or licensing identity is invented for a derived snapshot.
        old = sm.BenchmarkSnapshotModel(
            id=uuid4(),
            owner_id=owner,
            snapshot_kind="composite",
            series_id=None,
            benchmark_version_id=UUID(composite.benchmark_version_id),
            provider_id=None,
            license_version_id=None,
            adapter_version=None,
            schema_version=d.HISTORICAL_SCHEMA_VERSION,
            source_revision=None,
            revision_order=None,
            economic_digest=content,
            content_digest=content,
            effective_at=composite.window.end_at,
            first_observed_at=calculated_at,
            expires_at=min(expiry),
            synthetic=all(synthetic),
            period_start=composite.window.start_date,
            period_end=composite.window.end_date,
            expected_count=len(composite.observations),
            available_count=sum(x.wealth.value is not None for x in composite.observations),
            quality="fresh"
            if all(x.wealth.value is not None for x in composite.observations)
            else "partial",
            reason=None,
            created_at=calculated_at,
        )
        session.add(old)
        session.flush()
        for component in composite.inputs:
            row = hm.BenchmarkSnapshotComponentModel(
                id=uuid4(),
                owner_id=owner,
                snapshot_id=old.id,
                source_id=UUID(component.source_id),
                weight=component.weight,
            )
            session.add(row)
            session.flush()
            for identifier in set((*component.snapshot_ids, *component.license_version_ids)):
                selected_dependency = by_id.get(identifier)
                if selected_dependency is None:
                    raise error("HISTORICAL_UNAVAILABLE")
                session.add(
                    hm.BenchmarkSnapshotDependencyModel(
                        owner_id=owner, component_id=row.id, dependency_id=selected_dependency.id
                    )
                )
        for point in composite.observations:
            session.add(
                hm.BenchmarkCompositePointModel(
                    owner_id=owner,
                    snapshot_id=old.id,
                    ordinal=point.ordinal,
                    session_date=point.session_date,
                    effective_at=point.effective_at,
                    wealth=point.wealth.value,
                    interval_return=point.interval_return.value,
                    canonical_point=encoded(point),
                )
            )
    session.add(
        hm.HistoricalCompositeModel(
            owner_id=owner,
            run_id=run.id,
            snapshot_id=old.id,
            canonical_composite=encoded(composite),
        )
    )


def composite_header(
    session: Session,
    owner: UUID,
    run: hm.HistoricalRunModel,
    result: r.BenchmarkCalculation,
) -> source_app.CompositeBenchmarkSnapshotHeaderView:
    link = session.scalar(
        select(hm.HistoricalCompositeModel).where(
            hm.HistoricalCompositeModel.run_id == run.id,
            hm.HistoricalCompositeModel.owner_id == owner,
        )
    )
    assert link is not None and result.composite is not None
    snapshot = session.get(sm.BenchmarkSnapshotModel, link.snapshot_id)
    assert snapshot is not None
    return composite_snapshot_header(snapshot, result.composite)


def composite_snapshot_header(
    snapshot: sm.BenchmarkSnapshotModel,
    composite: r.CompositeBenchmarkSnapshot,
) -> source_app.CompositeBenchmarkSnapshotHeaderView:
    """Project the same canonical composite for comparison and source detail reads."""
    return source_app.CompositeBenchmarkSnapshotHeaderView(
        id=str(snapshot.id),
        benchmark_version_id=composite.benchmark_version_id,
        reporting_currency=composite.reporting_currency,
        return_basis=composite.return_basis,
        calendar_id=composite.calendar_ref.id,
        calendar_version=composite.calendar_ref.version,
        rebalance_rule=composite.rebalance_rule,
        window=composite.window,
        input_digest=composite.input_digest,
        content_digest=digest(composite),
        calculated_at=snapshot.created_at,
        method=composite.method,
        inputs=composite.inputs,
        observation_count=len(composite.observations),
        coverage=composite.coverage,
    )


def historical_page[T: r.PerformancePoint | r.HistoricalCashFlowPoint](
    service: PostgresHistoricalService,
    session: Session,
    owner: UUID,
    account: UUID,
    run: hm.HistoricalRunModel,
    points: tuple[T, ...],
    query: app.PerformanceSeriesQuery | app.CashFlowIntelligenceQuery,
) -> Page[T]:
    model: type[hm.PerformancePointModel] | type[hm.HistoricalCashFlowRowModel] = (
        hm.PerformancePointModel
        if isinstance(query, app.PerformanceSeriesQuery)
        else hm.HistoricalCashFlowRowModel
    )
    resource = (
        CollectionSnapshotResource.HISTORICAL_PERFORMANCE
        if isinstance(query, app.PerformanceSeriesQuery)
        else CollectionSnapshotResource.HISTORICAL_CASH_FLOWS
    )
    definition = CollectionSnapshotDefinition(
        resource, owner, account, collection_filter_fingerprint(run.id, run.options_digest)
    )
    ids = tuple(
        session.scalars(
            select(model.id).where(model.run_id == run.id).order_by(model.ordinal).limit(10001)
        )
    )
    if len(ids) != len(points):
        raise error("HISTORICAL_UNAVAILABLE")
    store = CollectionSnapshotStore(
        session,
        service._cursors,
        ttl_seconds=service._ttl,
        max_active_snapshots_per_owner=service._snapshot_quota,
        max_active_members_per_owner=service._member_quota,
    )
    if query.cursor is not None:
        page = store.resume(definition, query.cursor, limit=query.limit)
    else:
        key = digest((definition, run.id, ids))
        retained = session.scalar(
            select(CollectionQuerySnapshotModel)
            .join(
                hm.HistoricalCollectionBindingModel,
                hm.HistoricalCollectionBindingModel.collection_snapshot_id
                == CollectionQuerySnapshotModel.id,
            )
            .where(
                hm.HistoricalCollectionBindingModel.owner_id == owner,
                hm.HistoricalCollectionBindingModel.cache_key == key,
                CollectionQuerySnapshotModel.expires_at > func.now(),
            )
            .order_by(CollectionQuerySnapshotModel.created_at.desc())
            .limit(1)
        )
        if retained is None:
            page = store.materialize(definition, ids, limit=query.limit)
            session.add(
                hm.HistoricalCollectionBindingModel(
                    owner_id=owner,
                    run_id=run.id,
                    collection_snapshot_id=page.snapshot_id,
                    cache_key=key,
                )
            )
        else:
            actual = tuple(
                session.scalars(
                    select(CollectionQuerySnapshotMemberModel.record_id)
                    .where(CollectionQuerySnapshotMemberModel.snapshot_id == retained.id)
                    .order_by(CollectionQuerySnapshotMemberModel.ordinal)
                    .limit(len(ids) + 1)
                )
            )
            if actual != ids or retained.exact_total != len(ids):
                raise CursorValidationError("The retained historical membership is invalid.")
            page = store._read_page(
                CollectionSnapshot(
                    retained.id, definition, len(ids), retained.created_at, retained.expires_at
                ),
                after_ordinal=0,
                limit=query.limit,
            )
    index = {identifier: i for i, identifier in enumerate(ids)}
    if any(x not in index for x in page.record_ids):
        raise CursorValidationError("The retained historical membership is invalid.")
    return Page(
        tuple(points[index[x]] for x in page.record_ids),
        page.next_cursor,
        page.limit,
        page.exact_total,
    )
