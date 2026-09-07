"""Authorized retained source headers, observation pages and frozen status selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from trading212_application import sources as app
from trading212_application.queries import CursorValidationError
from trading212_application.source_providers import SourceCapability
from trading212_application.views import Page
from trading212_domain.sources import (
    BenchmarkObservation,
    FxObservation,
    PriceBasis,
    PriceObservation,
    SourceAvailability,
    SourcePeriod,
    SourceReason,
    SourceUse,
)
from trading212_security.principals import Principal

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    collection_filter_fingerprint,
)
from .source_models import (
    BenchmarkObservationModel,
    BenchmarkSnapshotModel,
    FxObservationModel,
    FxSnapshotModel,
    MarketDataProviderModel,
    MarketSourceSeriesModel,
    PriceObservationModel,
    PriceSnapshotModel,
    SourceCoverageGapModel,
    SourceRetrievalOccurrenceModel,
    SourceSnapshotFields,
    SourceStatusSelectionModel,
)
from .source_store import SourceStore, digest, error


@dataclass(frozen=True)
class SnapshotChoice:
    snapshot: SourceSnapshotFields | None
    reason: SourceReason | None = None


class SourceReads(SourceStore):
    async def get_price_snapshot(
        self, principal: Principal, snapshot_id: str, *, account_id: str | None = None
    ) -> app.PriceSnapshotHeaderView:
        def operation(session: Session, owner: UUID) -> app.PriceSnapshotHeaderView:
            self._account(session, principal, account_id)
            row = self._owned(session, owner, PriceSnapshotModel, snapshot_id)
            license = self._snapshot_permit(session, row)
            return app.PriceSnapshotHeaderView(
                id=str(row.id),
                series=self._series_view(session, owner, row.series_id),
                provenance=self._provenance(row),
                period=SourcePeriod(start=row.period_start, end=row.period_end),
                coverage=app.SourceCoverageView.from_coverage(self._coverage(session, row)),
                freshness=self._freshness(session, row),
                content_digest=row.content_digest,
                license=license,
                latest_retrieval=self._retrieval(session, row),
            )

        return await self._run(principal, operation)

    async def get_fx_snapshot(
        self, principal: Principal, snapshot_id: str, *, account_id: str | None = None
    ) -> app.FxSnapshotHeaderView:
        def operation(session: Session, owner: UUID) -> app.FxSnapshotHeaderView:
            self._account(session, principal, account_id)
            row = self._owned(session, owner, FxSnapshotModel, snapshot_id)
            license = self._snapshot_permit(session, row)
            calendar = self._calendar(session, owner, row.calendar_id)
            return app.FxSnapshotHeaderView(
                calendar_id=calendar.id,
                calendar_version=calendar.version,
                id=str(row.id),
                provenance=self._provenance(row),
                period=SourcePeriod(start=row.period_start, end=row.period_end),
                coverage=app.SourceCoverageView.from_coverage(self._coverage(session, row)),
                freshness=self._freshness(session, row),
                content_digest=row.content_digest,
                license=license,
                latest_retrieval=self._retrieval(session, row),
            )

        return await self._run(principal, operation)

    async def get_benchmark_snapshot(
        self, principal: Principal, snapshot_id: str, *, account_id: str | None = None
    ) -> app.BenchmarkSnapshotHeaderView:
        def operation(session: Session, owner: UUID) -> app.BenchmarkSnapshotHeaderView:
            self._account(session, principal, account_id)
            row = self._owned(session, owner, BenchmarkSnapshotModel, snapshot_id)
            license = self._snapshot_permit(session, row)
            if row.snapshot_kind != "provider_series" or row.series_id is None:
                raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
            return app.BenchmarkSnapshotHeaderView(
                id=str(row.id),
                series=self._series_view(session, owner, row.series_id),
                provenance=self._provenance(row),
                period=SourcePeriod(start=row.period_start, end=row.period_end),
                coverage=app.SourceCoverageView.from_coverage(self._coverage(session, row)),
                freshness=self._freshness(session, row),
                content_digest=row.content_digest,
                license=license,
                latest_retrieval=self._retrieval(session, row),
            )

        return await self._run(principal, operation)

    async def list_price_observations(
        self, principal: Principal, snapshot_id: str, *, query: app.SourceObservationQuery
    ) -> Page[PriceObservation]:
        def operation(session: Session, owner: UUID) -> Page[PriceObservation]:
            account = self._account(session, principal, query.account_id)
            snapshot = self._owned(session, owner, PriceSnapshotModel, snapshot_id)
            self._snapshot_permit(session, snapshot)
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.PRICE_OBSERVATIONS,
                owner,
                account,
                collection_filter_fingerprint(snapshot.id, snapshot.content_digest),
            )
            ids = (
                ()
                if query.cursor
                else tuple(
                    session.scalars(
                        select(PriceObservationModel.id)
                        .where(PriceObservationModel.snapshot_id == snapshot.id)
                        .order_by(PriceObservationModel.ordinal)
                    )
                )
            )
            page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
            rows = tuple(
                self._owned(session, owner, PriceObservationModel, x) for x in page.record_ids
            )
            if any(row.snapshot_id != snapshot.id for row in rows):
                raise CursorValidationError("The retained source membership is invalid.")
            items = tuple(self._price_observation(row) for row in rows)
            return Page(items, page.next_cursor, page.limit, page.exact_total)

        return await self._run(principal, operation)

    async def list_fx_observations(
        self, principal: Principal, snapshot_id: str, *, query: app.SourceObservationQuery
    ) -> Page[FxObservation]:
        def operation(session: Session, owner: UUID) -> Page[FxObservation]:
            account = self._account(session, principal, query.account_id)
            snapshot = self._owned(session, owner, FxSnapshotModel, snapshot_id)
            self._snapshot_permit(session, snapshot)
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.FX_OBSERVATIONS,
                owner,
                account,
                collection_filter_fingerprint(snapshot.id, snapshot.content_digest),
            )
            ids = (
                ()
                if query.cursor
                else tuple(
                    session.scalars(
                        select(FxObservationModel.id)
                        .where(FxObservationModel.snapshot_id == snapshot.id)
                        .order_by(FxObservationModel.ordinal)
                    )
                )
            )
            page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
            rows = tuple(
                self._owned(session, owner, FxObservationModel, x) for x in page.record_ids
            )
            if any(row.snapshot_id != snapshot.id for row in rows):
                raise CursorValidationError("The retained source membership is invalid.")
            return Page(
                tuple(self._fx_observation(row) for row in rows),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._run(principal, operation)

    async def list_benchmark_observations(
        self, principal: Principal, snapshot_id: str, *, query: app.SourceObservationQuery
    ) -> Page[BenchmarkObservation]:
        def operation(session: Session, owner: UUID) -> Page[BenchmarkObservation]:
            account = self._account(session, principal, query.account_id)
            snapshot = self._owned(session, owner, BenchmarkSnapshotModel, snapshot_id)
            self._snapshot_permit(session, snapshot)
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.BENCHMARK_OBSERVATIONS,
                owner,
                account,
                collection_filter_fingerprint(snapshot.id, snapshot.content_digest),
            )
            ids = (
                ()
                if query.cursor
                else tuple(
                    session.scalars(
                        select(BenchmarkObservationModel.id)
                        .where(BenchmarkObservationModel.snapshot_id == snapshot.id)
                        .order_by(BenchmarkObservationModel.ordinal)
                    )
                )
            )
            page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
            rows = tuple(
                self._owned(session, owner, BenchmarkObservationModel, x) for x in page.record_ids
            )
            if any(row.snapshot_id != snapshot.id for row in rows):
                raise CursorValidationError("The retained source membership is invalid.")
            return Page(
                tuple(self._benchmark_observation(row) for row in rows),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._run(principal, operation)

    def _providers(
        self, session: Session, owner: UUID, provider_id: str | None
    ) -> tuple[app.ProviderStatusView, ...]:
        query = select(MarketDataProviderModel).where(MarketDataProviderModel.owner_id == owner)
        if provider_id is not None:
            self._owned(session, owner, MarketDataProviderModel, provider_id)
            query = query.where(MarketDataProviderModel.id == UUID(provider_id))
        rows = tuple(
            session.scalars(
                query.order_by(MarketDataProviderModel.key, MarketDataProviderModel.id).limit(101)
            )
        )
        if len(rows) > 100:
            raise error(app.SourceServiceErrorCode.RESULT_TOO_LARGE)
        views = []
        for row in rows:
            license = self._current_license(session, owner, row.id)
            reason = (
                SourceReason.NOT_CONFIGURED if row.configuration_state != "configured" else None
            )
            if reason is None and (license is None or not license.permits(SourceUse.DISPLAY)):
                reason = SourceReason.LICENSE_DENIED
            views.append(
                app.ProviderStatusView(
                    id=str(row.id),
                    key=row.key,
                    name=row.name,
                    adapter_version=row.adapter_version,
                    configuration_state=app.ProviderConfigurationState(row.configuration_state),
                    availability=SourceAvailability.AVAILABLE
                    if reason is None
                    else SourceAvailability.UNAVAILABLE,
                    synthetic=row.synthetic,
                    freshness_policy_version=row.freshness_policy_version,
                    max_age_seconds=row.max_age_seconds,
                    capabilities=tuple(SourceCapability(x) for x in row.capabilities),
                    supported_price_bases=tuple(PriceBasis(x) for x in row.supported_price_bases),
                    license=license,
                    reason=reason,
                )
            )
        return tuple(views)

    def _select_snapshot(
        self,
        session: Session,
        owner: UUID,
        model: type[PriceSnapshotModel] | type[FxSnapshotModel] | type[BenchmarkSnapshotModel],
        *,
        series: UUID | None,
        provider: UUID,
        period: SourcePeriod | None,
        cutoff: datetime | None,
        pair: tuple[str, str] | None = None,
    ) -> SnapshotChoice:
        if cutoff is None:
            cutoff = session.scalar(
                select(func.max(SourceRetrievalOccurrenceModel.retrieved_at)).where(
                    SourceRetrievalOccurrenceModel.owner_id == owner
                )
            )
        if cutoff is None:
            return SnapshotChoice(None)
        query = select(model).where(
            model.owner_id == owner,
            model.provider_id == provider,
            model.first_observed_at <= cutoff,
            model.effective_at <= cutoff,
        )
        if series is not None:
            series_model = (
                PriceSnapshotModel if model is PriceSnapshotModel else BenchmarkSnapshotModel
            )
            query = query.where(series_model.series_id == series)
        if period is not None:
            query = query.where(model.period_start <= period.start, model.period_end >= period.end)
        if pair is not None:
            query = query.where(
                or_(
                    select(FxObservationModel.id)
                    .where(
                        FxObservationModel.snapshot_id == model.id,
                        FxObservationModel.base == pair[0],
                        FxObservationModel.quote == pair[1],
                    )
                    .exists(),
                    select(SourceCoverageGapModel.id)
                    .where(
                        SourceCoverageGapModel.fx_snapshot_id == model.id,
                        SourceCoverageGapModel.source_key == pair[0] + ":" + pair[1],
                    )
                    .exists(),
                )
            )
        latest = session.scalar(query.order_by(model.effective_at.desc(), model.id).limit(1))
        if latest is None:
            return SnapshotChoice(None)
        candidates = query.where(model.effective_at == latest.effective_at)
        count, ordered, highest = session.execute(
            candidates.with_only_columns(
                func.count(model.id),
                func.count(model.revision_order),
                func.max(model.revision_order),
            )
        ).one()
        if count == ordered:
            candidates = candidates.where(model.revision_order == highest)
        different = session.scalar(
            candidates.with_only_columns(func.count(func.distinct(model.economic_digest)))
        )
        chosen = session.scalar(candidates.order_by(model.id).limit(1))
        return SnapshotChoice(
            chosen,
            SourceReason.AMBIGUOUS_REVISION if different is not None and different > 1 else None,
        )

    def _selection(
        self,
        session: Session,
        owner: UUID,
        provider: UUID,
        series: UUID | None,
        choice: SnapshotChoice,
        pair: tuple[str, str] | None,
        cutoff: datetime | None,
    ) -> UUID:
        snapshot = choice.snapshot
        retrieval = None if snapshot is None else self._retrieval(session, snapshot, cutoff=cutoff)
        key = digest(
            (
                provider,
                series,
                choice.reason,
                None if snapshot is None else snapshot.id,
                None if retrieval is None else retrieval.id,
                pair,
            )
        )
        row = session.scalar(
            select(SourceStatusSelectionModel).where(
                SourceStatusSelectionModel.owner_id == owner,
                SourceStatusSelectionModel.selection_digest == key,
            )
        )
        if row is None:
            row = SourceStatusSelectionModel(
                id=uuid4(),
                owner_id=owner,
                selection_digest=key,
                selection_reason=None if choice.reason is None else choice.reason.value,
                provider_id=provider,
                series_id=series,
                retrieval_id=None if retrieval is None else UUID(retrieval.id),
                base=None if pair is None else pair[0],
                quote=None if pair is None else pair[1],
                **({} if snapshot is None else {self._snapshot_reference(snapshot): snapshot.id}),
            )
            session.add(row)
            session.flush()
        return row.id

    def _summary(
        self, session: Session, selection: SourceStatusSelectionModel
    ) -> tuple[app.SourceSnapshotSummaryView | None, SourceAvailability, SourceReason | None]:
        provider = self._owned(
            session, selection.owner_id, MarketDataProviderModel, selection.provider_id
        )
        if selection.selection_reason is not None:
            return None, SourceAvailability.UNAVAILABLE, SourceReason(selection.selection_reason)
        if provider.configuration_state != "configured":
            return None, SourceAvailability.UNAVAILABLE, SourceReason.NOT_CONFIGURED
        row: SourceSnapshotFields | None = None
        for model, identifier in (
            (PriceSnapshotModel, selection.price_snapshot_id),
            (FxSnapshotModel, selection.fx_snapshot_id),
            (BenchmarkSnapshotModel, selection.benchmark_snapshot_id),
        ):
            if identifier is not None:
                row = self._owned(session, selection.owner_id, model, identifier)
                break
        if row is None:
            return None, SourceAvailability.UNAVAILABLE, SourceReason.NO_OBSERVATIONS
        try:
            self._snapshot_permit(session, row)
        except app.SourceServiceError:
            return (
                None,
                SourceAvailability.UNAVAILABLE,
                SourceReason.EXPIRED
                if row.expires_at <= self._now()
                else SourceReason.LICENSE_DENIED,
            )
        reason = None if row.reason is None else SourceReason(row.reason)
        quality = row.quality
        from trading212_domain import QualityState

        summary = app.SourceSnapshotSummaryView(
            id=str(row.id),
            freshness=self._freshness(session, row),
            content_digest=row.content_digest,
            period=SourcePeriod(start=row.period_start, end=row.period_end),
            first_observed_at=row.first_observed_at,
            effective_at=row.effective_at,
            latest_retrieval=self._retrieval(session, row, identifier=selection.retrieval_id),
            expected_count=row.expected_count,
            available_count=row.available_count,
            quality=QualityState(quality),
            reason=reason,
        )
        state = (
            SourceAvailability.AVAILABLE
            if quality == "fresh"
            else SourceAvailability.PARTIAL
            if row.available_count
            else SourceAvailability.UNAVAILABLE
        )
        return summary, state, reason

    def _series_status(
        self,
        session: Session,
        principal: Principal,
        owner: UUID,
        account_id: str,
        query: app.SourceStatusQuery,
        *,
        kind: str,
    ) -> tuple[tuple[app.ProviderStatusView, ...], Page[app.SourceSeriesStatusView]]:
        account = self._account(session, principal, account_id)
        providers = self._providers(session, owner, query.provider_id)
        if query.source_id is not None:
            source = self._owned(session, owner, MarketSourceSeriesModel, query.source_id)
            if source.kind != kind or (
                query.provider_id is not None and str(source.provider_id) != query.provider_id
            ):
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
        resource = (
            CollectionSnapshotResource.MARKET_SOURCE_STATUS
            if kind == "security_price"
            else CollectionSnapshotResource.BENCHMARK_SOURCE_STATUS
        )
        definition = CollectionSnapshotDefinition(
            resource,
            owner,
            account,
            collection_filter_fingerprint(
                query.provider_id,
                query.source_id,
                query.currency,
                query.basis,
                query.search,
                query.period,
                query.source_cutoff_at,
                query.sort,
            ),
        )
        ids: tuple[UUID, ...] = ()
        if query.cursor is None:
            statement = select(MarketSourceSeriesModel).where(
                MarketSourceSeriesModel.owner_id == owner, MarketSourceSeriesModel.kind == kind
            )
            for field, value in (
                ("provider_id", query.provider_id),
                ("id", query.source_id),
                ("currency", None if query.currency is None else query.currency.value),
                ("basis", None if query.basis is None else query.basis.value),
            ):
                if value is not None:
                    statement = statement.where(
                        getattr(MarketSourceSeriesModel, field)
                        == (UUID(value) if field in {"provider_id", "id"} else value)
                    )
            if query.search:
                statement = statement.where(
                    MarketSourceSeriesModel.provider_key.icontains(query.search, autoescape=True)
                )
            entries = session.scalars(
                statement.order_by(
                    MarketSourceSeriesModel.provider_key, MarketSourceSeriesModel.id
                ).limit(self._member_quota + 1)
            )
            model = PriceSnapshotModel if kind == "security_price" else BenchmarkSnapshotModel
            ids = tuple(
                self._selection(
                    session,
                    owner,
                    row.provider_id,
                    row.id,
                    self._select_snapshot(
                        session,
                        owner,
                        model,
                        series=row.id,
                        provider=row.provider_id,
                        period=query.period,
                        cutoff=query.source_cutoff_at,
                    ),
                    None,
                    query.source_cutoff_at,
                )
                for row in entries
            )
        page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
        views = []
        for identifier in page.record_ids:
            selection = self._owned(session, owner, SourceStatusSelectionModel, identifier)
            assert selection.series_id is not None
            summary, state, reason = self._summary(session, selection)
            views.append(
                app.SourceSeriesStatusView(
                    series=self._series_view(session, owner, selection.series_id),
                    latest_snapshot=summary,
                    availability=state,
                    reason=reason,
                )
            )
        return providers, Page(tuple(views), page.next_cursor, page.limit, page.exact_total)

    async def get_market_source_status(
        self, principal: Principal, account_id: str, *, query: app.SourceStatusQuery
    ) -> app.MarketSourceStatusView:
        def operation(session: Session, owner: UUID) -> app.MarketSourceStatusView:
            providers, series = self._series_status(
                session, principal, owner, account_id, query, kind="security_price"
            )
            return app.MarketSourceStatusView(
                account_id=account_id, providers=providers, series=series
            )

        return await self._run(principal, operation)

    async def get_benchmark_source_status(
        self, principal: Principal, account_id: str, *, query: app.SourceStatusQuery
    ) -> app.BenchmarkSourceStatusView:
        def operation(session: Session, owner: UUID) -> app.BenchmarkSourceStatusView:
            providers, series = self._series_status(
                session, principal, owner, account_id, query, kind="benchmark_level"
            )
            return app.BenchmarkSourceStatusView(
                account_id=account_id, providers=providers, series=series
            )

        return await self._run(principal, operation)

    async def get_fx_source_status(
        self, principal: Principal, account_id: str, *, query: app.FxSourceStatusQuery
    ) -> app.FxSourceStatusView:
        def operation(session: Session, owner: UUID) -> app.FxSourceStatusView:
            account = self._account(session, principal, account_id)
            providers = self._providers(session, owner, query.provider_id)
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.FX_SOURCE_STATUS,
                owner,
                account,
                collection_filter_fingerprint(
                    query.provider_id,
                    query.base,
                    query.quote,
                    query.period,
                    query.source_cutoff_at,
                    query.sort,
                ),
            )
            ids: tuple[UUID, ...] = ()
            if query.cursor is None:
                observed = (
                    select(
                        FxSnapshotModel.provider_id.label("provider_id"),
                        FxObservationModel.base.label("base"),
                        FxObservationModel.quote.label("quote"),
                    )
                    .join(FxObservationModel, FxObservationModel.snapshot_id == FxSnapshotModel.id)
                    .where(FxSnapshotModel.owner_id == owner)
                )
                missing = (
                    select(
                        FxSnapshotModel.provider_id.label("provider_id"),
                        func.split_part(SourceCoverageGapModel.source_key, ":", 1).label("base"),
                        func.split_part(SourceCoverageGapModel.source_key, ":", 2).label("quote"),
                    )
                    .join(
                        SourceCoverageGapModel,
                        SourceCoverageGapModel.fx_snapshot_id == FxSnapshotModel.id,
                    )
                    .where(
                        FxSnapshotModel.owner_id == owner,
                        SourceCoverageGapModel.source_key.op("~")("^[A-Z]{3}:[A-Z]{3}$"),
                    )
                )
                catalog = observed.union(missing).subquery()
                statement = select(catalog.c.provider_id, catalog.c.base, catalog.c.quote)
                if query.provider_id is not None:
                    statement = statement.where(catalog.c.provider_id == UUID(query.provider_id))
                if query.base is not None and query.quote is not None:
                    statement = statement.where(
                        catalog.c.base == query.base.value, catalog.c.quote == query.quote.value
                    )
                pairs = session.execute(
                    statement.order_by(
                        catalog.c.base, catalog.c.quote, catalog.c.provider_id
                    ).limit(self._member_quota + 1)
                )
                ids = tuple(
                    self._selection(
                        session,
                        owner,
                        provider,
                        None,
                        self._select_snapshot(
                            session,
                            owner,
                            FxSnapshotModel,
                            series=None,
                            provider=provider,
                            period=query.period,
                            cutoff=query.source_cutoff_at,
                            pair=(base, quote),
                        ),
                        (base, quote),
                        query.source_cutoff_at,
                    )
                    for provider, base, quote in pairs
                )
            page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
            views = []
            from trading212_domain import CurrencyCode

            for identifier in page.record_ids:
                selected = self._owned(session, owner, SourceStatusSelectionModel, identifier)
                summary, state, reason = self._summary(session, selected)
                assert selected.base is not None and selected.quote is not None
                license = self._current_license(session, owner, selected.provider_id)
                if license is None:
                    raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
                views.append(
                    app.FxPairStatusView(
                        provider_id=str(selected.provider_id),
                        license_version_id=license.id,
                        base=CurrencyCode(selected.base),
                        quote=CurrencyCode(selected.quote),
                        latest_snapshot=summary,
                        availability=state,
                        reason=reason,
                    )
                )
            return app.FxSourceStatusView(
                account_id=account_id,
                providers=providers,
                pairs=Page(tuple(views), page.next_cursor, page.limit, page.exact_total),
            )

        return await self._run(principal, operation)
