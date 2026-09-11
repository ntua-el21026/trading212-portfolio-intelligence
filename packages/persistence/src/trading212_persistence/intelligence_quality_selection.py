"""Retained producer headers and fixed dependency inventories; no producer getters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from trading212_application import intelligence_quality as q
from trading212_security.principals import AuthorizationError, Scope

from . import historical_models as hm
from . import models as m
from . import xray_run_models as xm
from .intelligence_quality_sources import SPECS, header
from .planning_models import AnalyticsRunModel, AnalyticsSourceModel

K = q.QualitySourceKind
Kind = q.IntelligenceKind
MAX_PAYLOAD = 33_554_432
HISTORICAL_KINDS = frozenset(
    {Kind.PERFORMANCE, Kind.BENCHMARK, Kind.INCOME, Kind.ATTRIBUTION, Kind.CASH_FLOW}
)
PLANNING_KINDS = frozenset({Kind.ACTUAL_VS_TARGET, Kind.DRIFT})
ACTIVITY_KINDS = frozenset({K.BROKER_RECORD, K.BROKER_OCCURRENCE, K.RECONCILIATION, K.REVISION})

HISTORICAL_COLUMNS = {
    "ingestion_run_id": K.INGESTION,
    "source_record_id": K.BROKER_RECORD,
    "source_occurrence_id": K.BROKER_OCCURRENCE,
    "portfolio_snapshot_id": K.PORTFOLIO_SNAPSHOT,
    "calculation_run_id": K.CALCULATION,
    "reconciliation_run_id": K.RECONCILIATION,
    "price_snapshot_id": K.PRICE,
    "fx_snapshot_id": K.FX,
    "action_snapshot_id": K.ACTION,
    "benchmark_snapshot_id": K.BENCHMARK,
    "mapping_id": K.MAPPING,
    "calendar_id": K.CALENDAR,
    "license_version_id": K.LICENSE,
    "benchmark_version_id": K.BENCHMARK_VERSION,
    "target_version_id": K.TARGET,
    "classification_id": K.CLASSIFICATION,
    "registered_evidence_id": K.EVIDENCE,
    "activity_revision_evidence_id": K.REVISION,
}
XRAY_COLUMNS = {
    "valuation_run_id": K.CALCULATION,
    "reconciliation_run_id": K.RECONCILIATION,
    "broker_source_record_id": K.BROKER_RECORD,
    "threshold_policy_id": K.XRAY_POLICY,
    "fx_snapshot_id": K.FX,
    "entity_evidence_version_id": K.ENTITY,
    "classification_snapshot_id": K.XRAY_CLASSIFICATION,
    "fund_definition_id": K.FUND,
    "fund_mapping_id": K.FUND_MAPPING,
    "constituent_snapshot_id": K.CONSTITUENT,
}


@dataclass(frozen=True, slots=True)
class RetainedSelection:
    view: q.QualitySelection
    native_run_id: UUID
    snapshot_id: UUID | None
    payload_bytes: int
    retained: bool


def select_retained(
    session: Session,
    owner: UUID,
    account: UUID,
    kind: Kind,
    at: datetime,
    scopes: frozenset[Scope],
    *,
    identifier: UUID | None = None,
) -> RetainedSelection | None:
    if kind is Kind.VALUATION:
        snapshot, valuation_run = m.PortfolioSnapshotModel, m.CalculationRunModel
        valuation_query = (
            select(
                snapshot.id,
                snapshot.calculation_run_id,
                snapshot.valuation_at,
                snapshot.source_cutoff_at,
                snapshot.created_at,
                snapshot.reporting_currency,
                valuation_run.input_fingerprint,
                valuation_run.output_fingerprint,
                valuation_run.version,
            )
            .join(valuation_run, valuation_run.id == snapshot.calculation_run_id)
            .where(
                snapshot.broker_account_id == account,
                valuation_run.broker_account_id == account,
                snapshot.created_at <= at,
            )
        )
        if identifier is not None:
            valuation_query = valuation_query.where(snapshot.id == identifier)
        valuation_row = session.execute(
            valuation_query.order_by(snapshot.created_at.desc(), snapshot.id.desc()).limit(1)
        ).one_or_none()
        if valuation_row is None:
            return None
        return RetainedSelection(
            q.QualitySelection(
                kind="valuation",
                id=valuation_row.id,
                input_id=None,
                input_kind=None,
                input_digest=valuation_row.input_fingerprint,
                content_digest=valuation_row.output_fingerprint,
                method_version=valuation_row.version,
                reporting_currency=valuation_row.reporting_currency,
                valuation_at=valuation_row.valuation_at,
                source_cutoff_at=valuation_row.source_cutoff_at,
                created_at=valuation_row.created_at,
            ),
            valuation_row.calculation_run_id,
            valuation_row.id,
            0,
            True,
        )

    run = AnalyticsRunModel
    query = select(
        run.id,
        run.input_digest,
        run.content_digest,
        run.method_version,
        run.reporting_currency,
        run.valuation_at,
        run.source_cutoff_at,
        run.created_at,
        func.octet_length(run.canonical_result).label("payload_bytes"),
    ).where(
        run.owner_id == owner,
        run.broker_account_id == account,
        run.kind == kind.value,
        run.created_at <= at,
    )
    if identifier is not None:
        query = query.where(run.id == identifier)
    if kind in HISTORICAL_KINDS:
        historical_run, historical_capture = hm.HistoricalRunModel, hm.HistoricalInputModel
        query = (
            query.join(historical_run, historical_run.analytics_run_id == run.id)
            .join(historical_capture, historical_capture.id == historical_run.input_id)
            .where(
                historical_run.owner_id == owner,
                historical_run.kind == kind.value,
                historical_run.sealed.is_(True),
                historical_capture.owner_id == owner,
                historical_capture.broker_account_id == account,
                historical_capture.sealed.is_(True),
            )
        )
        if Scope.TARGETS_READ not in scopes:
            # Scope eligibility is a WHERE predicate, before selecting a run ID or
            # counting any protected group/target-bearing result.
            query = query.where(
                historical_capture.target_version_id.is_(None),
                ~select(hm.HistoricalDependencyModel.id)
                .where(
                    hm.HistoricalDependencyModel.owner_id == owner,
                    hm.HistoricalDependencyModel.input_id == historical_capture.id,
                    hm.HistoricalDependencyModel.target_version_id.is_not(None),
                )
                .exists(),
            )
        query = query.add_columns(
            historical_run.id.label("native_id"),
            historical_capture.id.label("input_id"),
            historical_capture.period_start,
            historical_capture.period_end,
            historical_capture.input_digest.label("capture_digest"),
            select(AnalyticsSourceModel.id)
            .where(
                AnalyticsSourceModel.owner_id == owner,
                AnalyticsSourceModel.run_id == run.id,
                AnalyticsSourceModel.historical_input_id == historical_capture.id,
                AnalyticsSourceModel.digest == historical_capture.input_digest,
            )
            .exists()
            .label("input_bound"),
        )
    elif kind is Kind.XRAY:
        xray_run, xray_capture = xm.XrayRunModel, xm.XrayInputSnapshotModel
        query = (
            query.join(xray_run, xray_run.analytics_run_id == run.id)
            .join(xray_capture, xray_capture.id == xray_run.input_id)
            .where(
                xray_run.owner_id == owner,
                xray_run.sealed_at.is_not(None),
                xray_capture.owner_id == owner,
                xray_capture.account_id == account,
                xray_capture.sealed_at.is_not(None),
            )
            .add_columns(
                xray_run.id.label("native_id"),
                xray_capture.id.label("input_id"),
                xray_capture.snapshot_id,
                xray_capture.input_digest.label("capture_digest"),
                xray_run.content_digest.label("native_digest"),
                func.octet_length(xray_run.canonical_summary).label("summary_bytes"),
            )
        )
    row = (
        session.execute(query.order_by(run.created_at.desc(), run.id.desc()).limit(1))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row["payload_bytes"] > MAX_PAYLOAD or row.get("summary_bytes", 0) > q.MAX_QUALITY_BYTES:
        raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
    retained = bool(row["payload_bytes"])
    input_id = row.get("input_id")
    if input_id is not None:
        if not row.get("input_bound", True) or (
            kind is Kind.XRAY
            and (
                row["capture_digest"] != row["input_digest"]
                or row["native_digest"] != row["content_digest"]
            )
        ):
            retained = False
        event = (
            hm.HistoricalRetentionEventModel
            if kind in HISTORICAL_KINDS
            else xm.XrayRetentionEventModel
        )
        if (
            session.scalar(
                select(event.id).where(event.owner_id == owner, event.input_id == input_id).limit(1)
            )
            is not None
        ):
            retained = False
    return RetainedSelection(
        q.QualitySelection(
            kind="analytics",
            id=row["id"],
            input_id=input_id,
            input_kind="historical"
            if kind in HISTORICAL_KINDS
            else "xray"
            if kind is Kind.XRAY
            else None,
            input_digest=row.get("capture_digest", row["input_digest"]),
            content_digest=row["content_digest"],
            method_version=row["method_version"],
            reporting_currency=row["reporting_currency"],
            valuation_at=row["valuation_at"],
            source_cutoff_at=row["source_cutoff_at"],
            created_at=row["created_at"],
            period_start=row.get("period_start"),
            period_end=row.get("period_end"),
        ),
        row.get("native_id", row["id"]),
        row.get("snapshot_id"),
        row["payload_bytes"],
        retained,
    )


def _visible(kind: K, scopes: frozenset[Scope]) -> bool:
    return not (kind in ACTIVITY_KINDS and Scope.ACTIVITY_READ not in scopes) and not (
        kind is K.TARGET and Scope.TARGETS_READ not in scopes
    )


def dependency_inventory(
    session: Session,
    owner: UUID,
    account: UUID,
    kind: Kind,
    selection: RetainedSelection,
    scopes: frozenset[Scope],
) -> tuple[q.QualitySourceIdentity, ...]:
    """Bound both raw membership and recursive evidence; only visible rows enter SQL results."""
    found: dict[tuple[K, UUID, UUID | None], q.QualitySourceIdentity] = {}
    visited_evidence: set[UUID] = set()
    raw_count = 0

    def add(source_kind: K, identifier: UUID) -> None:
        nonlocal raw_count
        if not _visible(source_kind, scopes):
            return
        spec = SPECS[source_kind]
        row = header(session, spec, identifier, owner, account)
        if row is None:
            raise AuthorizationError("access denied")
        parent_id = row.get(spec.parent_column) if spec.parent_column else None
        identity = q.QualitySourceIdentity(kind=source_kind, id=identifier, parent_id=parent_id)
        key = (source_kind, identifier, parent_id)
        if source_kind is K.EVIDENCE and identifier in visited_evidence:
            raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
        if key in found:
            return
        raw_count += 1
        if raw_count > q.MAX_QUALITY_SOURCES or len(visited_evidence) > 32:
            raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
        found[key] = identity
        if parent_id is not None and spec.parent_kind is not None:
            add(spec.parent_kind, parent_id)
        if source_kind is K.PORTFOLIO_SNAPSHOT:
            add(K.CALCULATION, row["calculation_run_id"])
        if source_kind is K.REVISION:
            add(K.BROKER_RECORD, row["new_source_record_id"])
            add(K.BROKER_RECORD, row["superseded_source_record_id"])
        if source_kind is K.EVIDENCE:
            if identifier in visited_evidence:
                raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
            visited_evidence.add(identifier)
            dependencies(
                hm.HistoricalDependencyModel,
                HISTORICAL_COLUMNS,
                hm.HistoricalDependencyModel.evidence_id == identifier,
            )
            visited_evidence.remove(identifier)

    def dependencies(
        model: type[hm.HistoricalDependencyModel] | type[xm.XrayInputDependencyModel],
        registry: dict[str, K],
        parent: ColumnElement[bool],
    ) -> None:
        names = {column: member for column, member in registry.items() if _visible(member, scopes)}
        columns = [getattr(model, column) for column in names]
        rows = (
            session.execute(
                select(*columns)
                .where(
                    model.owner_id == owner,
                    parent,
                    or_(*(column.is_not(None) for column in columns)),
                )
                .order_by(model.id)
                .limit(q.MAX_QUALITY_SOURCES + 1)
            )
            .mappings()
            .all()
        )
        if len(rows) > q.MAX_QUALITY_SOURCES:
            raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
        for row in rows:
            pairs = [
                (names[column], identifier)
                for column, identifier in row.items()
                if identifier is not None
            ]
            if len(pairs) != 1:
                raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
            add(*pairs[0])

    if kind is Kind.VALUATION:
        add(K.PORTFOLIO_SNAPSHOT, selection.view.id)
        if Scope.ACTIVITY_READ in scopes:
            # Legacy calculation inputs are a mixed broker-record identity list.
            # Read that list only with the activity grant; do not infer hidden IDs
            # or counts from it for baseline-only traversal.
            calculation = m.CalculationRunModel
            length = session.scalar(
                select(func.jsonb_array_length(calculation.input_ids)).where(
                    calculation.id == selection.native_run_id,
                    calculation.broker_account_id == account,
                )
            )
            if length is None or length > q.MAX_QUALITY_SOURCES:
                raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
            source_ids = session.scalar(
                select(calculation.input_ids).where(
                    calculation.id == selection.native_run_id,
                    calculation.broker_account_id == account,
                )
            )
            for source_id in source_ids or ():
                add(K.BROKER_RECORD, UUID(source_id))
        for model, source_kind in (
            (m.SnapshotPositionModel, K.POSITION),
            (m.SnapshotCashModel, K.CASH),
        ):
            ids = session.scalars(
                select(model.id)
                .where(model.snapshot_id == selection.view.id)
                .order_by(model.id)
                .limit(q.MAX_QUALITY_SOURCES + 1)
            ).all()
            if len(ids) > q.MAX_QUALITY_SOURCES:
                raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
            for identifier in ids:
                add(source_kind, identifier)
    elif kind in HISTORICAL_KINDS:
        dependencies(
            hm.HistoricalDependencyModel,
            HISTORICAL_COLUMNS,
            hm.HistoricalDependencyModel.input_id == selection.view.input_id,
        )
    elif kind is Kind.XRAY:
        if selection.snapshot_id is not None:
            add(K.PORTFOLIO_SNAPSHOT, selection.snapshot_id)
        dependencies(
            xm.XrayInputDependencyModel,
            XRAY_COLUMNS,
            xm.XrayInputDependencyModel.input_id == selection.view.input_id,
        )
    elif kind in PLANNING_KINDS:
        planning_source = AnalyticsSourceModel
        registry = {
            "snapshot_id": K.PORTFOLIO_SNAPSHOT,
            "target_version_id": K.TARGET,
            "source_record_id": K.BROKER_RECORD,
        }
        names = {column: member for column, member in registry.items() if _visible(member, scopes)}
        columns = [getattr(planning_source, column) for column in names]
        rows = (
            session.execute(
                select(*columns)
                .where(
                    planning_source.owner_id == owner,
                    planning_source.run_id == selection.view.id,
                    or_(*(column.is_not(None) for column in columns)),
                )
                .order_by(planning_source.id)
                .limit(q.MAX_QUALITY_SOURCES + 1)
            )
            .mappings()
            .all()
        )
        if len(rows) > q.MAX_QUALITY_SOURCES:
            raise q.IntelligenceQualityError("RESULT_TOO_LARGE")
        for row in rows:
            pairs = [
                (names[column], identifier)
                for column, identifier in row.items()
                if identifier is not None
            ]
            if len(pairs) != 1:
                raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
            add(*pairs[0])
    return tuple(
        sorted(
            found.values(),
            key=lambda item: (item.kind.value, str(item.id), str(item.parent_id or "")),
        )
    )
