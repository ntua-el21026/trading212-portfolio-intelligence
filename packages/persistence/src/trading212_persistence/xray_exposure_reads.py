"""Bounded effective exposure, full path proof and held-fund discovery reads."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import xray as app
from trading212_application.views import Page
from trading212_domain.xray import CashRoot, PositionRoot, XrayCash, XrayDimension, XrayPosition
from trading212_domain.xray_result import XrayExposureBucket, XrayTerminalPath
from trading212_security.principals import Principal

from .collection_snapshots import CollectionSnapshotPage, CollectionSnapshotResource
from .xray_base import xray_error
from .xray_collections import cursor_parent, generated_page, retained_first_page
from .xray_read_store import XrayReadStore, component, run_definition
from .xray_run_models import (
    XrayExposureModel,
    XrayExposurePathBucketModel,
    XrayExposurePathModel,
    XrayHeldFundModel,
    XrayInputCashModel,
    XrayInputPositionModel,
)
from .xray_store_contract import XrayRunHandle
from .xray_views import exposure_view, path_view, residual_view


class XrayExposureReads(XrayReadStore):
    async def get_effective_exposure(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: app.EffectiveExposureQuery,
    ) -> app.EffectiveExposureView:
        def read(session: Session, owner: UUID) -> app.EffectiveExposureView:
            account = self._xray_account(session, principal, account_id)
            options = query.options
            resource = (
                CollectionSnapshotResource.XRAY_EXPOSURES
                if isinstance(options, app.Exposures)
                else CollectionSnapshotResource.XRAY_PATHS
                if isinstance(options, app.Paths)
                else CollectionSnapshotResource.XRAY_HELD_FUNDS
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
            if isinstance(options, app.Paths) and options.exposure_id is not None:
                exposure = session.scalar(
                    select(XrayExposureModel.id).where(
                        XrayExposureModel.owner_id == owner,
                        XrayExposureModel.run_id == handle.run_id,
                        XrayExposureModel.id == UUID(options.exposure_id),
                        XrayExposureModel.dimension == options.dimension.value,
                    )
                )
                if exposure is None:
                    raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
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
                ids = self._exposure_members(session, owner, handle, options)
                licenses = self._xray_storage_licenses(session, owner, handle)
                expires_at = self._xray_storage_expires_at(session, owner, handle.input_id)
                # Ordered membership and its binding are new retained source copies.
                self._permit_xray_storage_licenses(session, owner, licenses, expires_at=expires_at)
                page = generated_page(
                    session,
                    store,
                    definition,
                    run_id=handle.run_id,
                    source_id=None,
                    exact_total=len(ids),
                    create_records=lambda _: ids,
                    limit=query.limit,
                )
                self._permit_xray_storage_licenses(session, owner, licenses, expires_at=expires_at)
            if isinstance(options, app.HeldFunds):
                rows = tuple(
                    session.scalars(
                        select(XrayHeldFundModel).where(
                            XrayHeldFundModel.owner_id == owner,
                            XrayHeldFundModel.run_id == handle.run_id,
                            XrayHeldFundModel.id.in_(page.record_ids),
                        )
                    )
                )
                by_id = {row.id: row for row in rows}
                if set(by_id) != set(page.record_ids):
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
                return app.HeldFundsView(
                    context=handle.context,
                    summary=handle.summary,
                    held_funds=Page(
                        items=tuple(
                            self._held_view(session, owner, handle, by_id[identifier].instrument_id)
                            for identifier in page.record_ids
                        ),
                        next_cursor=page.next_cursor,
                        limit=page.limit,
                        total=page.exact_total,
                    ),
                )
            dimension = self._dimension(session, owner, handle, options.dimension)
            residuals = tuple(
                residual_view(value)
                for value in self._residuals(
                    session, owner, handle.run_id, f"dimension:{options.dimension.value}"
                )
            )
            if isinstance(options, app.Exposures):
                return app.ExposuresView(
                    context=handle.context,
                    summary=handle.summary,
                    dimension_summary=dimension,
                    dimension_residuals=residuals,
                    normalized_known_only=options.normalized_known_only,
                    exposures=self._exposure_page(session, owner, handle, options, page),
                )
            return app.PathsView(
                context=handle.context,
                summary=handle.summary,
                dimension_summary=dimension,
                dimension_residuals=residuals,
                normalized_known_only=options.normalized_known_only,
                paths=self._path_page(session, owner, handle, options, page),
            )

        return await self._read_xray(principal, read)

    def _exposure_members(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        options: app.Exposures | app.Paths | app.HeldFunds,
    ) -> tuple[UUID, ...]:
        if isinstance(options, app.Exposures):
            query = (
                select(XrayExposureModel.id)
                .where(
                    XrayExposureModel.owner_id == owner,
                    XrayExposureModel.run_id == handle.run_id,
                    XrayExposureModel.dimension == options.dimension.value,
                )
                .order_by(XrayExposureModel.ordinal, XrayExposureModel.id)
            )
        elif isinstance(options, app.HeldFunds):
            query = (
                select(XrayHeldFundModel.id)
                .where(
                    XrayHeldFundModel.owner_id == owner,
                    XrayHeldFundModel.run_id == handle.run_id,
                )
                .order_by(XrayHeldFundModel.ordinal, XrayHeldFundModel.id)
            )
        else:
            query = (
                select(XrayExposurePathModel.id)
                .where(
                    XrayExposurePathModel.owner_id == owner,
                    XrayExposurePathModel.run_id == handle.run_id,
                )
                .order_by(XrayExposurePathModel.ordinal, XrayExposurePathModel.id)
            )
            if options.exposure_id is not None:
                query = query.join(
                    XrayExposurePathBucketModel,
                    XrayExposurePathBucketModel.path_id == XrayExposurePathModel.id,
                ).where(
                    XrayExposurePathBucketModel.owner_id == owner,
                    XrayExposurePathBucketModel.exposure_id == UUID(options.exposure_id),
                    XrayExposurePathBucketModel.dimension == options.dimension.value,
                )
        ids = tuple(session.scalars(query.limit(100_001)))
        if len(ids) > 100_000 or len(set(ids)) != len(ids):
            raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE)
        return ids

    def _exposure_page(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        options: app.Exposures,
        page: CollectionSnapshotPage,
    ) -> Page[app.XrayExposureRowView]:
        rows = tuple(
            session.scalars(
                select(XrayExposureModel).where(
                    XrayExposureModel.owner_id == owner,
                    XrayExposureModel.run_id == handle.run_id,
                    XrayExposureModel.dimension == options.dimension.value,
                    XrayExposureModel.id.in_(page.record_ids),
                )
            )
        )
        by_id = {row.id: row for row in rows}
        if set(by_id) != set(page.record_ids):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        values = []
        for identifier in page.record_ids:
            row = by_id[identifier]
            value = component(row.canonical_payload, XrayExposureBucket)
            if value.dimension is not options.dimension or value.bucket_key != row.bucket_key:
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            name = (
                self._entity_name(session, owner, handle, UUID(value.bucket_key))
                if value.dimension is XrayDimension.COMPANY
                else value.bucket_key
            )
            values.append(
                exposure_view(
                    value,
                    identifier=identifier,
                    name=name,
                    normalized=options.normalized_known_only,
                    residuals=self._residuals(
                        session,
                        owner,
                        handle.run_id,
                        f"bucket:{value.dimension.value}:{value.bucket_key}",
                    ),
                )
            )
        return Page(
            items=tuple(values),
            next_cursor=page.next_cursor,
            limit=page.limit,
            total=page.exact_total,
        )

    def _path_page(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        options: app.Paths,
        page: CollectionSnapshotPage,
    ) -> Page[app.XrayPathRowView]:
        query = select(XrayExposurePathModel).where(
            XrayExposurePathModel.owner_id == owner,
            XrayExposurePathModel.run_id == handle.run_id,
            XrayExposurePathModel.id.in_(page.record_ids),
        )
        if options.exposure_id is not None:
            query = query.join(
                XrayExposurePathBucketModel,
                XrayExposurePathBucketModel.path_id == XrayExposurePathModel.id,
            ).where(
                XrayExposurePathBucketModel.owner_id == owner,
                XrayExposurePathBucketModel.exposure_id == UUID(options.exposure_id),
                XrayExposurePathBucketModel.dimension == options.dimension.value,
            )
        by_id = {row.id: row for row in session.scalars(query)}
        if set(by_id) != set(page.record_ids):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        values = []
        for identifier in page.record_ids:
            row = by_id[identifier]
            value = component(row.canonical_payload, XrayTerminalPath)
            if (
                value.key != row.path_key
                or value.root_key != row.root_key
                or tuple(row.identity_decision_ids) != value.identity_decision_ids
                or tuple(row.source_reference_ids) != value.source_reference_ids
            ):
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            kind, _, root_id = value.root_key.partition(":")
            root: PositionRoot | CashRoot
            if kind == "position":
                payload = session.scalar(
                    select(XrayInputPositionModel.canonical_position).where(
                        XrayInputPositionModel.owner_id == owner,
                        XrayInputPositionModel.input_id == handle.input_id,
                        XrayInputPositionModel.position_id == UUID(root_id),
                    )
                )
                if payload is None:
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
                root = component(payload, XrayPosition).root
            else:
                payload = session.scalar(
                    select(XrayInputCashModel.canonical_cash).where(
                        XrayInputCashModel.owner_id == owner,
                        XrayInputCashModel.input_id == handle.input_id,
                        XrayInputCashModel.cash_id == UUID(root_id),
                    )
                )
                if payload is None:
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
                root = component(payload, XrayCash).root
            name = (
                self._entity_name(session, owner, handle, value.entity_id)
                if value.entity_id is not None
                else self._instrument_name(session, value.instrument_id)
                if value.instrument_id is not None
                else "Explicit cash"
                if value.explicit_cash
                else "Unresolved exposure"
            )
            sources = self._xray_source_views(session, owner, handle, value.source_reference_ids)
            values.append(
                path_view(
                    value,
                    identifier=identifier,
                    root=root,
                    name=name,
                    dimension=options.dimension,
                    normalized=options.normalized_known_only,
                    sources={UUID(source.id): source for source in sources},
                    residuals=self._residuals(
                        session, owner, handle.run_id, f"path:{value.key}", maximum=16
                    ),
                )
            )
        return Page(
            items=tuple(values),
            next_cursor=page.next_cursor,
            limit=page.limit,
            total=page.exact_total,
        )
