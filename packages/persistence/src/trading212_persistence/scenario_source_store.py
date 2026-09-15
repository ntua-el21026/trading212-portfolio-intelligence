"""Private owned sensitivity publication and metadata-first authorization/decode."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session, sessionmaker, undefer
from trading212_application import sources as source_app
from trading212_domain import scenario_sources as domain_sources
from trading212_domain.errors import DomainError
from trading212_domain.scenario import MAX_SCENARIO_BYTES, ScenarioSensitivityVersionPin
from trading212_domain.scenario_serialization import (
    scenario_record_bytes,
    scenario_sensitivity_capture_from_json,
    scenario_sensitivity_evidence_from_json,
    scenario_sensitivity_observation_from_json,
    scenario_sensitivity_version_from_json,
)
from trading212_domain.scenario_sources import (
    ScenarioSensitivityCapture,
    ScenarioSensitivityMembership,
    ScenarioSourceLicense,
)
from trading212_domain.sources import SourceLicense, SourceUse
from trading212_domain.values import require_utc
from trading212_security.principals import Scope

from .report_authorization import ReportAuthorization
from .scenario_retention_boundary import require_scenario_retention
from .scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel as Link,
)
from .scenario_source_models import (
    ScenarioSensitivityEvidenceModel as Evidence,
)
from .scenario_source_models import (
    ScenarioSensitivityEvidencePayloadModel as EvidencePayload,
)
from .scenario_source_models import (
    ScenarioSensitivityMembershipModel as Membership,
)
from .scenario_source_models import (
    ScenarioSensitivityObservationModel as Observation,
)
from .scenario_source_models import (
    ScenarioSensitivityObservationPayloadModel as ObservationPayload,
)
from .scenario_source_models import (
    ScenarioSensitivityRetentionModel as Retention,
)
from .scenario_source_models import (
    ScenarioSensitivityVersionModel as Version,
)
from .scenario_source_models import (
    ScenarioSensitivityVersionPayloadModel as VersionPayload,
)
from .scenario_source_projection import SOURCE_PUBLICATION_MODELS, normalized_sensitivity_rows
from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code
from .source_models import SourceOwned, SourceSnapshotFields
from .source_service import PostgresSourceService


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizedScenarioSources:
    capture: ScenarioSensitivityCapture
    expires_at: datetime
    license_version_ids: tuple[UUID, ...]


class ScenarioCopySources(PostgresSourceService):
    """One per capture, shared with the existing X-ray and historical readers."""

    def begin_copy(self, *, retained_at: datetime, required_copy_use: SourceUse | None) -> None:
        self.copy_created_at = require_utc(retained_at)
        self.required_copy_use = required_copy_use
        self.copy_deadline = self.copy_created_at + timedelta(days=30)
        self.copy_licenses: dict[UUID, SourceLicense] = {}
        self.max_copy_licenses = 256 if required_copy_use is SourceUse.REPORT else 8192

    def _permit(
        self, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> SourceLicense:
        try:
            license = super()._permit(session, owner, license_id, use)
            super()._permit(session, owner, license_id, SourceUse.STORE)
            super()._permit(session, owner, license_id, SourceUse.DISPLAY)
            if self.required_copy_use is not None:
                super()._permit(session, owner, license_id, self.required_copy_use)
            current = self._current_license(session, owner, UUID(license.provider_id))
        except source_app.SourceServiceError:
            raise ScenarioStorageError(Code.ACCESS_DENIED) from None
        if current is None or current.retention_days is None or license.retention_days is None:
            raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
        self.copy_licenses[license_id] = license
        if len(self.copy_licenses) > self.max_copy_licenses:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        self.copy_deadline = min(
            self.copy_deadline,
            self.copy_created_at
            + timedelta(days=min(30, license.retention_days, current.retention_days)),
        )
        if self.copy_deadline <= self._now():
            raise ScenarioStorageError(Code.RUN_EXPIRED)
        return license

    def _snapshot_permit(
        self, session: Session, row: SourceSnapshotFields, use: SourceUse = SourceUse.DISPLAY
    ) -> SourceLicense:
        license = super()._snapshot_permit(session, row, use)
        self.copy_deadline = min(self.copy_deadline, row.expires_at)
        return license

    def original_permit(
        self, session: Session, row: Version | Observation | Evidence
    ) -> SourceLicense:
        """A new copy never renews the storage lifetime of its original source."""
        license = self._permit(session, row.owner_id, row.license_version_id, SourceUse.DISPLAY)
        current = self._current_license(session, row.owner_id, UUID(license.provider_id))
        if current is None or current.retention_days is None or license.retention_days is None:
            raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
        original_deadline = row.created_at + timedelta(
            days=min(30, license.retention_days, current.retention_days)
        )
        if isinstance(row, Version):
            original_deadline = min(original_deadline, row.expires_at)
        self.copy_deadline = min(self.copy_deadline, original_deadline)
        if self.copy_deadline <= self._now():
            raise ScenarioStorageError(Code.RUN_EXPIRED)
        return license


class ScenarioSourceStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._cursor_key = cursor_signing_key
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    def copy_authority(
        self, *, retained_at: datetime | None = None, required_copy_use: SourceUse | None = None
    ) -> ScenarioCopySources:
        sources = ScenarioCopySources(
            sessions=self._sessions, cursor_signing_key=self._cursor_key, clock=self._clock
        )
        sources.begin_copy(
            retained_at=retained_at or self._now(), required_copy_use=required_copy_use
        )
        return sources

    def publish_capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        capture: ScenarioSensitivityCapture,
        *,
        expires_at: datetime,
    ) -> None:
        """Only fixed in-process adapters/fixtures call this; it is not a source API."""
        auth = replace(
            auth,
            required_scopes=auth.required_scopes
            | {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.SCENARIOS_WRITE},
        )
        auth.check(session, now=self._now())
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{auth.owner_id}"},
        )
        payload = scenario_record_bytes(capture)
        if len(payload) > MAX_SCENARIO_BYTES:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        capture = scenario_sensitivity_capture_from_json(payload)
        owned_records: tuple[
            domain_sources.ScenarioSensitivitySourceVersion
            | domain_sources.ScenarioSensitivityObservation
            | domain_sources.ScenarioSensitivityEvidence,
            ...,
        ] = (*capture.versions, *capture.observations, *capture.evidence)
        if any(item.owner_id != auth.owner_id for item in owned_records):
            raise ScenarioStorageError(Code.ACCESS_DENIED)
        sources = self.copy_authority()
        for item in capture.licenses:
            if (
                sources._permit(session, auth.owner_id, item.license_version_id, SourceUse.DISPLAY)
                != item.license
            ):
                raise ScenarioStorageError(Code.CONFLICT)
        original_headers: list[Version | Observation | Evidence] = []
        for source_model, identifiers in (
            (Version, tuple(item.version_id for item in capture.versions)),
            (Observation, tuple(item.observation_id for item in capture.observations)),
            (Evidence, tuple(item.id for item in capture.evidence)),
        ):
            for begin in range(0, len(identifiers), 500):
                for original in session.scalars(
                    select(source_model).where(
                        source_model.owner_id == auth.owner_id,
                        source_model.id.in_(identifiers[begin : begin + 500]),
                    )
                ):
                    if not isinstance(original, (Version, Observation, Evidence)):
                        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
                    sources.original_permit(session, original)
                    original_headers.append(original)
        expiry = min(require_utc(expires_at), sources.copy_deadline)
        if expiry <= self._now():
            raise ScenarioStorageError(Code.RUN_EXPIRED)
        sets: dict[UUID, UUID] = {}
        for version in capture.versions:
            if version.source_set_id in sets and sets[version.source_set_id] != version.provider_id:
                raise ScenarioStorageError(Code.CONFLICT)
            sets[version.source_set_id] = version.provider_id
        rows = normalized_sensitivity_rows(capture, expires_at=expiry)
        new_versions: list[UUID] = []
        for model in SOURCE_PUBLICATION_MODELS:
            values_for_model = rows[model]
            for begin in range(0, len(values_for_model), 500):
                auth.check(session, now=self._now())
                batch = values_for_model[begin : begin + 500]
                query = select(model).where(
                    model.owner_id == auth.owner_id, model.id.in_(values["id"] for values in batch)
                )
                if model in (VersionPayload, ObservationPayload, EvidencePayload):
                    query = query.options(undefer("*"))
                actual = {row.id: row for row in session.scalars(query)}
                additions = []
                for values in batch:
                    row = actual.get(cast(UUID, values["id"]))
                    if row is not None:
                        if isinstance(row, Version) and (
                            not row.sealed
                            or row.expires_at <= self._now()
                            or session.scalar(
                                select(Retention.id).where(Retention.version_id == row.id)
                            )
                        ):
                            raise ScenarioStorageError(Code.RUN_EXPIRED)
                        for name, expected in values.items():
                            if model is Version and name in ("sealed", "expires_at"):
                                continue
                            if getattr(row, name) != expected:
                                raise ScenarioStorageError(Code.CONFLICT)
                    else:
                        additions.append(dict(values, created_at=self._now()))
                        if model is Version:
                            new_versions.append(cast(UUID, values["id"]))
                if additions:
                    session.execute(insert(model), additions)
        if new_versions:
            session.execute(
                update(Version)
                .where(Version.id.in_(new_versions), Version.owner_id == auth.owner_id)
                .values(sealed=True)
            )
        session.flush()
        for item in capture.licenses:
            sources._permit(session, auth.owner_id, item.license_version_id, SourceUse.DISPLAY)
        for original in original_headers:
            sources.original_permit(session, original)
        auth.check(session, now=self._now())
        require_scenario_retention(
            expires_at=expiry, copy_deadline=sources.copy_deadline, now=self._now()
        )

    def read_capture(
        self,
        session: Session,
        auth: ReportAuthorization,
        pins: tuple[ScenarioSensitivityVersionPin, ...],
        *,
        retained_at: datetime | None = None,
        required_copy_use: SourceUse | None = None,
        sources: ScenarioCopySources | None = None,
    ) -> AuthorizedScenarioSources:
        auth = replace(
            auth,
            required_scopes=auth.required_scopes | {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ},
        )
        auth.check(session, now=self._now())
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{auth.owner_id}"},
        )
        if (
            type(pins) is not tuple
            or len(pins) > 128
            or any(type(pin) is not ScenarioSensitivityVersionPin for pin in pins)
        ):
            raise ScenarioStorageError(Code.VALIDATION_FAILED)
        wanted = {pin.version_id: pin for pin in pins}
        if len(wanted) != len(pins):
            raise ScenarioStorageError(Code.CONFLICT)
        sources = sources or self.copy_authority(
            retained_at=retained_at, required_copy_use=required_copy_use
        )
        versions = tuple(
            session.scalars(
                select(Version)
                .where(Version.owner_id == auth.owner_id, Version.id.in_(wanted))
                .order_by(Version.id)
                .limit(129)
            )
        )
        if len(versions) != len(wanted):
            raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
        if sum(v.observation_count + v.membership_count for v in versions) > 100000:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        for version in versions:
            pin = wanted[version.id]
            if (
                not version.sealed
                or version.expires_at <= self._now()
                or session.scalar(
                    select(Retention.id).where(
                        Retention.owner_id == auth.owner_id, Retention.version_id == version.id
                    )
                )
            ):
                raise ScenarioStorageError(Code.RUN_EXPIRED)
            if (
                version.content_digest,
                version.driver_id,
                version.driver_definition_version_id,
            ) != (pin.content_digest, pin.driver_id, pin.driver_definition_version_id):
                raise ScenarioStorageError(Code.CONFLICT)
            sources.original_permit(session, version)
        observations = tuple(
            session.scalars(
                select(Observation)
                .where(Observation.owner_id == auth.owner_id, Observation.version_id.in_(wanted))
                .order_by(Observation.id)
                .limit(100001)
            )
        )
        memberships = tuple(
            session.scalars(
                select(Membership)
                .where(Membership.owner_id == auth.owner_id, Membership.version_id.in_(wanted))
                .order_by(Membership.id)
                .limit(100001)
            )
        )
        evidence = tuple(
            session.scalars(
                select(Evidence)
                .where(
                    Evidence.owner_id == auth.owner_id,
                    Evidence.id.in_(
                        select(Link.evidence_id).where(
                            Link.owner_id == auth.owner_id, Link.version_id.in_(wanted)
                        )
                    ),
                )
                .order_by(Evidence.id)
                .limit(100001)
            )
        )
        if len(observations) + len(memberships) + len(evidence) > 100000:
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        licensed_rows: tuple[Version | Observation | Evidence, ...] = (
            *versions,
            *observations,
            *evidence,
        )
        for row in licensed_rows:
            sources.original_permit(session, row)
        # Every permission above precedes the first source payload selection.
        auth.check(session, now=self._now())
        canonical: dict[type[SourceOwned], dict[UUID, bytes]] = {}
        source_bytes = 0
        for model, column, identities in (
            (VersionPayload, VersionPayload.version_id, tuple(wanted)),
            (
                ObservationPayload,
                ObservationPayload.observation_id,
                tuple(row.id for row in observations),
            ),
            (EvidencePayload, EvidencePayload.evidence_id, tuple(row.id for row in evidence)),
        ):
            count, size = session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(func.octet_length(model.canonical_payload)), 0),
                ).where(model.owner_id == auth.owner_id, column.in_(identities))
            ).one()
            if count != len(identities):
                raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
            source_bytes += size
            if source_bytes > MAX_SCENARIO_BYTES:
                raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
            canonical[model] = dict(
                session.execute(
                    select(column, model.canonical_payload).where(
                        model.owner_id == auth.owner_id, column.in_(identities)
                    )
                )
                .tuples()
                .all()
            )
        if (
            sum(len(payload) for values in canonical.values() for payload in values.values())
            > MAX_SCENARIO_BYTES
        ):
            raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
        try:
            capture = ScenarioSensitivityCapture(
                versions=tuple(
                    scenario_sensitivity_version_from_json(canonical[VersionPayload][row.id])
                    for row in versions
                ),
                observations=tuple(
                    scenario_sensitivity_observation_from_json(
                        canonical[ObservationPayload][row.id]
                    )
                    for row in observations
                ),
                memberships=tuple(
                    ScenarioSensitivityMembership(
                        version_id=row.version_id,
                        version_digest=row.version_digest,
                        observation_id=row.observation_id,
                        observation_digest=row.observation_digest,
                    )
                    for row in memberships
                ),
                evidence=tuple(
                    scenario_sensitivity_evidence_from_json(canonical[EvidencePayload][row.id])
                    for row in evidence
                ),
                licenses=tuple(
                    ScenarioSourceLicense(license_version_id=key, license=value)
                    for key, value in sorted(sources.copy_licenses.items())
                    if key in {row.license_version_id for row in licensed_rows}
                ),
            )
            self._verify_projection(session, auth, capture, sources.copy_deadline)
        except DomainError:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE) from None
        for row in licensed_rows:
            sources.original_permit(session, row)
        auth.check(session, now=self._now())
        return AuthorizedScenarioSources(
            capture=capture,
            expires_at=sources.copy_deadline,
            license_version_ids=tuple(sorted(sources.copy_licenses)),
        )

    def _verify_projection(
        self,
        session: Session,
        auth: ReportAuthorization,
        capture: ScenarioSensitivityCapture,
        expiry: datetime,
    ) -> None:
        expected = normalized_sensitivity_rows(capture, expires_at=expiry)
        for model in SOURCE_PUBLICATION_MODELS:
            values = expected[model]
            for begin in range(0, len(values), 500):
                batch = values[begin : begin + 500]
                query = select(model).where(
                    model.owner_id == auth.owner_id, model.id.in_(item["id"] for item in batch)
                )
                if model in (VersionPayload, ObservationPayload, EvidencePayload):
                    query = query.options(undefer("*"))
                actual = {row.id: row for row in session.scalars(query)}
                for item in batch:
                    row = actual.get(cast(UUID, item["id"]))
                    if row is None:
                        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
                    for name, value in item.items():
                        if model is Version and name in ("sealed", "expires_at"):
                            continue
                        if getattr(row, name) != value:
                            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        versions = tuple(version.version_id for version in capture.versions)
        # Exact inventories reject extra rows that canonical payloads omit.
        for model, column in (
            (Observation, Observation.version_id),
            (Membership, Membership.version_id),
            (Link, Link.version_id),
            (VersionPayload, VersionPayload.version_id),
        ):
            count = session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.owner_id == auth.owner_id, column.in_(versions))
            )
            if count != len(expected[model]):
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
