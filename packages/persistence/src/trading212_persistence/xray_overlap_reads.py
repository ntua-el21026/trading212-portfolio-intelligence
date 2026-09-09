"""Collection-owned overlap projections from retained canonical compositions."""

from __future__ import annotations

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_analytics.xray import (
    calculate_common_entities,
    calculate_overlap_pairs,
    project_common_entities_top,
)
from trading212_application import xray as app
from trading212_application.views import Page
from trading212_domain.xray_codec import encode_xray_component
from trading212_domain.xray_result import (
    CanonicalCommonEntity,
    CanonicalFundPair,
    CanonicalOverlapPair,
)
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotPage, CollectionSnapshotResource
from .xray_base import xray_error
from .xray_collections import cursor_parent, generated_page, retained_first_page
from .xray_read_store import XrayReadStore, component, run_definition
from .xray_run_models import EtfOverlapEntityModel, EtfOverlapPairModel, XrayFundCompositionModel
from .xray_store_contract import XrayRunHandle
from .xray_views import common_entity_view, pair_view


def pair_id(namespace: UUID, pair: CanonicalFundPair) -> UUID:
    return uuid5(namespace, f"pair:{pair.first_fund_id}:{pair.second_fund_id}")


class XrayOverlapReads(XrayReadStore):
    async def get_etf_overlap(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: app.EtfOverlapQuery,
    ) -> app.EtfOverlapView:
        def read(session: Session, owner: UUID) -> app.EtfOverlapView:
            account = self._xray_account(session, principal, account_id)
            options = query.options
            if isinstance(options, app.McpTopPair):
                handle = self._resolve_xray_run(session, principal, account, query.request)
                result = self._load_xray_result(session, principal, account, handle)
                pair = CanonicalFundPair(UUID(options.left_fund_id), UUID(options.right_fund_id))
                self._composition_ids(
                    session, owner, handle, (pair.first_fund_id, pair.second_fund_id)
                )
                common = calculate_common_entities(result, pair)
                top = project_common_entities_top(common, options.top_n)
                header = self._pair_view(
                    session,
                    owner,
                    handle,
                    common.pair,
                    identifier=pair_id(handle.run_id, pair),
                    held={},
                )
                return app.McpTopPairView(
                    context=handle.context,
                    summary=handle.summary,
                    pair=header,
                    common_entities=tuple(
                        common_entity_view(
                            value,
                            identifier=uuid5(pair_id(handle.run_id, pair), str(value.entity_id)),
                            name=self._entity_name(session, owner, handle, value.entity_id),
                        )
                        for value in top.items
                    ),
                    total_count=top.total_count,
                    returned_count=top.returned_count,
                    omitted_count=top.omitted_count,
                    omitted_common_weight=top.omitted_common_weight,
                )
            resource = (
                CollectionSnapshotResource.XRAY_PAIRS
                if isinstance(options, app.Pairs)
                else CollectionSnapshotResource.XRAY_COMMON_ENTITIES
            )
            definition = run_definition(owner, account, query.request, options, resource)
            binding = (
                None
                if query.cursor is None
                else cursor_parent(session, self._cursors, definition, query.cursor)
            )
            if binding is not None and binding.run_id is None:
                raise xray_error(app.XrayServiceErrorCode.VALIDATION_FAILED)
            handle = self._resolve_xray_run(
                session,
                principal,
                account,
                query.request,
                retained_run_id=None if binding is None else binding.run_id,
            )
            compositions = self._composition_ids(
                session, owner, handle, tuple(UUID(value) for value in options.fund_ids)
            )
            store = self._store(session)
            page = (
                store.resume(definition, query.cursor, limit=query.limit)
                if query.cursor is not None
                else retained_first_page(
                    session,
                    store,
                    definition,
                    run_id=handle.run_id,
                    source_id=None,
                    limit=query.limit,
                )
            )
            if page is None:
                storage_licenses = self._xray_storage_licenses(session, owner, handle)
                expires_at = self._xray_storage_expires_at(session, owner, handle.input_id)
                self._permit_xray_storage_licenses(
                    session, owner, storage_licenses, expires_at=expires_at
                )
                result = self._load_xray_result(session, principal, account, handle)
                if isinstance(options, app.Pairs):
                    pairs = calculate_overlap_pairs(
                        result, tuple(UUID(value) for value in options.fund_ids)
                    )

                    def create_pairs(collection: UUID) -> tuple[UUID, ...]:
                        self._permit_xray_storage_licenses(
                            session, owner, storage_licenses, expires_at=expires_at
                        )
                        identifiers = []
                        for ordinal, value in enumerate(pairs):
                            identifier = pair_id(collection, value.pair)
                            session.add(
                                EtfOverlapPairModel(
                                    id=identifier,
                                    owner_id=owner,
                                    collection_id=collection,
                                    run_id=handle.run_id,
                                    left_composition_id=compositions[value.pair.first_fund_id],
                                    right_composition_id=compositions[value.pair.second_fund_id],
                                    ordinal=ordinal,
                                    canonical_payload=encode_xray_component(value),
                                )
                            )
                            identifiers.append(identifier)
                        session.flush()
                        return tuple(identifiers)

                    page = generated_page(
                        session,
                        store,
                        definition,
                        run_id=handle.run_id,
                        source_id=None,
                        exact_total=len(pairs),
                        create_records=create_pairs,
                        limit=query.limit,
                    )
                else:
                    pair = CanonicalFundPair(
                        UUID(options.left_fund_id), UUID(options.right_fund_id)
                    )
                    common = calculate_common_entities(result, pair)

                    def create_common(collection: UUID) -> tuple[UUID, ...]:
                        self._permit_xray_storage_licenses(
                            session, owner, storage_licenses, expires_at=expires_at
                        )
                        identifier = pair_id(collection, pair)
                        session.add(
                            EtfOverlapPairModel(
                                id=identifier,
                                owner_id=owner,
                                collection_id=collection,
                                run_id=handle.run_id,
                                left_composition_id=compositions[pair.first_fund_id],
                                right_composition_id=compositions[pair.second_fund_id],
                                ordinal=0,
                                canonical_payload=encode_xray_component(common.pair),
                            )
                        )
                        session.flush()
                        identifiers = []
                        for ordinal, value in enumerate(common.entities):
                            entity_id = uuid5(identifier, str(value.entity_id))
                            session.add(
                                EtfOverlapEntityModel(
                                    id=entity_id,
                                    owner_id=owner,
                                    collection_id=collection,
                                    pair_id=identifier,
                                    entity_id=value.entity_id,
                                    ordinal=ordinal,
                                    canonical_payload=encode_xray_component(value),
                                )
                            )
                            identifiers.append(entity_id)
                        session.flush()
                        return tuple(identifiers)

                    page = generated_page(
                        session,
                        store,
                        definition,
                        run_id=handle.run_id,
                        source_id=None,
                        exact_total=len(common.entities),
                        create_records=create_common,
                        limit=query.limit,
                    )
                self._permit_xray_storage_licenses(
                    session, owner, storage_licenses, expires_at=expires_at
                )
            if isinstance(options, app.Pairs):
                return app.OverlapPairsView(
                    context=handle.context,
                    summary=handle.summary,
                    selected_fund_ids=options.fund_ids,
                    pairs=self._pairs_page(session, owner, handle, page, compositions),
                )
            return self._common_page(session, owner, handle, options, page, compositions)

        return await self._read_xray(principal, read)

    def _composition_ids(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        funds: tuple[UUID, ...],
    ) -> dict[UUID, UUID]:
        rows = session.execute(
            select(XrayFundCompositionModel.instrument_id, XrayFundCompositionModel.id).where(
                XrayFundCompositionModel.owner_id == owner,
                XrayFundCompositionModel.run_id == handle.run_id,
                XrayFundCompositionModel.instrument_id.in_(funds),
            )
        ).all()
        values = {instrument: identifier for instrument, identifier in rows}
        if set(values) != set(funds):
            raise xray_error(app.XrayServiceErrorCode.VALIDATION_FAILED)
        return values

    def _pair_view(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        value: CanonicalOverlapPair,
        *,
        identifier: UUID,
        held: dict[UUID, app.XrayHeldFundView],
    ) -> app.XrayOverlapPairView:
        if value.result_digest != handle.context.content_digest:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        for instrument in (value.pair.first_fund_id, value.pair.second_fund_id):
            if instrument not in held:
                held[instrument] = self._held_view(session, owner, handle, instrument)
        return pair_view(
            value,
            identifier=identifier,
            left=held[value.pair.first_fund_id],
            right=held[value.pair.second_fund_id],
            common_entity_count=value.common_entity_count,
        )

    def _checked_pair(
        self,
        row: EtfOverlapPairModel,
        handle: XrayRunHandle,
        compositions: dict[UUID, UUID],
    ) -> CanonicalOverlapPair:
        value = component(row.canonical_payload, CanonicalOverlapPair)
        if (
            row.run_id != handle.run_id
            or compositions.get(value.pair.first_fund_id) != row.left_composition_id
            or compositions.get(value.pair.second_fund_id) != row.right_composition_id
        ):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        return value

    def _pairs_page(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        page: CollectionSnapshotPage,
        compositions: dict[UUID, UUID],
    ) -> Page[app.XrayOverlapPairView]:
        by_id = {
            row.id: row
            for row in session.scalars(
                select(EtfOverlapPairModel).where(
                    EtfOverlapPairModel.owner_id == owner,
                    EtfOverlapPairModel.collection_id == page.snapshot_id,
                    EtfOverlapPairModel.run_id == handle.run_id,
                    EtfOverlapPairModel.id.in_(page.record_ids),
                )
            )
        }
        if set(by_id) != set(page.record_ids):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        held: dict[UUID, app.XrayHeldFundView] = {}
        return Page(
            items=tuple(
                self._pair_view(
                    session,
                    owner,
                    handle,
                    self._checked_pair(by_id[identifier], handle, compositions),
                    identifier=identifier,
                    held=held,
                )
                for identifier in page.record_ids
            ),
            next_cursor=page.next_cursor,
            limit=page.limit,
            total=page.exact_total,
        )

    def _common_page(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        options: app.CommonEntities,
        page: CollectionSnapshotPage,
        compositions: dict[UUID, UUID],
    ) -> app.CommonEntitiesView:
        pair_rows = tuple(
            session.scalars(
                select(EtfOverlapPairModel)
                .where(
                    EtfOverlapPairModel.owner_id == owner,
                    EtfOverlapPairModel.collection_id == page.snapshot_id,
                    EtfOverlapPairModel.run_id == handle.run_id,
                )
                .limit(2)
            )
        )
        if len(pair_rows) != 1:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        row = pair_rows[0]
        value = self._checked_pair(row, handle, compositions)
        if value.pair != CanonicalFundPair(UUID(options.left_fund_id), UUID(options.right_fund_id)):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        header = self._pair_view(session, owner, handle, value, identifier=row.id, held={})
        by_id = {
            item.id: item
            for item in session.scalars(
                select(EtfOverlapEntityModel).where(
                    EtfOverlapEntityModel.owner_id == owner,
                    EtfOverlapEntityModel.collection_id == page.snapshot_id,
                    EtfOverlapEntityModel.pair_id == row.id,
                    EtfOverlapEntityModel.id.in_(page.record_ids),
                )
            )
        }
        if set(by_id) != set(page.record_ids) or page.exact_total != value.common_entity_count:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        items = []
        for identifier in page.record_ids:
            stored = by_id[identifier]
            entity = component(stored.canonical_payload, CanonicalCommonEntity)
            if entity.entity_id != stored.entity_id:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            items.append(
                common_entity_view(
                    entity,
                    identifier=identifier,
                    name=self._entity_name(session, owner, handle, entity.entity_id),
                )
            )
        return app.CommonEntitiesView(
            context=handle.context,
            summary=handle.summary,
            selected_fund_ids=options.fund_ids,
            pair=header,
            common_entities=Page(
                items=tuple(items),
                next_cursor=page.next_cursor,
                limit=page.limit,
                total=page.exact_total,
            ),
        )
