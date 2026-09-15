"""Durable immutable identity sets for stable mutable-collection traversal."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import islice
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
    cursor_binding,
)

from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
    OwnerModel,
    PortfolioSnapshotModel,
)

COLLECTION_SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_MAX_ACTIVE_COLLECTION_SNAPSHOTS_PER_OWNER = 64
DEFAULT_MAX_ACTIVE_COLLECTION_MEMBERS_PER_OWNER = 250_000
_FILTER_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_INSERT_BATCH_SIZE = 1_000


class CollectionSnapshotResource(StrEnum):
    RESEARCH_ITEMS = "research_items"
    RESEARCH_NOTES = "research_notes"
    RESEARCH_NOTE_VERSIONS = "research_note_versions"
    RISK_DEFINITIONS = "risk_definitions"
    RISK_VERSIONS = "risk_versions"
    RISK_RUNS = "risk_runs"
    SCENARIO_DEFINITIONS = "scenario_definitions"
    SCENARIO_VERSIONS = "scenario_versions"
    SCENARIO_RUNS = "scenario_runs"
    ASSUMPTION_SETS = "assumption_sets"
    ASSUMPTION_VERSIONS = "assumption_versions"
    GOALS = "goals"
    GOAL_VERSIONS = "goal_versions"
    PROJECTION_RUNS = "projection_runs"
    INTELLIGENCE_QUALITY_SOURCES = "intelligence_quality_sources"
    PORTFOLIOS_NAME = "portfolios_name"
    PORTFOLIOS_UPDATED = "portfolios_updated"
    TARGET_VERSIONS = "target_versions"
    TARGET_EVENTS = "target_events"
    TARGET_NODES = "target_nodes"
    CONTRIBUTION_PLANS = "contribution_plans"
    ALERT_RULES = "alert_rules"
    ALERT_VERSIONS = "alert_versions"
    ALERT_EVENTS = "alert_events"
    ALERT_EVALUATIONS = "alert_evaluations"
    NOTIFICATION_DESTINATIONS = "notification_destinations"
    PREMIUM_REPORTS = "premium_reports"
    REPORTS = "reports"
    EXPORTS = "exports"
    PLAN_REVISIONS = "plan_revisions"
    PLAN_LINES = "plan_lines"
    ACTUAL_TARGET_ROWS = "actual_target_rows"
    MARKET_SOURCE_STATUS = "market_source_status"
    BENCHMARK_SOURCE_STATUS = "benchmark_source_status"
    FX_SOURCE_STATUS = "fx_source_status"
    PRICE_OBSERVATIONS = "price_observations"
    FX_OBSERVATIONS = "fx_observations"
    BENCHMARK_OBSERVATIONS = "benchmark_observations"
    BENCHMARK_DEFINITIONS_NAME = "benchmark_defs_name"
    BENCHMARK_DEFINITIONS_CREATED = "benchmark_defs_created"
    BENCHMARK_VERSIONS = "benchmark_versions"
    XRAY_EXPOSURES = "xray_exposures"
    XRAY_PATHS = "xray_paths"
    XRAY_HELD_FUNDS = "xray_held_funds"
    XRAY_PAIRS = "xray_pairs"
    XRAY_COMMON_ENTITIES = "xray_common_entities"
    CONSTITUENT_HOLDINGS = "constituent_holdings"
    HISTORICAL_PERFORMANCE = "historical_performance"
    HISTORICAL_CASH_FLOWS = "historical_cash_flows"
    COMPOSITE_BENCHMARK_POINTS = "composite_benchmark_points"
    ACTIVITY = "activity"
    DIVIDENDS = "dividends"
    INSTRUMENTS = "instruments"
    POSITIONS_MARKET_VALUE = "positions_market_value"
    POSITIONS_WEIGHT = "positions_weight"
    POSITIONS_TICKER = "positions_ticker"


_SORT_SPECIFICATIONS = {
    CollectionSnapshotResource.RESEARCH_ITEMS: "ordinal_asc",
    CollectionSnapshotResource.RESEARCH_NOTES: "created_at_desc_id_desc",
    CollectionSnapshotResource.RESEARCH_NOTE_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.RISK_DEFINITIONS: "created_at_desc_id_desc",
    CollectionSnapshotResource.RISK_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.RISK_RUNS: "created_at_desc_id_desc",
    CollectionSnapshotResource.SCENARIO_DEFINITIONS: "created_at_desc_id_desc",
    CollectionSnapshotResource.SCENARIO_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.SCENARIO_RUNS: "created_at_desc_id_desc",
    CollectionSnapshotResource.ASSUMPTION_SETS: "created_at_desc_id_desc",
    CollectionSnapshotResource.ASSUMPTION_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.GOALS: "created_at_desc_id_desc",
    CollectionSnapshotResource.GOAL_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.PROJECTION_RUNS: "created_at_desc_id_desc",
    CollectionSnapshotResource.INTELLIGENCE_QUALITY_SOURCES: "ordinal_asc",
    CollectionSnapshotResource.XRAY_EXPOSURES: "ordinal_asc",
    CollectionSnapshotResource.XRAY_PATHS: "ordinal_asc",
    CollectionSnapshotResource.XRAY_HELD_FUNDS: "ordinal_asc",
    CollectionSnapshotResource.XRAY_PAIRS: "ordinal_asc",
    CollectionSnapshotResource.XRAY_COMMON_ENTITIES: "ordinal_asc",
    CollectionSnapshotResource.CONSTITUENT_HOLDINGS: "ordinal_asc",
    CollectionSnapshotResource.HISTORICAL_PERFORMANCE: "ordinal_asc",
    CollectionSnapshotResource.HISTORICAL_CASH_FLOWS: "ordinal_asc",
    CollectionSnapshotResource.COMPOSITE_BENCHMARK_POINTS: "ordinal_asc",
    CollectionSnapshotResource.MARKET_SOURCE_STATUS: "source_key_asc_id_asc",
    CollectionSnapshotResource.BENCHMARK_SOURCE_STATUS: "source_key_asc_id_asc",
    CollectionSnapshotResource.FX_SOURCE_STATUS: "base_quote_provider_asc",
    CollectionSnapshotResource.PRICE_OBSERVATIONS: "ordinal_asc",
    CollectionSnapshotResource.FX_OBSERVATIONS: "ordinal_asc",
    CollectionSnapshotResource.BENCHMARK_OBSERVATIONS: "ordinal_asc",
    CollectionSnapshotResource.BENCHMARK_DEFINITIONS_NAME: "name_asc_id_asc",
    CollectionSnapshotResource.BENCHMARK_DEFINITIONS_CREATED: "created_at_desc_id_desc",
    CollectionSnapshotResource.BENCHMARK_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.PORTFOLIOS_NAME: "name_asc_id_asc",
    CollectionSnapshotResource.PORTFOLIOS_UPDATED: "updated_at_desc_id_desc",
    CollectionSnapshotResource.TARGET_VERSIONS: "version_number_desc_id_desc",
    CollectionSnapshotResource.TARGET_EVENTS: "created_at_desc_id_desc",
    CollectionSnapshotResource.TARGET_NODES: "depth_first_order_key",
    CollectionSnapshotResource.CONTRIBUTION_PLANS: "created_at_desc_id_desc",
    CollectionSnapshotResource.ALERT_RULES: "created_at_desc_id_desc",
    CollectionSnapshotResource.ALERT_VERSIONS: "created_at_desc_id_desc",
    CollectionSnapshotResource.ALERT_EVENTS: "created_at_desc_id_desc",
    CollectionSnapshotResource.ALERT_EVALUATIONS: "created_at_desc_id_desc",
    CollectionSnapshotResource.NOTIFICATION_DESTINATIONS: "created_at_desc_id_desc",
    CollectionSnapshotResource.PREMIUM_REPORTS: "created_at_desc_id_desc",
    CollectionSnapshotResource.REPORTS: "created_at_desc_id_desc",
    CollectionSnapshotResource.EXPORTS: "created_at_desc_id_desc",
    CollectionSnapshotResource.PLAN_REVISIONS: "revision_number_desc_id_desc",
    CollectionSnapshotResource.PLAN_LINES: "ordinal_asc",
    CollectionSnapshotResource.ACTUAL_TARGET_ROWS: "ordinal_asc",
    CollectionSnapshotResource.ACTIVITY: "occurred_at_desc_id_desc",
    CollectionSnapshotResource.DIVIDENDS: "paid_on_desc_id_desc",
    CollectionSnapshotResource.INSTRUMENTS: (
        "provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc"
    ),
    CollectionSnapshotResource.POSITIONS_MARKET_VALUE: (
        "market_value_desc_ticker_asc_listing_id_asc"
    ),
    CollectionSnapshotResource.POSITIONS_WEIGHT: ("direct_weight_desc_ticker_asc_listing_id_asc"),
    CollectionSnapshotResource.POSITIONS_TICKER: "ticker_asc_listing_id_asc",
}
_OPTIONAL_ACCOUNT_RESOURCES = frozenset(
    {
        CollectionSnapshotResource.RESEARCH_ITEMS,
        CollectionSnapshotResource.RESEARCH_NOTES,
        CollectionSnapshotResource.RESEARCH_NOTE_VERSIONS,
        CollectionSnapshotResource.XRAY_EXPOSURES,
        CollectionSnapshotResource.XRAY_PATHS,
        CollectionSnapshotResource.XRAY_HELD_FUNDS,
        CollectionSnapshotResource.XRAY_PAIRS,
        CollectionSnapshotResource.XRAY_COMMON_ENTITIES,
        CollectionSnapshotResource.CONSTITUENT_HOLDINGS,
        CollectionSnapshotResource.COMPOSITE_BENCHMARK_POINTS,
        CollectionSnapshotResource.MARKET_SOURCE_STATUS,
        CollectionSnapshotResource.BENCHMARK_SOURCE_STATUS,
        CollectionSnapshotResource.FX_SOURCE_STATUS,
        CollectionSnapshotResource.PRICE_OBSERVATIONS,
        CollectionSnapshotResource.FX_OBSERVATIONS,
        CollectionSnapshotResource.BENCHMARK_OBSERVATIONS,
        CollectionSnapshotResource.BENCHMARK_DEFINITIONS_NAME,
        CollectionSnapshotResource.BENCHMARK_DEFINITIONS_CREATED,
        CollectionSnapshotResource.BENCHMARK_VERSIONS,
        CollectionSnapshotResource.PORTFOLIOS_NAME,
        CollectionSnapshotResource.PORTFOLIOS_UPDATED,
        CollectionSnapshotResource.TARGET_VERSIONS,
        CollectionSnapshotResource.TARGET_EVENTS,
        CollectionSnapshotResource.TARGET_NODES,
    }
)
_ACCOUNT_RESOURCES = frozenset(
    {
        CollectionSnapshotResource.RESEARCH_ITEMS,
        CollectionSnapshotResource.RESEARCH_NOTES,
        CollectionSnapshotResource.RESEARCH_NOTE_VERSIONS,
        CollectionSnapshotResource.RISK_DEFINITIONS,
        CollectionSnapshotResource.RISK_VERSIONS,
        CollectionSnapshotResource.RISK_RUNS,
        CollectionSnapshotResource.SCENARIO_DEFINITIONS,
        CollectionSnapshotResource.SCENARIO_VERSIONS,
        CollectionSnapshotResource.SCENARIO_RUNS,
        CollectionSnapshotResource.ASSUMPTION_SETS,
        CollectionSnapshotResource.ASSUMPTION_VERSIONS,
        CollectionSnapshotResource.GOALS,
        CollectionSnapshotResource.GOAL_VERSIONS,
        CollectionSnapshotResource.PROJECTION_RUNS,
        CollectionSnapshotResource.INTELLIGENCE_QUALITY_SOURCES,
        CollectionSnapshotResource.XRAY_EXPOSURES,
        CollectionSnapshotResource.XRAY_PATHS,
        CollectionSnapshotResource.XRAY_HELD_FUNDS,
        CollectionSnapshotResource.XRAY_PAIRS,
        CollectionSnapshotResource.XRAY_COMMON_ENTITIES,
        CollectionSnapshotResource.HISTORICAL_PERFORMANCE,
        CollectionSnapshotResource.HISTORICAL_CASH_FLOWS,
        CollectionSnapshotResource.CONTRIBUTION_PLANS,
        CollectionSnapshotResource.ALERT_RULES,
        CollectionSnapshotResource.ALERT_VERSIONS,
        CollectionSnapshotResource.ALERT_EVENTS,
        CollectionSnapshotResource.ALERT_EVALUATIONS,
        CollectionSnapshotResource.NOTIFICATION_DESTINATIONS,
        CollectionSnapshotResource.PREMIUM_REPORTS,
        CollectionSnapshotResource.REPORTS,
        CollectionSnapshotResource.EXPORTS,
        CollectionSnapshotResource.PLAN_REVISIONS,
        CollectionSnapshotResource.PLAN_LINES,
        CollectionSnapshotResource.ACTUAL_TARGET_ROWS,
        CollectionSnapshotResource.ACTIVITY,
        CollectionSnapshotResource.DIVIDENDS,
        CollectionSnapshotResource.POSITIONS_MARKET_VALUE,
        CollectionSnapshotResource.POSITIONS_WEIGHT,
        CollectionSnapshotResource.POSITIONS_TICKER,
    }
)
_POSITION_RESOURCES = frozenset(
    {
        CollectionSnapshotResource.POSITIONS_MARKET_VALUE,
        CollectionSnapshotResource.POSITIONS_WEIGHT,
        CollectionSnapshotResource.POSITIONS_TICKER,
    }
)


class CollectionSnapshotScopeError(ValueError):
    """The requested owner/account scope is unavailable or structurally invalid."""


@dataclass(frozen=True, slots=True)
class CollectionSnapshotDefinition:
    resource: CollectionSnapshotResource
    owner_id: UUID
    broker_account_id: UUID | None
    filter_fingerprint: str
    source_snapshot_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.resource, CollectionSnapshotResource):
            raise ValueError("unsupported collection snapshot resource")
        if not isinstance(self.owner_id, UUID):
            raise ValueError("owner_id must be a UUID")
        if self.broker_account_id is not None and not isinstance(self.broker_account_id, UUID):
            raise ValueError("broker_account_id must be a UUID")
        requires_account = self.resource in _ACCOUNT_RESOURCES
        if self.resource not in _OPTIONAL_ACCOUNT_RESOURCES and requires_account != (
            self.broker_account_id is not None
        ):
            raise ValueError("collection snapshot account scope does not match resource")
        if _FILTER_FINGERPRINT.fullmatch(self.filter_fingerprint) is None:
            raise ValueError("filter_fingerprint must be a lowercase SHA-256 digest")
        if self.source_snapshot_id is not None and self.resource not in _POSITION_RESOURCES:
            raise ValueError("only position collection snapshots may bind a portfolio snapshot")
        if self.source_snapshot_id is not None and not isinstance(self.source_snapshot_id, UUID):
            raise ValueError("source_snapshot_id must be a UUID")

    @property
    def sort_specification(self) -> str:
        return _SORT_SPECIFICATIONS[self.resource]


@dataclass(frozen=True, slots=True)
class CollectionSnapshot:
    id: UUID
    definition: CollectionSnapshotDefinition
    exact_total: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CollectionSnapshotPage:
    snapshot_id: UUID
    record_ids: tuple[UUID, ...]
    next_cursor: str | None
    limit: int
    exact_total: int
    expires_at: datetime
    source_snapshot_id: UUID | None


def collection_filter_fingerprint(*parts: object) -> str:
    """Hash normalized filter inputs without persisting their plaintext values."""

    return hashlib.sha256(cursor_binding(*parts).encode("utf-8")).hexdigest()


class CollectionSnapshotStore:
    """Materialize and page a fixed, scope-bound ordered record identity set.

    The caller owns the surrounding transaction. A savepoint protects the new
    snapshot and its members even when the caller catches materialization errors.
    """

    def __init__(
        self,
        session: Session,
        cursor_codec: CursorCodec,
        *,
        ttl_seconds: int = 3_600,
        cleanup_batch_size: int = 100,
        max_active_snapshots_per_owner: int = (DEFAULT_MAX_ACTIVE_COLLECTION_SNAPSHOTS_PER_OWNER),
        max_active_members_per_owner: int = DEFAULT_MAX_ACTIVE_COLLECTION_MEMBERS_PER_OWNER,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not 60 <= ttl_seconds <= 86_400:
            raise ValueError("snapshot TTL must be between 60 and 86400 seconds")
        if isinstance(cleanup_batch_size, bool) or not 1 <= cleanup_batch_size <= 1_000:
            raise ValueError("cleanup batch size must be between 1 and 1000")
        if (
            isinstance(max_active_snapshots_per_owner, bool)
            or not 1 <= max_active_snapshots_per_owner <= 10_000
        ):
            raise ValueError("active snapshot quota must be between 1 and 10000")
        if (
            isinstance(max_active_members_per_owner, bool)
            or not 1 <= max_active_members_per_owner <= 100_000_000
        ):
            raise ValueError("active member quota must be between 1 and 100000000")
        self._session = session
        self._cursors = cursor_codec
        self._ttl = timedelta(seconds=ttl_seconds)
        self._cleanup_batch_size = cleanup_batch_size
        self._max_active_snapshots = max_active_snapshots_per_owner
        self._max_active_members = max_active_members_per_owner

    def materialize(
        self,
        definition: CollectionSnapshotDefinition,
        ordered_record_ids: Iterable[UUID] | Callable[[], Iterable[UUID]],
        *,
        limit: int,
    ) -> CollectionSnapshotPage:
        return self._materialize(definition, ordered_record_ids, limit=limit)

    def materialize_generated(
        self,
        definition: CollectionSnapshotDefinition,
        *,
        exact_total: int,
        create_records: Callable[[UUID], Iterable[UUID]],
        limit: int,
    ) -> CollectionSnapshotPage:
        """Reserve the complete membership before creating collection-owned payloads.

        The callback receives the already allocated collection ID inside the same
        savepoint. Any count mismatch rolls back its payloads and all membership.
        """
        if type(exact_total) is not int or not 0 <= exact_total <= self._max_active_members:
            raise CollectionSnapshotCapacityError()
        if not callable(create_records):
            raise ValueError("A bounded collection record factory is required.")
        return self._materialize(
            definition,
            (),
            limit=limit,
            expected_total=exact_total,
            create_records=create_records,
        )

    def _materialize(
        self,
        definition: CollectionSnapshotDefinition,
        ordered_record_ids: Iterable[UUID] | Callable[[], Iterable[UUID]],
        *,
        limit: int,
        expected_total: int | None = None,
        create_records: Callable[[UUID], Iterable[UUID]] | None = None,
    ) -> CollectionSnapshotPage:
        """Persist one immutable ordered membership set and return its first page."""

        page_limit = _page_limit(limit)
        self._require_materialization_scope(definition)
        _acquire_owner_capacity_lock(self._session, definition.owner_id)
        self.cleanup_expired()
        created_at = _database_now(self._session)
        active_snapshot_count, active_member_count = self._active_capacity(
            definition.owner_id,
            now=created_at,
        )
        if (
            active_snapshot_count >= self._max_active_snapshots
            or active_member_count >= self._max_active_members
        ):
            raise CollectionSnapshotCapacityError()
        available_member_capacity = self._max_active_members - active_member_count
        if expected_total is not None and expected_total > available_member_capacity:
            raise CollectionSnapshotCapacityError()
        # Keep the capacity lock outside the savepoint so catching an overflow
        # cannot release it before the caller's surrounding transaction finishes.
        with self._session.begin_nested():
            snapshot = CollectionQuerySnapshotModel(
                id=uuid4(),
                schema_version=COLLECTION_SNAPSHOT_SCHEMA_VERSION,
                resource=definition.resource.value,
                owner_id=definition.owner_id,
                broker_account_id=definition.broker_account_id,
                source_snapshot_id=definition.source_snapshot_id,
                sort_specification=definition.sort_specification,
                filter_fingerprint=definition.filter_fingerprint,
                # Seal the exact total only after the complete identity set fits.
                exact_total=0,
                created_at=created_at,
                expires_at=created_at + self._ttl,
            )
            self._session.add(snapshot)
            self._session.flush()
            source = (
                create_records(snapshot.id)
                if create_records is not None
                else ordered_record_ids()
                if callable(ordered_record_ids)
                else ordered_record_ids
            )
            iterator = iter(source)
            exact_total = 0
            while True:
                batch_size = min(
                    _INSERT_BATCH_SIZE,
                    available_member_capacity - exact_total + 1,
                )
                batch = tuple(islice(iterator, batch_size))
                if not batch:
                    break
                if exact_total + len(batch) > available_member_capacity:
                    raise CollectionSnapshotCapacityError()
                if any(not isinstance(record_id, UUID) for record_id in batch):
                    raise ValueError("collection snapshot record IDs must be UUIDs")
                self._session.execute(
                    insert(CollectionQuerySnapshotMemberModel),
                    [
                        {
                            "snapshot_id": snapshot.id,
                            "ordinal": exact_total + offset + 1,
                            "record_id": record_id,
                        }
                        for offset, record_id in enumerate(batch)
                    ],
                )
                exact_total += len(batch)
            if expected_total is not None and expected_total != exact_total:
                raise ValueError("Generated collection membership does not match its reservation.")
            snapshot.exact_total = exact_total
            self._session.flush()
            value = _snapshot_value(snapshot)
            return self._read_page(value, after_ordinal=0, limit=page_limit)

    def resume(
        self,
        definition: CollectionSnapshotDefinition,
        cursor: str,
        *,
        limit: int,
    ) -> CollectionSnapshotPage:
        """Validate a signed snapshot/ordinal cursor and return the next stable page."""

        page_limit = _page_limit(limit)
        try:
            created_at, key = self._cursors.decode(
                cursor,
                resource=_cursor_resource(definition.resource),
                binding=_cursor_binding(definition),
                key_size=2,
            )
            snapshot_id = UUID(key[0])
            after_ordinal = int(key[1])
            if after_ordinal < 1:
                raise CursorValidationError("invalid cursor")
        except CursorValidationError:
            raise
        except (ValueError, TypeError) as exc:
            raise CursorValidationError("invalid cursor") from exc

        conditions = (
            CollectionQuerySnapshotModel.id == snapshot_id,
            CollectionQuerySnapshotModel.schema_version == COLLECTION_SNAPSHOT_SCHEMA_VERSION,
            CollectionQuerySnapshotModel.resource == definition.resource.value,
            CollectionQuerySnapshotModel.owner_id == definition.owner_id,
            CollectionQuerySnapshotModel.sort_specification == definition.sort_specification,
            CollectionQuerySnapshotModel.filter_fingerprint == definition.filter_fingerprint,
            CollectionQuerySnapshotModel.created_at == created_at,
        )
        account_condition = (
            CollectionQuerySnapshotModel.broker_account_id.is_(None)
            if definition.broker_account_id is None
            else CollectionQuerySnapshotModel.broker_account_id == definition.broker_account_id
        )
        model = self._session.scalar(
            select(CollectionQuerySnapshotModel).where(*conditions, account_condition)
        )
        if model is None:
            raise CursorValidationError("invalid cursor")
        snapshot = _snapshot_value(model)
        if snapshot.expires_at <= _database_now(self._session):
            raise CursorValidationError("invalid cursor")
        if after_ordinal >= snapshot.exact_total:
            raise CursorValidationError("invalid cursor")
        return self._read_page(snapshot, after_ordinal=after_ordinal, limit=page_limit)

    def cleanup_expired(self) -> int:
        """Delete at most one non-blocking batch of expired snapshots."""

        return cleanup_expired_collection_snapshots(
            self._session,
            batch_size=self._cleanup_batch_size,
        )

    def _active_capacity(self, owner_id: UUID, *, now: datetime) -> tuple[int, int]:
        from .xray_run_models import XrayCollectionBindingModel

        retained_xray = (
            select(XrayCollectionBindingModel.id)
            .where(
                XrayCollectionBindingModel.collection_id == CollectionQuerySnapshotModel.id,
                XrayCollectionBindingModel.owner_id == owner_id,
            )
            .exists()
        )
        snapshot_count, member_count = self._session.execute(
            select(
                func.count(CollectionQuerySnapshotModel.id),
                func.coalesce(func.sum(CollectionQuerySnapshotModel.exact_total), 0),
            ).where(
                CollectionQuerySnapshotModel.owner_id == owner_id,
                (CollectionQuerySnapshotModel.expires_at > now) | retained_xray,
            )
        ).one()
        return int(snapshot_count), int(member_count)

    def _require_materialization_scope(self, definition: CollectionSnapshotDefinition) -> None:
        if definition.resource in _POSITION_RESOURCES and definition.source_snapshot_id is None:
            raise CollectionSnapshotScopeError(
                "position collection snapshot requires an immutable portfolio snapshot"
            )
        if definition.broker_account_id is None:
            available = self._session.scalar(
                select(OwnerModel.id).where(OwnerModel.id == definition.owner_id)
            )
        else:
            available = self._session.scalar(
                select(BrokerAccountModel.id)
                .join(
                    BrokerConnectionModel,
                    BrokerConnectionModel.id == BrokerAccountModel.connection_id,
                )
                .where(
                    BrokerAccountModel.id == definition.broker_account_id,
                    BrokerConnectionModel.owner_id == definition.owner_id,
                )
            )
        if available is None:
            raise CollectionSnapshotScopeError("collection snapshot scope is unavailable")
        if definition.source_snapshot_id is not None:
            source_available = self._session.scalar(
                select(PortfolioSnapshotModel.id).where(
                    PortfolioSnapshotModel.id == definition.source_snapshot_id,
                    PortfolioSnapshotModel.broker_account_id == definition.broker_account_id,
                )
            )
            if source_available is None:
                raise CollectionSnapshotScopeError(
                    "position collection source snapshot is unavailable"
                )

    def _read_page(
        self,
        snapshot: CollectionSnapshot,
        *,
        after_ordinal: int,
        limit: int,
    ) -> CollectionSnapshotPage:
        rows = tuple(
            self._session.scalars(
                select(CollectionQuerySnapshotMemberModel)
                .where(
                    CollectionQuerySnapshotMemberModel.snapshot_id == snapshot.id,
                    CollectionQuerySnapshotMemberModel.ordinal > after_ordinal,
                )
                .order_by(CollectionQuerySnapshotMemberModel.ordinal)
                .limit(limit + 1)
            )
        )
        expected_count = min(snapshot.exact_total - after_ordinal, limit + 1)
        if expected_count < 0 or len(rows) != expected_count:
            raise CursorValidationError("invalid cursor")
        for expected_ordinal, member in enumerate(rows, start=after_ordinal + 1):
            if member.ordinal != expected_ordinal:
                raise CursorValidationError("invalid cursor")

        selected = rows[:limit]
        next_cursor = None
        if len(rows) > limit and selected:
            next_cursor = self._cursors.encode(
                resource=_cursor_resource(snapshot.definition.resource),
                binding=_cursor_binding(snapshot.definition),
                read_cutoff=snapshot.created_at,
                key=(str(snapshot.id), str(selected[-1].ordinal)),
            )
        return CollectionSnapshotPage(
            snapshot_id=snapshot.id,
            record_ids=tuple(member.record_id for member in selected),
            next_cursor=next_cursor,
            limit=limit,
            exact_total=snapshot.exact_total,
            expires_at=snapshot.expires_at,
            source_snapshot_id=snapshot.definition.source_snapshot_id,
        )


def _snapshot_value(model: CollectionQuerySnapshotModel) -> CollectionSnapshot:
    return CollectionSnapshot(
        id=model.id,
        definition=CollectionSnapshotDefinition(
            resource=CollectionSnapshotResource(model.resource),
            owner_id=model.owner_id,
            broker_account_id=model.broker_account_id,
            filter_fingerprint=model.filter_fingerprint,
            source_snapshot_id=model.source_snapshot_id,
        ),
        exact_total=model.exact_total,
        created_at=_utc(model.created_at),
        expires_at=_utc(model.expires_at),
    )


def cleanup_expired_collection_snapshots(session: Session, *, batch_size: int = 100) -> int:
    """Delete one deterministic non-blocking batch of expired traversal snapshots."""

    if isinstance(batch_size, bool) or not 1 <= batch_size <= 1_000:
        raise ValueError("cleanup batch size must be between 1 and 1000")
    # X-ray projections can contain licensed payloads and must be removed by
    # their bounded participant before this ordinary snapshot deletion path.
    from .xray_run_models import XrayCollectionBindingModel

    retained_xray = (
        select(XrayCollectionBindingModel.id)
        .where(
            XrayCollectionBindingModel.collection_id == CollectionQuerySnapshotModel.id,
        )
        .exists()
    )
    expired_ids = tuple(
        session.scalars(
            select(CollectionQuerySnapshotModel.id)
            .where(CollectionQuerySnapshotModel.expires_at <= func.now(), ~retained_xray)
            .order_by(
                CollectionQuerySnapshotModel.expires_at,
                CollectionQuerySnapshotModel.id,
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    if not expired_ids:
        return 0
    session.execute(
        delete(CollectionQuerySnapshotModel).where(CollectionQuerySnapshotModel.id.in_(expired_ids))
    )
    return len(expired_ids)


def _cursor_binding(definition: CollectionSnapshotDefinition) -> str:
    return cursor_binding(
        "collection-query-snapshot",
        COLLECTION_SNAPSHOT_SCHEMA_VERSION,
        definition.owner_id,
        definition.broker_account_id,
        definition.resource,
        definition.sort_specification,
        definition.filter_fingerprint,
    )


def _cursor_resource(resource: CollectionSnapshotResource) -> str:
    return f"collection_snapshot.{resource.value}"


def _page_limit(limit: int) -> int:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return limit


def _acquire_owner_capacity_lock(session: Session, owner_id: UUID) -> None:
    """Serialize active-capacity accounting for one owner until transaction end."""

    high = owner_id.int >> 64
    low = owner_id.int & ((1 << 64) - 1)
    unsigned_key = high ^ low
    signed_key = unsigned_key if unsigned_key < (1 << 63) else unsigned_key - (1 << 64)
    session.execute(select(func.pg_advisory_xact_lock(signed_key)))


def _database_now(session: Session) -> datetime:
    value = cast(datetime | None, session.scalar(select(func.now())))
    if value is None:
        raise RuntimeError("database clock is unavailable")
    return _utc(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("collection snapshot timestamps must be timezone-aware")
    return value.astimezone(UTC)
