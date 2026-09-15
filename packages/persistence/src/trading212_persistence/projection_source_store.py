"""Closed original calibration evidence; UUID/digest pins never grant authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_application import sources as source_app
from trading212_application.projection_capture import ProjectionSnapshotValue
from trading212_domain.enums import QualityState
from trading212_domain.projection import PROJECTION_MAX_BYTES, ProjectionSourcePin
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceUse
from trading212_domain.values import require_utc
from trading212_security.principals import Scope

from . import historical_models as hm
from . import models as m
from . import source_models as sm
from .historical_base import REFERENCE_MODELS
from .projection_definition_store import ProjectionStorageError, projection_owner_lock
from .projection_source_memberships import retained_source_keys
from .report_authorization import ReportAuthorization
from .source_service import PostgresSourceService
from .source_store import digest

SourceKind = Literal[
    "historical_input", "price_total_return", "benchmark_total_return", "portfolio_snapshot"
]
SourceRole = Literal["initial_snapshot", "calibration"]
MAX_SOURCE_ROWS = 100_000
_METADATA = frozenset(
    (
        "id",
        "owner_id",
        "broker_account_id",
        "created_at",
        "content_digest",
        "input_digest",
        "request_digest",
        "source_cutoff_at",
        "valuation_at",
        "reporting_currency",
        "sealed",
        "policy_id",
        "benchmark_version_id",
        "target_version_id",
        "period_start",
        "period_end",
        "knowledge_policy",
        "provider_id",
        "license_version_id",
        "series_id",
        "calendar_id",
        "mapping_id",
        "instrument_id",
        "listing_id",
        "kind",
        "basis",
        "currency",
        "snapshot_kind",
        "source_record_id",
        "new_source_record_id",
        "superseded_source_record_id",
        "calculation_run_id",
        "payload_fingerprint",
        "observed_at",
        "source_updated_at",
        "completed_at",
        "status",
        "first_observed_at",
        "effective_at",
        "valid_from",
        "valid_to",
        "version",
        "key",
        "quality",
        "quality_state",
        "expires_at",
        "economic_digest",
        "request_fingerprint",
        "input_fingerprint",
        "output_fingerprint",
        "first_known_at",
    )
)
_HISTORY_KINDS = frozenset(
    (
        "ingestion_run",
        "broker_source_record",
        "broker_source_occurrence",
        "portfolio_snapshot",
        "calculation_run",
        "reconciliation_run",
        "price_snapshot",
        "fx_snapshot",
        "corporate_action_snapshot",
        "provider_benchmark_snapshot",
        "instrument_mapping",
        "calendar_version",
        "provider_license_version",
        "benchmark_version",
        "target_version",
        "classification_evidence",
        "historical_evidence",
        "activity_revision_evidence",
    )
)
_PHYSICAL = {
    "price_snapshot": sm.PriceSnapshotModel,
    "fx_snapshot": sm.FxSnapshotModel,
    "corporate_action_snapshot": sm.CorporateActionSnapshotModel,
    "provider_benchmark_snapshot": sm.BenchmarkSnapshotModel,
}


def unavailable() -> ProjectionStorageError:
    return ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)


def bounded(payload: bytes) -> bytes:
    if not payload or len(payload) > PROJECTION_MAX_BYTES:
        raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
    return payload


def records(
    session: Session, model: Any, *conditions: Any, order: Any = None
) -> tuple[dict[str, Any], ...]:
    """Private complete-row load; callers must authorize and count before entering."""
    count = session.scalar(select(func.count()).select_from(model).where(*conditions))
    size = session.scalar(
        select(func.coalesce(func.sum(func.pg_column_size(model.__table__.table_valued())), 0))
        .select_from(model)
        .where(*conditions)
    )
    if count is None or count > MAX_SOURCE_ROWS or size is None or size > PROJECTION_MAX_BYTES:
        raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
    query = (
        select(*model.__table__.columns)
        .where(*conditions)
        .order_by(order if order is not None else model.id)
    )
    result = tuple(
        dict(row) for row in session.execute(query.limit(MAX_SOURCE_ROWS + 1)).mappings()
    )
    if len(result) != count:
        raise unavailable()
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionSourceHeader:
    kind: SourceKind
    role: SourceRole
    subject_id: UUID
    content_digest: str
    original_created_at: datetime
    expires_at: datetime
    metadata: tuple[dict[str, Any], ...]
    license_version_ids: tuple[UUID, ...]
    # Closed physical source identities collected during the same authorized traversal.
    retained_sources: tuple[tuple[str, UUID, datetime], ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCapturedSource:
    header: ProjectionSourceHeader
    quality: QualityState
    canonical_proof: bytes

    @property
    def proof_digest(self) -> str:
        return sha256(self.canonical_proof).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionSourceBundle:
    snapshot: ProjectionSnapshotValue | None
    sources: tuple[ProjectionCapturedSource, ...]
    expires_at: datetime
    license_version_ids: tuple[UUID, ...]


class ProjectionSourceStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sources = PostgresSourceService(
            sessions=sessions, cursor_signing_key=cursor_signing_key, clock=self._clock
        )

    def _now(self) -> datetime:
        return require_utc(self._clock())

    def _metadata(
        self, session: Session, auth: ReportAuthorization, model: Any, identifier: UUID
    ) -> dict[str, Any]:
        names = tuple(column.name for column in model.__table__.columns if column.name in _METADATA)
        query = select(*(getattr(model, name) for name in names)).where(model.id == identifier)
        if hasattr(model, "owner_id"):
            query = query.where(model.owner_id == auth.owner_id)
        if hasattr(model, "broker_account_id"):
            query = query.where(model.broker_account_id == auth.account_id)
        value = session.execute(query).mappings().one_or_none()
        if value is None:
            raise unavailable()
        return {"table": model.__tablename__, **dict(value)}

    def _license(
        self, session: Session, auth: ReportAuthorization, identifier: UUID, original_at: datetime
    ) -> datetime:
        # Explicitly check both uses on the immutable pinned and current license.
        try:
            license = self._sources._permit(session, auth.owner_id, identifier, SourceUse.STORE)
            self._sources._permit(session, auth.owner_id, identifier, SourceUse.DISPLAY)
        except source_app.SourceServiceError:
            raise ProjectionStorageError(app.ProjectionErrorCode.ACCESS_DENIED) from None
        current = self._sources._current_license(session, auth.owner_id, UUID(license.provider_id))
        if current is None or current.retention_days is None or license.retention_days is None:
            raise unavailable()
        deadline = original_at + timedelta(
            days=min(30, license.retention_days, current.retention_days)
        )
        if deadline <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        return deadline

    def _physical(
        self, session: Session, auth: ReportAuthorization, model: Any, identifier: UUID
    ) -> tuple[dict[str, Any], datetime, UUID]:
        row = self._metadata(session, auth, model, identifier)
        if row.get("snapshot_kind", "provider_series") != "provider_series":
            raise unavailable()
        at, expiry, license_id = (
            row.get("created_at"),
            row.get("expires_at"),
            row.get("license_version_id"),
        )
        if (
            not isinstance(at, datetime)
            or at > self._now()
            or not isinstance(expiry, datetime)
            or not isinstance(license_id, UUID)
        ):
            raise unavailable()
        field = str(model.__tablename__).removesuffix("s") + "_id"
        for marker in (sm.SourceRetentionWorkModel, sm.SourceExpiryEventModel):
            if (
                session.scalar(
                    select(marker.id)
                    .where(marker.owner_id == auth.owner_id, getattr(marker, field) == identifier)
                    .limit(1)
                )
                is not None
            ):
                raise unavailable()
        license = self._metadata(session, auth, sm.ProviderLicenseVersionModel, license_id)
        if license.get("provider_id") != row.get("provider_id"):
            raise unavailable()
        expiry = min(expiry, self._license(session, auth, license_id, at))
        if expiry <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        return row, expiry, license_id

    def _history(
        self,
        session: Session,
        auth: ReportAuthorization,
        pin: ProjectionSourcePin,
        *,
        retained_at: datetime | None = None,
    ) -> ProjectionSourceHeader:
        identifier = UUID(pin.subject_id)
        root = self._metadata(session, auth, hm.HistoricalInputModel, identifier)
        scopes = auth.required_scopes | {Scope.ACTIVITY_READ}
        if root.get("target_version_id") is not None:
            scopes |= {Scope.TARGETS_READ}
        auth = replace(auth, required_scopes=frozenset(scopes))
        auth.check(session, now=self._now())
        if root.get("sealed") is not True or root.get("input_digest") != pin.content_digest:
            raise unavailable()
        if (
            session.scalar(
                select(hm.HistoricalRetentionEventModel.id)
                .where(
                    hm.HistoricalRetentionEventModel.owner_id == auth.owner_id,
                    hm.HistoricalRetentionEventModel.input_id == identifier,
                )
                .limit(1)
            )
            is not None
        ):
            raise unavailable()
        original = cast(datetime, root["created_at"])
        if original > self._now() or root["source_cutoff_at"] > self._now():
            raise unavailable()
        expiry = (retained_at or self._now()) + timedelta(days=30)
        metadata = [root]
        metadata_bytes = len(canonical_json(root).encode())
        licenses: set[UUID] = set()
        retained_sources = {("historical", identifier, original)}
        pending: list[tuple[UUID, bool]] = [(identifier, False)]
        visited: set[tuple[UUID, bool]] = set()
        rows_seen = 0
        while pending:
            subject, evidence = pending.pop()
            if (subject, evidence) in visited:
                continue
            visited.add((subject, evidence))
            relation = hm.HistoricalDependencyModel
            condition = (
                relation.evidence_id == subject if evidence else relation.input_id == subject
            )
            # This relation contains identities only, never financial or BYTEA fields.
            rows = session.scalars(
                select(relation)
                .where(relation.owner_id == auth.owner_id, condition)
                .order_by(relation.id)
                .limit(MAX_SOURCE_ROWS - rows_seen + 1)
            ).all()
            rows_seen += len(rows)
            if rows_seen > MAX_SOURCE_ROWS:
                raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
            for link in rows:
                kind, raw_id = link.reference_key.split(":", 1)
                if kind not in _HISTORY_KINDS:
                    raise unavailable()
                model, field = REFERENCE_MODELS[kind]
                source_id = UUID(raw_id)
                if getattr(link, field) != source_id:
                    raise unavailable()
                if evidence and kind == "historical_evidence":
                    # Existing historical admission is flat: input -> evidence -> source.
                    raise unavailable()
                if kind in _PHYSICAL:
                    header, until, license_id = self._physical(session, auth, model, source_id)
                    parent_kind = {
                        "price_snapshot": "price",
                        "fx_snapshot": "fx",
                        "corporate_action_snapshot": "corporate_action",
                        "provider_benchmark_snapshot": "benchmark",
                    }[kind]
                    retained_sources.add(
                        (parent_kind, source_id, cast(datetime, header["created_at"]))
                    )
                    licenses.add(license_id)
                    expiry = min(expiry, until)
                else:
                    header = self._metadata(session, auth, model, source_id)
                    metadata_license_id = (
                        source_id
                        if kind == "provider_license_version"
                        else header.get("license_version_id")
                    )
                    if isinstance(metadata_license_id, UUID):
                        licenses.add(metadata_license_id)
                        source_at = (
                            original
                            if kind == "provider_license_version"
                            else header.get("created_at")
                        )
                        if not isinstance(source_at, datetime):
                            raise unavailable()
                        expiry = min(
                            expiry,
                            self._license(session, auth, metadata_license_id, source_at),
                            self._license(session, auth, metadata_license_id, original),
                        )
                    if kind == "provider_license_version":
                        retained_sources.add(("license", source_id, original))
                    elif kind == "classification_evidence":
                        retained_sources.add(
                            (
                                "classification",
                                source_id,
                                min(original, cast(datetime, header["created_at"])),
                            )
                        )
                    if kind == "historical_evidence":
                        if header.get("sealed") is not True:
                            raise unavailable()
                        pending.append((source_id, True))
                    if kind == "target_version":
                        auth = replace(
                            auth, required_scopes=auth.required_scopes | {Scope.TARGETS_READ}
                        )
                        auth.check(session, now=self._now())
                    for parent_name in (
                        "source_record_id",
                        "new_source_record_id",
                        "superseded_source_record_id",
                    ):
                        parent = header.get(parent_name)
                        if isinstance(parent, UUID):
                            metadata.append(
                                self._metadata(session, auth, m.SourceRecordModel, parent)
                            )
                metadata_bytes += len(canonical_json(header).encode())
                if metadata_bytes > PROJECTION_MAX_BYTES:
                    raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
                metadata.append(header)
                if len(licenses) > 8192:
                    raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        if expiry <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        return ProjectionSourceHeader(
            kind="historical_input",
            role="calibration",
            subject_id=identifier,
            content_digest=pin.content_digest,
            original_created_at=original,
            expires_at=expiry,
            metadata=tuple(metadata),
            license_version_ids=tuple(sorted(licenses)),
            retained_sources=tuple(sorted(retained_sources)),
        )

    def _calibration(
        self,
        session: Session,
        auth: ReportAuthorization,
        pin: ProjectionSourcePin,
        *,
        retained_at: datetime | None = None,
    ) -> ProjectionSourceHeader:
        identifier = UUID(pin.subject_id)
        choices = []
        for kind, model in (
            ("historical_input", hm.HistoricalInputModel),
            ("price_total_return", sm.PriceSnapshotModel),
            ("benchmark_total_return", sm.BenchmarkSnapshotModel),
        ):
            query = select(model.id).where(model.id == identifier, model.owner_id == auth.owner_id)
            if kind == "historical_input":
                query = query.where(hm.HistoricalInputModel.broker_account_id == auth.account_id)
            if session.scalar(query) is not None:
                choices.append((kind, model))
        if len(choices) != 1:
            raise unavailable()
        kind, model = choices[0]
        if kind == "historical_input":
            return self._history(session, auth, pin, retained_at=retained_at)
        header, expiry, license_id = self._physical(session, auth, model, identifier)
        if header["content_digest"] != pin.content_digest:
            raise unavailable()
        series = self._metadata(session, auth, sm.MarketSourceSeriesModel, header["series_id"])
        expected_kind = "security_price" if kind == "price_total_return" else "benchmark_level"
        if (
            series.get("kind") != expected_kind
            or series.get("basis") != "total_return"
            or any(
                series.get(name) != header.get(name)
                for name in ("provider_id", "license_version_id")
            )
        ):
            raise unavailable()
        metadata = [
            header,
            series,
            self._metadata(session, auth, sm.SourceCalendarModel, series["calendar_id"]),
        ]
        if series.get("mapping_id") is not None:
            mapping = self._metadata(
                session, auth, sm.MarketDataInstrumentModel, series["mapping_id"]
            )
            if mapping.get("provider_id") != series["provider_id"] or mapping.get(
                "instrument_id"
            ) != series.get("instrument_id"):
                raise unavailable()
            metadata.append(mapping)
        return ProjectionSourceHeader(
            kind=cast(SourceKind, kind),
            role="calibration",
            subject_id=identifier,
            content_digest=pin.content_digest,
            original_created_at=header["created_at"],
            expires_at=expiry,
            metadata=tuple(metadata),
            license_version_ids=(license_id,),
            retained_sources=(
                (
                    "price" if kind == "price_total_return" else "benchmark",
                    identifier,
                    cast(datetime, header["created_at"]),
                ),
            ),
        )

    def resolve_calibration(
        self,
        session: Session,
        authorization: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        use: SourceUse,
        now: datetime,
    ) -> None:
        authorization.check(session, now=now)
        if (
            use not in (SourceUse.STORE, SourceUse.DISPLAY)
            or len(pins) > 256
            or len({p.subject_id for p in pins}) != len(pins)
        ):
            raise unavailable()
        if pins:
            projection_owner_lock(session, authorization.owner_id)
        for pin in pins:
            self._calibration(session, authorization, pin)
        authorization.check(session, now=self._now())

    def _snapshot_header(
        self,
        session: Session,
        auth: ReportAuthorization,
        identifier: UUID,
        *,
        retained_at: datetime | None = None,
    ) -> ProjectionSourceHeader:
        row = self._metadata(session, auth, m.PortfolioSnapshotModel, identifier)
        calculation = self._metadata(
            session, auth, m.CalculationRunModel, row["calculation_run_id"]
        )
        if (
            row["valuation_at"] > self._now()
            or row["reporting_currency"] != calculation["reporting_currency"]
        ):
            raise unavailable()
        expiry = (retained_at or self._now()) + timedelta(days=30)
        if expiry <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.RUN_EXPIRED)
        return ProjectionSourceHeader(
            kind="portfolio_snapshot",
            role="initial_snapshot",
            subject_id=identifier,
            content_digest=digest((str(identifier), calculation["output_fingerprint"])),
            original_created_at=row["created_at"],
            expires_at=expiry,
            metadata=(row, calculation),
            license_version_ids=(),
        )

    def authorize_sources(
        self,
        session: Session,
        auth: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        snapshot_id: UUID | None = None,
        retained_at: datetime | None = None,
    ) -> tuple[tuple[ProjectionSourceHeader, ...], datetime]:
        """Metadata-only final-return/publication seam, with current source deadline."""
        auth.check(session, now=self._now())
        if len(pins) > 256 or len({p.subject_id for p in pins}) != len(pins):
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        if pins or snapshot_id is not None:
            projection_owner_lock(session, auth.owner_id)
        headers = []
        metadata_bytes = 0
        for pin in pins:
            header = self._calibration(session, auth, pin, retained_at=retained_at)
            metadata_bytes += len(canonical_json(header.metadata).encode())
            if metadata_bytes > PROJECTION_MAX_BYTES:
                raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
            headers.append(header)
        if snapshot_id is not None:
            headers.insert(
                0, self._snapshot_header(session, auth, snapshot_id, retained_at=retained_at)
            )
        retained_source_keys(headers)
        if len({i for h in headers for i in h.license_version_ids}) > 8192:
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        deadline = min(
            (h.expires_at for h in headers),
            default=(retained_at or self._now()) + timedelta(days=30),
        )
        deadline = min(deadline, (retained_at or self._now()) + timedelta(days=30))
        auth.check(session, now=self._now())
        return tuple(headers), deadline

    def capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        snapshot_id: UUID | None = None,
        retained_at: datetime | None = None,
    ) -> ProjectionSourceBundle:
        auth.check(session, now=self._now())
        if len(pins) > 256 or len({p.subject_id for p in pins}) != len(pins):
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        # Resolve every source before the first private payload or financial SELECT.
        if pins or snapshot_id is not None:
            projection_owner_lock(session, auth.owner_id)
        headers = []
        metadata_bytes = 0
        for pin in pins:
            header = self._calibration(session, auth, pin, retained_at=retained_at)
            metadata_bytes += len(canonical_json(header.metadata).encode())
            if metadata_bytes > PROJECTION_MAX_BYTES:
                raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
            headers.append(header)
        if snapshot_id is not None:
            headers.insert(
                0, self._snapshot_header(session, auth, snapshot_id, retained_at=retained_at)
            )
        retained_source_keys(headers)
        if len({i for h in headers for i in h.license_version_ids}) > 8192:
            raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
        sources: list[ProjectionCapturedSource] = []
        snapshot = None
        total = 0
        for header in headers:
            value, initial, quality = self._proof(session, auth, header)
            payload = bounded(canonical_json(value).encode())
            total += len(payload)
            if total > PROJECTION_MAX_BYTES:
                raise ProjectionStorageError(app.ProjectionErrorCode.INPUT_BOUND_EXCEEDED)
            sources.append(
                ProjectionCapturedSource(header=header, quality=quality, canonical_proof=payload)
            )
            if initial is not None:
                snapshot = initial
        current_headers, _deadline = self.authorize_sources(
            session, auth, pins, snapshot_id=snapshot_id, retained_at=retained_at
        )
        if any(
            a.kind != b.kind
            or a.subject_id != b.subject_id
            or a.content_digest != b.content_digest
            or a.metadata != b.metadata
            or a.license_version_ids != b.license_version_ids
            or a.retained_sources != b.retained_sources
            for a, b in zip(headers, current_headers, strict=True)
        ):
            raise unavailable()
        auth.check(session, now=self._now())
        deadline = min(
            (h.expires_at for h in current_headers),
            default=(retained_at or self._now()) + timedelta(days=30),
        )
        deadline = min(deadline, (retained_at or self._now()) + timedelta(days=30))
        return ProjectionSourceBundle(
            snapshot=snapshot,
            sources=tuple(sources),
            expires_at=deadline,
            license_version_ids=tuple(sorted({i for h in headers for i in h.license_version_ids})),
        )

    def _proof(
        self, session: Session, auth: ReportAuthorization, header: ProjectionSourceHeader
    ) -> tuple[Mapping[str, Any], ProjectionSnapshotValue | None, QualityState]:
        from .projection_source_proof import original_projection_proof

        return original_projection_proof(self, session, auth, header)
