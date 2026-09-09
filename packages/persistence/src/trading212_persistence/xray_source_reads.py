"""Owner-scoped constituent headers and immutable, licensed holding collections."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import xray as app
from trading212_application.sources import SourceFreshnessState, SourceFreshnessView
from trading212_domain import CurrencyCode, QualityState
from trading212_domain.sources import SourceUse, source_id
from trading212_domain.xray_codec import decode_xray_policy
from trading212_security.principals import Principal

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotResource,
)
from .source_models import MarketDataProviderModel
from .source_store import digest
from .xray_base import xray_error
from .xray_catalog_models import (
    ConstituentHoldingModel,
    ConstituentSnapshotModel,
    FundDefinitionModel,
    FundSourceMappingModel,
    XrayPolicyVersionModel,
)
from .xray_collections import cursor_parent, generated_page, retained_first_page
from .xray_read_store import XrayReadStore
from .xray_run_models import XrayInputDependencyModel, XrayRunSourceModel
from .xray_store_contract import XrayRunHandle


class XraySourceReads(XrayReadStore):
    def _constituent_source(
        self,
        session: Session,
        principal: Principal,
        owner: UUID,
        snapshot_id: str,
        query: app.ConstituentSnapshotQuery | app.ConstituentHoldingsQuery,
    ) -> tuple[ConstituentSnapshotModel, FundDefinitionModel, XrayRunHandle | None]:
        source_id(snapshot_id, "snapshot_id")
        identifier = UUID(snapshot_id)
        handle = None
        if query.account_id is not None:
            account = self._xray_account(session, principal, query.account_id)
            assert query.run_id is not None
            handle = self._authorize_xray_run(session, principal, account, UUID(query.run_id))
            used = session.scalar(
                select(XrayInputDependencyModel.id)
                .join(
                    XrayRunSourceModel,
                    XrayRunSourceModel.dependency_id == XrayInputDependencyModel.id,
                )
                .where(
                    XrayInputDependencyModel.owner_id == owner,
                    XrayInputDependencyModel.input_id == handle.input_id,
                    XrayInputDependencyModel.constituent_snapshot_id == identifier,
                    XrayRunSourceModel.owner_id == owner,
                    XrayRunSourceModel.run_id == handle.run_id,
                )
                .limit(1)
            )
            if used is None:
                raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
        row = self._owned(session, owner, ConstituentSnapshotModel, identifier)
        self._evidence_permit(session, row, SourceUse.DISPLAY)
        mapping = self._owned(session, owner, FundSourceMappingModel, row.fund_mapping_id)
        self._evidence_permit(session, mapping, SourceUse.DISPLAY)
        fund = self._owned(session, owner, FundDefinitionModel, mapping.fund_definition_id)
        self._evidence_permit(session, fund, SourceUse.DISPLAY)
        return row, fund, handle

    def _constituent_freshness(
        self,
        session: Session,
        owner: UUID,
        row: ConstituentSnapshotModel,
        provider: MarketDataProviderModel,
        handle: XrayRunHandle | None,
    ) -> tuple[SourceFreshnessView, datetime]:
        evaluated_at = self._now() if handle is None else handle.context.quality_evaluated_at
        if handle is None:
            version = provider.freshness_policy_version
            maximum = provider.max_age_seconds
        else:
            policy_ref = next(
                item for item in handle.context.policies if item.kind == "calculation"
            )
            policy_row = self._owned(session, owner, XrayPolicyVersionModel, policy_ref.id)
            policy = decode_xray_policy(policy_row.canonical_policy).freshness_policy
            version, maximum = policy.version, policy.stale_after_seconds
        if version is None or maximum is None:
            return SourceFreshnessView(), evaluated_at
        boundary = row.effective_at + timedelta(seconds=maximum)
        # Preserve the existing provider max-age rule for direct diagnostics;
        # retained X-ray runs use their pinned strict "stale after" boundary.
        stale = evaluated_at >= boundary if handle is None else evaluated_at > boundary
        return SourceFreshnessView(
            state=SourceFreshnessState.STALE if stale else SourceFreshnessState.FRESH,
            policy_version=version,
            reference_at=row.effective_at,
            max_age_seconds=maximum,
        ), evaluated_at

    async def get_constituent_snapshot(
        self,
        principal: Principal,
        snapshot_id: str,
        *,
        query: app.ConstituentSnapshotQuery,
    ) -> app.ConstituentSnapshotHeader:
        def read(session: Session, owner: UUID) -> app.ConstituentSnapshotHeader:
            row, fund, handle = self._constituent_source(
                session, principal, owner, snapshot_id, query
            )
            provider = self._owned(session, owner, MarketDataProviderModel, row.provider_id)
            freshness, evaluated_at = self._constituent_freshness(
                session, owner, row, provider, handle
            )
            return app.ConstituentSnapshotHeader(
                id=str(row.id),
                fund_instrument_id=str(fund.instrument_id),
                fund_name=self._instrument_name(session, fund.instrument_id),
                fund_mapping_id=str(row.fund_mapping_id),
                source_at=row.effective_at,
                first_observed_at=row.first_observed_at,
                content_digest=row.content_digest,
                provider_id=str(row.provider_id),
                provider_name=provider.name,
                license=self._license(session, owner, row.license_version_id),
                holding_count=row.row_count,
                known_weight=row.known_weight,
                unresolved_weight=row.unresolved_weight,
                cash_weight=row.cash_weight,
                quality=QualityState(row.quality),
                confidence=row.confidence,
                freshness=freshness,
                freshness_evaluated_at=evaluated_at,
            )

        return await self._read_xray(principal, read)

    async def list_constituent_holdings(
        self,
        principal: Principal,
        snapshot_id: str,
        *,
        query: app.ConstituentHoldingsQuery,
    ) -> app.ConstituentHoldingPage:
        def read(session: Session, owner: UUID) -> app.ConstituentHoldingPage:
            row, fund, _ = self._constituent_source(session, principal, owner, snapshot_id, query)
            definition = CollectionSnapshotDefinition(
                resource=CollectionSnapshotResource.CONSTITUENT_HOLDINGS,
                owner_id=owner,
                broker_account_id=None if query.account_id is None else UUID(query.account_id),
                filter_fingerprint=digest((snapshot_id, query.account_id, query.run_id)),
            )
            store = self._store(session)
            page: CollectionSnapshotPage | None
            if query.cursor is not None:
                binding = cursor_parent(session, self._cursors, definition, query.cursor)
                if binding.constituent_snapshot_id != row.id:
                    raise xray_error(app.XrayServiceErrorCode.VALIDATION_FAILED)
                page = store.resume(definition, query.cursor, limit=query.limit)
            else:
                page = retained_first_page(
                    session, store, definition, run_id=None, source_id=row.id, limit=query.limit
                )
            if page is None:
                identifiers = tuple(
                    session.scalars(
                        select(ConstituentHoldingModel.id)
                        .where(
                            ConstituentHoldingModel.owner_id == owner,
                            ConstituentHoldingModel.snapshot_id == row.id,
                        )
                        .order_by(ConstituentHoldingModel.ordinal)
                        .limit(100_001)
                    )
                )
                if len(identifiers) > 100_000:
                    raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE)
                if len(identifiers) != row.row_count:
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
                mapping = self._owned(session, owner, FundSourceMappingModel, row.fund_mapping_id)
                licenses = (
                    row.license_version_id,
                    mapping.license_version_id,
                    fund.license_version_id,
                )
                expires_at = min(row.expires_at, mapping.expires_at, fund.expires_at)
                # Even empty membership creates a retained source binding.
                self._permit_xray_storage_licenses(session, owner, licenses, expires_at=expires_at)
                page = generated_page(
                    session,
                    store,
                    definition,
                    run_id=None,
                    source_id=row.id,
                    exact_total=len(identifiers),
                    create_records=lambda _: identifiers,
                    limit=query.limit,
                )
                self._permit_xray_storage_licenses(session, owner, licenses, expires_at=expires_at)
            rows = {
                item.id: item
                for item in session.scalars(
                    select(ConstituentHoldingModel).where(
                        ConstituentHoldingModel.owner_id == owner,
                        ConstituentHoldingModel.snapshot_id == row.id,
                        ConstituentHoldingModel.id.in_(page.record_ids),
                    )
                )
            }
            if set(rows) != set(page.record_ids):
                raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
            items = []
            for identifier in page.record_ids:
                item = rows[identifier]
                if item.state not in {"resolved", "cash", "unresolved"}:
                    raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
                items.append(
                    app.ConstituentHoldingView(
                        id=str(item.id),
                        source_key=item.source_key,
                        weight=item.weight,
                        state=cast(Literal["resolved", "cash", "unresolved"], item.state),
                        currency=CurrencyCode(item.currency),
                        instrument_id=None
                        if item.instrument_id is None
                        else str(item.instrument_id),
                        entity_id=None if item.entity_id is None else str(item.entity_id),
                        name=item.name,
                        confidence=item.confidence,
                        evidence_key=item.evidence_key,
                    )
                )
            return app.ConstituentHoldingPage(
                snapshot_id=str(row.id),
                items=tuple(items),
                next_cursor=page.next_cursor,
                limit=page.limit,
                total=page.exact_total,
            )

        return await self._read_xray(principal, read)
