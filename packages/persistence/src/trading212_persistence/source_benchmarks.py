"""Immutable benchmark definitions and versions over authorized source catalog IDs."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application import sources as app
from trading212_application.views import Page
from trading212_domain import CurrencyCode
from trading212_domain.sources import (
    BenchmarkComponent,
    BenchmarkContent,
    BenchmarkNormalizationAdjustment,
    BenchmarkRebalanceRule,
    PriceBasis,
    SourceUse,
    normalize_benchmark_content,
)
from trading212_security.principals import Principal

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    collection_filter_fingerprint,
)
from .source_models import (
    BenchmarkComponentModel,
    BenchmarkDefinitionModel,
    BenchmarkVersionModel,
    MarketSourceSeriesModel,
    SourceCalendarModel,
    SourceCommandIdentityModel,
    SourceCommandVersionModel,
)
from .source_store import SourceStore, digest, error


class SourceBenchmarks(SourceStore):
    def _definition_summary(
        self, session: Session, row: BenchmarkDefinitionModel
    ) -> app.BenchmarkDefinitionSummaryView:
        latest = session.scalar(
            select(BenchmarkVersionModel)
            .where(BenchmarkVersionModel.definition_id == row.id)
            .order_by(BenchmarkVersionModel.version_number.desc())
            .limit(1)
        )
        count = session.scalar(
            select(func.count())
            .select_from(BenchmarkVersionModel)
            .where(BenchmarkVersionModel.definition_id == row.id)
        )
        return app.BenchmarkDefinitionSummaryView(
            id=str(row.id),
            name=row.name,
            reporting_currency=CurrencyCode(row.reporting_currency),
            revision=row.revision,
            state=app.BenchmarkDefinitionState.ARCHIVED
            if row.archived
            else app.BenchmarkDefinitionState.ACTIVE,
            created_at=row.created_at,
            updated_at=row.updated_at,
            latest_version_id=None if latest is None else str(latest.id),
            version_count=int(count or 0),
        )

    def _benchmark_version(
        self, session: Session, owner: UUID, identifier: UUID
    ) -> app.BenchmarkVersionView:
        row = self._owned(session, owner, BenchmarkVersionModel, identifier)
        calendar = self._owned(session, owner, SourceCalendarModel, row.calendar_id)
        components = tuple(
            session.scalars(
                select(BenchmarkComponentModel)
                .where(BenchmarkComponentModel.version_id == row.id)
                .order_by(BenchmarkComponentModel.source_id)
            )
        )
        for component in components:
            source = self._owned(session, owner, MarketSourceSeriesModel, component.source_id)
            self._permit(session, owner, source.license_version_id, SourceUse.DISPLAY)
        content = BenchmarkContent(
            reporting_currency=CurrencyCode(row.reporting_currency),
            effective_at=row.effective_at,
            return_basis=PriceBasis(row.basis),
            calendar_id=calendar.key,
            calendar_version=calendar.version,
            rebalance_rule=BenchmarkRebalanceRule(row.rebalance),
            components=tuple(
                BenchmarkComponent(source_id=str(x.source_id), weight=x.weight) for x in components
            ),
        )
        adjustments = tuple(
            BenchmarkNormalizationAdjustment(
                source_id=str(x.source_id),
                original_weight=x.original_weight,
                normalized_weight=x.weight,
            )
            for x in components
            if x.original_weight is not None
        )
        return app.BenchmarkVersionView(
            id=str(row.id),
            definition_id=str(row.definition_id),
            version_number=row.version_number,
            content=content,
            content_digest=row.content_digest,
            published_at=row.published_at,
            normalization_adjustments=adjustments,
        )

    def _definition_detail(
        self,
        session: Session,
        owner: UUID,
        row: BenchmarkDefinitionModel,
        query: app.BenchmarkDetailQuery,
    ) -> app.BenchmarkDefinitionDetailView:
        selected = None
        if query.selected_version_id is not None:
            version = self._owned(session, owner, BenchmarkVersionModel, query.selected_version_id)
            if version.definition_id != row.id:
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            selected = self._benchmark_version(session, owner, version.id)
        definition = CollectionSnapshotDefinition(
            CollectionSnapshotResource.BENCHMARK_VERSIONS,
            owner,
            None,
            collection_filter_fingerprint(row.id, query.selected_version_id),
        )
        ids = (
            ()
            if query.cursor
            else tuple(
                session.scalars(
                    select(BenchmarkVersionModel.id)
                    .where(BenchmarkVersionModel.definition_id == row.id)
                    .order_by(BenchmarkVersionModel.version_number.desc())
                    .limit(self._member_quota + 1)
                )
            )
        )
        page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
        items = tuple(self._benchmark_version(session, owner, x) for x in page.record_ids)
        if selected is None and items:
            selected = items[0]
        return app.BenchmarkDefinitionDetailView(
            definition=self._definition_summary(session, row),
            versions=Page(items, page.next_cursor, page.limit, page.exact_total),
            selected_version=selected,
        )

    async def list_benchmark_definitions(
        self, principal: Principal, *, query: app.BenchmarkDefinitionQuery
    ) -> Page[app.BenchmarkDefinitionSummaryView]:
        def operation(session: Session, owner: UUID) -> Page[app.BenchmarkDefinitionSummaryView]:
            resource = (
                CollectionSnapshotResource.BENCHMARK_DEFINITIONS_NAME
                if query.sort is app.BenchmarkSort.NAME_ASC
                else CollectionSnapshotResource.BENCHMARK_DEFINITIONS_CREATED
            )
            definition = CollectionSnapshotDefinition(
                resource,
                owner,
                None,
                collection_filter_fingerprint(query.state, query.search, query.sort),
            )
            ids: tuple[UUID, ...] = ()
            if query.cursor is None:
                statement = select(BenchmarkDefinitionModel.id).where(
                    BenchmarkDefinitionModel.owner_id == owner
                )
                if query.state is not app.BenchmarkStateFilter.ALL:
                    statement = statement.where(
                        BenchmarkDefinitionModel.archived
                        == (query.state is app.BenchmarkStateFilter.ARCHIVED)
                    )
                if query.search:
                    statement = statement.where(
                        BenchmarkDefinitionModel.name.icontains(query.search, autoescape=True)
                    )
                ordering = (
                    (func.lower(BenchmarkDefinitionModel.name), BenchmarkDefinitionModel.id)
                    if query.sort is app.BenchmarkSort.NAME_ASC
                    else (
                        BenchmarkDefinitionModel.created_at.desc(),
                        BenchmarkDefinitionModel.id.desc(),
                    )
                )
                ids = tuple(
                    session.scalars(statement.order_by(*ordering).limit(self._member_quota + 1))
                )
            page = self._page(session, definition, ids, cursor=query.cursor, limit=query.limit)
            return Page(
                tuple(
                    self._definition_summary(
                        session, self._owned(session, owner, BenchmarkDefinitionModel, x)
                    )
                    for x in page.record_ids
                ),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._run(principal, operation)

    async def get_benchmark_definition(
        self, principal: Principal, definition_id: str, *, query: app.BenchmarkDetailQuery
    ) -> app.BenchmarkDefinitionDetailView:
        return await self._run(
            principal,
            lambda session, owner: self._definition_detail(
                session,
                owner,
                self._owned(session, owner, BenchmarkDefinitionModel, definition_id),
                query,
            ),
        )

    def _validate_benchmark_sources(
        self, session: Session, owner: UUID, content: BenchmarkContent
    ) -> UUID:
        calendar = session.scalar(
            select(SourceCalendarModel).where(
                SourceCalendarModel.owner_id == owner,
                SourceCalendarModel.key == content.calendar_id,
                SourceCalendarModel.version == content.calendar_version,
            )
        )
        if calendar is None:
            raise error(app.SourceServiceErrorCode.NOT_FOUND)
        for component in content.components:
            series = self._owned(session, owner, MarketSourceSeriesModel, component.source_id)
            self._permit(session, owner, series.license_version_id, SourceUse.DISPLAY)
            if series.basis != content.return_basis.value or series.calendar_id != calendar.id:
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        return calendar.id

    def _publish_benchmark(
        self,
        session: Session,
        owner: UUID,
        definition: BenchmarkDefinitionModel,
        content: BenchmarkContent,
        normalize: bool,
    ) -> BenchmarkVersionModel:
        calendar = self._validate_benchmark_sources(session, owner, content)
        validated = normalize_benchmark_content(content, normalize=normalize)
        content = validated.content
        if content.reporting_currency.value != definition.reporting_currency:
            raise error(app.SourceServiceErrorCode.CURRENCY_MISMATCH)
        number = (
            int(
                session.scalar(
                    select(func.coalesce(func.max(BenchmarkVersionModel.version_number), 0)).where(
                        BenchmarkVersionModel.definition_id == definition.id
                    )
                )
                or 0
            )
            + 1
        )
        row = BenchmarkVersionModel(
            id=uuid4(),
            owner_id=owner,
            definition_id=definition.id,
            version_number=number,
            reporting_currency=content.reporting_currency.value,
            effective_at=content.effective_at,
            published_at=self._now(),
            basis=content.return_basis.value,
            rebalance=content.rebalance_rule.value,
            calendar_id=calendar,
            content_digest=digest(content),
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        originals = {x.source_id: x.original_weight for x in validated.adjustments}
        session.add_all(
            BenchmarkComponentModel(
                owner_id=owner,
                version_id=row.id,
                source_id=UUID(x.source_id),
                weight=x.weight,
                original_weight=originals.get(x.source_id),
                created_at=self._now(),
            )
            for x in content.components
        )
        session.flush()
        return row

    @staticmethod
    def _precondition(row: BenchmarkDefinitionModel, if_match: str | None) -> None:
        if if_match is None:
            raise error(app.SourceServiceErrorCode.REVISION_REQUIRED)
        from trading212_application.targets import target_etag

        if if_match != target_etag(str(row.id), row.revision):
            raise error(app.SourceServiceErrorCode.REVISION_MISMATCH)

    def _command_detail(
        self,
        session: Session,
        owner: UUID,
        row: BenchmarkDefinitionModel,
        command: SourceCommandIdentityModel,
    ) -> app.BenchmarkDefinitionDetailView:
        assert (
            command.result_revision is not None
            and command.response_total is not None
            and command.response_updated_at is not None
        )
        retained = tuple(
            session.scalars(
                select(SourceCommandVersionModel)
                .where(SourceCommandVersionModel.command_id == command.id)
                .order_by(SourceCommandVersionModel.ordinal)
            )
        )
        versions = tuple(self._benchmark_version(session, owner, x.version_id) for x in retained)
        selected = (
            None
            if command.response_selected_version_id is None
            else self._benchmark_version(session, owner, command.response_selected_version_id)
        )
        latest = next((x for x in versions if x.version_number == command.response_total), None)
        summary = app.BenchmarkDefinitionSummaryView(
            id=str(row.id),
            name=row.name,
            reporting_currency=CurrencyCode(row.reporting_currency),
            revision=command.result_revision,
            state=app.BenchmarkDefinitionState.ARCHIVED
            if command.response_archived
            else app.BenchmarkDefinitionState.ACTIVE,
            created_at=row.created_at,
            updated_at=command.response_updated_at,
            latest_version_id=None if latest is None else latest.id,
            version_count=command.response_total,
        )
        return app.BenchmarkDefinitionDetailView(
            definition=summary,
            versions=Page(versions, command.response_next_cursor, 25, command.response_total),
            selected_version=selected,
        )

    async def create_benchmark_definition(
        self,
        principal: Principal,
        command: app.CreateBenchmarkDefinitionCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.BenchmarkDefinitionDetailView:
        def operation(session: Session, owner: UUID) -> app.BenchmarkDefinitionDetailView:
            self._validate_benchmark_sources(session, owner, command.content)
            replay, fingerprint = self._replay(
                session, owner, "definition.create", idempotency_key, command
            )
            if replay is not None:
                version = self._owned(session, owner, BenchmarkVersionModel, replay.result_id)
                return self._command_detail(
                    session,
                    owner,
                    self._owned(session, owner, BenchmarkDefinitionModel, version.definition_id),
                    replay,
                )
            row = BenchmarkDefinitionModel(
                id=uuid4(),
                owner_id=owner,
                name=command.name,
                reporting_currency=command.content.reporting_currency.value,
                revision=1,
                archived=False,
                created_at=self._now(),
                updated_at=self._now(),
            )
            session.add(row)
            session.flush()
            version = self._publish_benchmark(
                session, owner, row, command.content, command.normalize
            )
            response = self._definition_detail(
                session, owner, row, app.BenchmarkDetailQuery(selected_version_id=str(version.id))
            )
            self._record(
                session,
                principal,
                "definition.create",
                idempotency_key,
                fingerprint,
                version.id,
                correlation_id,
                row.revision,
                response=response,
            )
            return response

        return await self._run(principal, operation, write=True)

    async def create_benchmark_version(
        self,
        principal: Principal,
        definition_id: str,
        command: app.CreateBenchmarkVersionCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.BenchmarkDefinitionDetailView:
        def operation(session: Session, owner: UUID) -> app.BenchmarkDefinitionDetailView:
            row = self._owned(session, owner, BenchmarkDefinitionModel, definition_id)
            self._validate_benchmark_sources(session, owner, command.content)
            replay, fingerprint = self._replay(
                session, owner, "definition.version", idempotency_key, (row.id, command)
            )
            if replay is not None:
                return self._command_detail(session, owner, row, replay)
            self._precondition(row, if_match)
            if row.archived:
                raise error(app.SourceServiceErrorCode.INVALID_STATE_TRANSITION)
            version = self._publish_benchmark(
                session, owner, row, command.content, command.normalize
            )
            row.revision += 1
            row.updated_at = self._now()
            session.flush()
            response = self._definition_detail(
                session, owner, row, app.BenchmarkDetailQuery(selected_version_id=str(version.id))
            )
            self._record(
                session,
                principal,
                "definition.version",
                idempotency_key,
                fingerprint,
                version.id,
                correlation_id,
                row.revision,
                response=response,
            )
            return response

        return await self._run(principal, operation, write=True)

    async def archive_benchmark_definition(
        self,
        principal: Principal,
        definition_id: str,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.BenchmarkDefinitionDetailView:
        def operation(session: Session, owner: UUID) -> app.BenchmarkDefinitionDetailView:
            row = self._owned(session, owner, BenchmarkDefinitionModel, definition_id)
            replay, fingerprint = self._replay(
                session, owner, "definition.archive", idempotency_key, row.id
            )
            if replay is None:
                self._precondition(row, if_match)
                if row.archived:
                    raise error(app.SourceServiceErrorCode.INVALID_STATE_TRANSITION)
                row.archived = True
                row.revision += 1
                row.updated_at = self._now()
                session.flush()
                response = self._definition_detail(session, owner, row, app.BenchmarkDetailQuery())
                self._record(
                    session,
                    principal,
                    "definition.archive",
                    idempotency_key,
                    fingerprint,
                    row.id,
                    correlation_id,
                    row.revision,
                    response=response,
                )
                return response
            return self._command_detail(session, owner, row, replay)

        return await self._run(principal, operation, write=True)
