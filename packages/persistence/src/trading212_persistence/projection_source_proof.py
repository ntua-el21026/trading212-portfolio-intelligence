"""Complete original projection evidence, called only after all headers are authorized."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application.projection_capture import ProjectionSnapshotValue
from trading212_domain.enums import QualityState
from trading212_domain.historical_serialization import (
    historical_input_digest,
    historical_input_from_json,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import BenchmarkSnapshot, PriceSnapshot, source_snapshot_digest
from trading212_domain.values import CurrencyCode, Money

from . import historical_models as hm
from . import models as m
from . import source_models as sm
from .projection_source_store import bounded, records, unavailable
from .report_authorization import ReportAuthorization
from .source_store import digest, license_view

if TYPE_CHECKING:
    from .projection_source_store import ProjectionSourceHeader, ProjectionSourceStore


def quality(value: Any) -> QualityState:
    """Retain the worst declared evidence quality, never upgrade missing coverage."""
    order = (
        QualityState.FRESH,
        QualityState.STALE,
        QualityState.ESTIMATED,
        QualityState.UNRECONCILED,
        QualityState.PARTIAL,
        QualityState.FAILED,
    )
    found = {QualityState.FRESH}

    def visit(item: Any) -> None:
        if isinstance(item, QualityState):
            found.add(item)
        elif is_dataclass(item) and not isinstance(item, type):
            for field in fields(item):
                visit(getattr(item, field.name))
        elif isinstance(item, (tuple, list)):
            for entry in item:
                visit(entry)

    visit(value)
    coverage = getattr(value, "coverage", None)
    if coverage is not None and any(
        not measure.complete for measure in getattr(coverage, "measures", ())
    ):
        found.add(QualityState.PARTIAL)
    return max(found, key=order.index)


def original_projection_proof(
    store: ProjectionSourceStore,
    session: Session,
    auth: ReportAuthorization,
    header: ProjectionSourceHeader,
) -> tuple[Mapping[str, Any], ProjectionSnapshotValue | None, QualityState]:
    licenses = []
    for identifier in header.license_version_ids:
        row = session.scalar(
            select(sm.ProviderLicenseVersionModel).where(
                sm.ProviderLicenseVersionModel.id == identifier,
                sm.ProviderLicenseVersionModel.owner_id == auth.owner_id,
            )
        )
        if row is None:
            raise unavailable()
        licenses.append(license_view(row))
    proof: dict[str, Any] = {
        "schema": "projection_source_proof_v1",
        "source_kind": header.kind,
        "subject_id": header.subject_id,
        "content_digest": header.content_digest,
        "original_created_at": header.original_created_at,
        "physical_expires_at": None
        if header.kind in ("portfolio_snapshot", "historical_input")
        else header.metadata[0]["expires_at"],
        "metadata": header.metadata,
        "licenses": tuple(licenses),
    }
    if header.kind == "portfolio_snapshot":
        snapshots = records(
            session,
            m.PortfolioSnapshotModel,
            m.PortfolioSnapshotModel.id == header.subject_id,
            m.PortfolioSnapshotModel.broker_account_id == auth.account_id,
        )
        if len(snapshots) != 1:
            raise unavailable()
        snapshot = snapshots[0]
        calculations = records(
            session,
            m.CalculationRunModel,
            m.CalculationRunModel.id == snapshot["calculation_run_id"],
            m.CalculationRunModel.broker_account_id == auth.account_id,
        )
        if (
            len(calculations) != 1
            or digest((str(header.subject_id), calculations[0]["output_fingerprint"]))
            != header.content_digest
            or snapshot["portfolio_total"] is None
        ):
            raise unavailable()
        initial = ProjectionSnapshotValue(
            account_id=auth.account_id,
            snapshot_id=header.subject_id,
            valuation_at=snapshot["valuation_at"],
            content_digest=header.content_digest,
            value=Money(snapshot["portfolio_total"], CurrencyCode(snapshot["reporting_currency"])),
        )
        proof.update(
            snapshot=snapshot,
            calculation=calculations[0],
            positions=records(
                session,
                m.SnapshotPositionModel,
                m.SnapshotPositionModel.snapshot_id == header.subject_id,
            ),
            cash=records(
                session, m.SnapshotCashModel, m.SnapshotCashModel.snapshot_id == header.subject_id
            ),
        )
        return proof, initial, QualityState(snapshot["quality_state"])
    if header.kind == "historical_input":
        size = session.scalar(
            select(func.octet_length(hm.HistoricalInputModel.canonical_input)).where(
                hm.HistoricalInputModel.id == header.subject_id,
                hm.HistoricalInputModel.owner_id == auth.owner_id,
                hm.HistoricalInputModel.broker_account_id == auth.account_id,
            )
        )
        if not isinstance(size, int) or not 0 < size <= 33_554_432:
            raise unavailable()
        payload = session.scalar(
            select(hm.HistoricalInputModel.canonical_input).where(
                hm.HistoricalInputModel.id == header.subject_id,
                hm.HistoricalInputModel.owner_id == auth.owner_id,
                hm.HistoricalInputModel.broker_account_id == auth.account_id,
            )
        )
        if payload is None:
            raise unavailable()
        value = historical_input_from_json(bounded(payload))
        if (
            value.owner_id != str(auth.owner_id)
            or value.account_id != str(auth.account_id)
            or historical_input_digest(value) != header.content_digest
        ):
            raise unavailable()
        # Complete immutable evidence, including its original canonical byte spelling.
        proof["canonical_input"] = payload.decode("utf-8")
        return proof, None, quality(value)
    model = (
        sm.PriceSnapshotModel if header.kind == "price_total_return" else sm.BenchmarkSnapshotModel
    )
    source_row = session.scalar(
        select(model).where(model.id == header.subject_id, model.owner_id == auth.owner_id)
    )
    if not isinstance(source_row, sm.PriceSnapshotModel | sm.BenchmarkSnapshotModel):
        raise unavailable()
    observation = (
        sm.PriceObservationModel
        if header.kind == "price_total_return"
        else sm.BenchmarkObservationModel
    )
    original_observations = records(
        session,
        observation,
        observation.snapshot_id == source_row.id,
        observation.owner_id == auth.owner_id,
        order=observation.ordinal,
    )
    field = "price_snapshot_id" if header.kind == "price_total_return" else "benchmark_snapshot_id"
    original_gaps = records(
        session,
        sm.SourceCoverageGapModel,
        getattr(sm.SourceCoverageGapModel, field) == source_row.id,
        sm.SourceCoverageGapModel.owner_id == auth.owner_id,
        order=sm.SourceCoverageGapModel.ordinal,
    )
    if source_row.series_id is None:
        raise unavailable()
    series = store._metadata(session, auth, sm.MarketSourceSeriesModel, source_row.series_id)
    calendar = records(
        session,
        sm.SourceCalendarModel,
        sm.SourceCalendarModel.id == series["calendar_id"],
        sm.SourceCalendarModel.owner_id == auth.owner_id,
    )
    calendar_sessions = records(
        session,
        sm.SourceCalendarSessionModel,
        sm.SourceCalendarSessionModel.calendar_id == series["calendar_id"],
        sm.SourceCalendarSessionModel.owner_id == auth.owner_id,
        order=sm.SourceCalendarSessionModel.session_date,
    )
    mapping = (
        ()
        if series.get("mapping_id") is None
        else records(
            session,
            sm.MarketDataInstrumentModel,
            sm.MarketDataInstrumentModel.id == series["mapping_id"],
            sm.MarketDataInstrumentModel.owner_id == auth.owner_id,
        )
    )
    mapping_candidates = (
        ()
        if series.get("mapping_id") is None
        else records(
            session,
            sm.SourceMappingCandidateModel,
            sm.SourceMappingCandidateModel.mapping_id == series["mapping_id"],
            sm.SourceMappingCandidateModel.owner_id == auth.owner_id,
            order=sm.SourceMappingCandidateModel.ordinal,
        )
    )
    source_value = store._sources._load_snapshot(session, source_row)
    if not isinstance(source_value, PriceSnapshot | BenchmarkSnapshot):
        raise unavailable()
    if (
        source_snapshot_digest(source_value) != header.content_digest
        or source_row.content_digest != header.content_digest
    ):
        raise unavailable()
    if digest(source_value.series) != series["content_digest"]:
        raise unavailable()
    complete_calendar = store._sources._calendar(session, auth.owner_id, series["calendar_id"])
    if len(calendar) != 1 or digest(complete_calendar) != calendar[0]["content_digest"]:
        raise unavailable()
    proof.update(
        snapshot=source_value,
        original_observations=original_observations,
        original_gaps=original_gaps,
        series=series,
        mapping=mapping,
        mapping_candidates=mapping_candidates,
        calendar=calendar[0],
        calendar_sessions=calendar_sessions,
    )
    bounded(canonical_json(proof).encode())
    return proof, None, quality(source_value)
