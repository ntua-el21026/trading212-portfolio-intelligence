"""Owned, separately retained coefficient evidence; definitions contain only pins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from .enums import QualityState
from .errors import fail_validation
from .scenario import (
    MAX_SCENARIO_LICENSES,
    MAX_SCENARIO_RULES,
    MAX_SCENARIO_SENSITIVITY_ROWS,
    ScenarioPriceSelector,
    ScenarioReason,
    ScenarioRecord,
)
from .scenario_validation import scenario_bound, unique
from .sources import ObservationState, SourceAvailability, SourceLicense
from .values import CurrencyCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioInstrumentSubject(ScenarioRecord):
    instrument_id: UUID
    kind: Literal["instrument"] = "instrument"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioEntitySubject(ScenarioRecord):
    entity_id: UUID
    kind: Literal["entity"] = "entity"


type ScenarioSensitivitySubject = ScenarioInstrumentSubject | ScenarioEntitySubject


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRateEquivalence(ScenarioRecord):
    rate_id: UUID
    currency: CurrencyCode
    kind: Literal["rate"] = "rate"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioFactorEquivalence(ScenarioRecord):
    factor_id: UUID
    kind: Literal["factor"] = "factor"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioPriceEquivalence(ScenarioRecord):
    selector: ScenarioPriceSelector
    kind: Literal["price"] = "price"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioFxEquivalence(ScenarioRecord):
    currency: CurrencyCode
    kind: Literal["fx"] = "fx"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioUnknownEquivalence(ScenarioRecord):
    reason: ScenarioReason
    kind: Literal["unknown"] = "unknown"


type ScenarioDriverEquivalence = (
    ScenarioRateEquivalence
    | ScenarioFactorEquivalence
    | ScenarioPriceEquivalence
    | ScenarioFxEquivalence
    | ScenarioUnknownEquivalence
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioDriverReference(ScenarioRecord):
    driver_id: UUID
    definition_version_id: UUID
    definition_digest: str
    kind: Literal["rate", "factor"]
    shock_unit: Literal["absolute_rate_change", "simple_factor_return"]
    equivalence: ScenarioDriverEquivalence
    evidence_reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        if self.shock_unit != (
            "absolute_rate_change" if self.kind == "rate" else "simple_factor_return"
        ):
            fail_validation("Driver unit differs from its kind.", field="shock_unit")
        unique(self.evidence_reference_ids, "evidence_reference_ids")
        object.__setattr__(
            self, "evidence_reference_ids", tuple(sorted(self.evidence_reference_ids))
        )


def _period(value: ScenarioSensitivitySourceVersion | ScenarioSensitivityObservation) -> None:
    if value.valid_until is not None and value.valid_until <= value.valid_from:
        fail_validation("Sensitivity validity interval is empty.", field="valid_until")
    if value.revision < 1:
        fail_validation("Sensitivity revision must be positive.", field="revision")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivitySourceVersion(ScenarioRecord):
    owner_id: UUID
    source_set_id: UUID
    version_id: UUID
    content_digest: str
    provider_id: UUID
    license_version_id: UUID
    adapter_id: str
    adapter_version: str
    driver: ScenarioDriverReference
    effective_at: datetime
    first_known_at: datetime
    valid_from: datetime
    valid_until: datetime | None
    revision: int
    availability: SourceAvailability
    quality: QualityState

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        _period(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityObservation(ScenarioRecord):
    owner_id: UUID
    observation_id: UUID
    version_id: UUID
    content_digest: str
    subject: ScenarioSensitivitySubject
    driver_id: UUID
    driver_definition_version_id: UUID
    coefficient: Decimal | None
    shock_unit: Literal["absolute_rate_change", "simple_factor_return"]
    response_unit: Literal["local_value_simple_return"]
    response_basis: Literal["local_economic_value", "fx_inclusive", "unknown"]
    response_currency: CurrencyCode | None
    effective_at: datetime
    first_known_at: datetime
    valid_from: datetime
    valid_until: datetime | None
    revision: int
    provider_id: UUID
    license_version_id: UUID
    state: ObservationState
    quality: QualityState
    confidence: Decimal | None
    reason: ScenarioReason | None
    evidence_reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        _period(self)
        unique(self.evidence_reference_ids, "evidence_reference_ids")
        object.__setattr__(
            self, "evidence_reference_ids", tuple(sorted(self.evidence_reference_ids))
        )
        if self.coefficient is not None and not Decimal(-100) <= self.coefficient <= Decimal(100):
            fail_validation("Sensitivity coefficient exceeds its range.", field="coefficient")
        available = self.state is ObservationState.AVAILABLE
        if (
            available != (self.coefficient is not None and self.reason is None)
            or (
                available
                and (
                    self.response_basis != "local_economic_value" or self.response_currency is None
                )
            )
            or (not available and (self.coefficient is not None or self.reason is None))
        ):
            fail_validation("Sensitivity availability is inconsistent.", field="coefficient")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityMembership(ScenarioRecord):
    version_id: UUID
    version_digest: str
    observation_id: UUID
    observation_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityEvidence(ScenarioRecord):
    id: UUID
    owner_id: UUID
    provider_id: UUID
    license_version_id: UUID
    source_record_id: UUID
    content_digest: str
    effective_at: datetime
    first_known_at: datetime
    adapter_id: str
    adapter_version: str
    transformation: Literal["identity_local_simple_return_v1", "unsupported"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSourceLicense(ScenarioRecord):
    license_version_id: UUID
    license: SourceLicense


def sensitivity_row_count(value: ScenarioSensitivityCapture, *, applied_uses: int = 0) -> int:
    """One aggregate budget, checked before indexing or expanding any collection."""
    if type(applied_uses) is not int or applied_uses < 0:
        fail_validation("Applied sensitivity count is invalid.", field="applied_uses")
    collections = (value.observations, value.memberships, value.evidence)
    scenario_bound(all(type(items) is tuple for items in collections), "sensitivity_rows")
    total = sum(map(len, collections)) + applied_uses
    scenario_bound(total <= MAX_SCENARIO_SENSITIVITY_ROWS, "sensitivity_rows")
    return total


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityCapture(ScenarioRecord):
    versions: tuple[ScenarioSensitivitySourceVersion, ...] = ()
    observations: tuple[ScenarioSensitivityObservation, ...] = ()
    memberships: tuple[ScenarioSensitivityMembership, ...] = ()
    evidence: tuple[ScenarioSensitivityEvidence, ...] = ()
    licenses: tuple[ScenarioSourceLicense, ...] = ()

    def __post_init__(self) -> None:
        sensitivity_row_count(self)
        scenario_bound(
            type(self.versions) is tuple and len(self.versions) <= MAX_SCENARIO_RULES, "versions"
        )
        scenario_bound(
            type(self.licenses) is tuple and len(self.licenses) <= MAX_SCENARIO_LICENSES, "licenses"
        )
        ScenarioRecord.__post_init__(self)
        for name, field in (
            ("versions", "version_id"),
            ("observations", "observation_id"),
            ("evidence", "id"),
            ("licenses", "license_version_id"),
        ):
            items = getattr(self, name)
            unique(tuple(getattr(item, field) for item in items), name)
            object.__setattr__(
                self, name, tuple(sorted(items, key=lambda item: str(getattr(item, field))))
            )
        unique(
            tuple((item.version_id, item.observation_id) for item in self.memberships),
            "memberships",
        )
        object.__setattr__(
            self,
            "memberships",
            tuple(
                sorted(
                    self.memberships,
                    key=lambda item: (str(item.version_id), str(item.observation_id)),
                )
            ),
        )
        versions = {item.version_id: item for item in self.versions}
        observations = {item.observation_id: item for item in self.observations}
        evidence = {item.id: item for item in self.evidence}
        licenses = {item.license_version_id: item.license for item in self.licenses}
        if len(self.memberships) != len(observations):
            fail_validation("Sensitivity membership inventory differs.", field="memberships")
        seen: set[UUID] = set()
        for member in self.memberships:
            version, observation = (
                versions.get(member.version_id),
                observations.get(member.observation_id),
            )
            if (
                version is None
                or observation is None
                or observation.observation_id in seen
                or (
                    observation.version_id != version.version_id
                    or member.version_digest != version.content_digest
                    or member.observation_digest != observation.content_digest
                    or observation.owner_id != version.owner_id
                    or observation.provider_id != version.provider_id
                    or observation.license_version_id != version.license_version_id
                    or observation.driver_id != version.driver.driver_id
                    or observation.driver_definition_version_id
                    != version.driver.definition_version_id
                    or observation.shock_unit != version.driver.shock_unit
                )
            ):
                fail_validation("Sensitivity membership identity differs.", field="memberships")
            seen.add(observation.observation_id)
        from .scenario_serialization import (
            scenario_sensitivity_evidence_digest,
            scenario_sensitivity_observation_digest,
            scenario_sensitivity_version_digest,
        )

        for version_record in self.versions:
            if version_record.content_digest != scenario_sensitivity_version_digest(version_record):
                fail_validation("Sensitivity version content digest differs.")
        for observation_record in self.observations:
            if observation_record.content_digest != scenario_sensitivity_observation_digest(
                observation_record
            ):
                fail_validation("Sensitivity observation content digest differs.")
        for evidence_record in self.evidence:
            if evidence_record.content_digest != scenario_sensitivity_evidence_digest(
                evidence_record
            ):
                fail_validation("Sensitivity evidence content digest differs.")
        licensed_records: tuple[
            ScenarioSensitivitySourceVersion
            | ScenarioSensitivityObservation
            | ScenarioSensitivityEvidence,
            ...,
        ] = (*self.versions, *self.observations, *self.evidence)
        for item in licensed_records:
            license = licenses.get(item.license_version_id)
            if license is None or license.provider_id != str(item.provider_id):
                fail_validation("Sensitivity license membership is absent.", field="licenses")
        for item in self.observations:
            if item.state is ObservationState.AVAILABLE and not item.evidence_reference_ids:
                fail_validation("Available sensitivity requires original transformation evidence.")
            for identifier in item.evidence_reference_ids:
                proof = evidence.get(identifier)
                if proof is None or (
                    proof.owner_id,
                    proof.provider_id,
                    proof.license_version_id,
                ) != (item.owner_id, item.provider_id, item.license_version_id):
                    fail_validation("Sensitivity evidence membership is absent.", field="evidence")
                if (
                    item.state is ObservationState.AVAILABLE
                    and proof.transformation != "identity_local_simple_return_v1"
                ):
                    fail_validation("Available sensitivity has no supported transformation proof.")
        for item in self.versions:
            if item.driver.equivalence.kind != "unknown" and not item.driver.evidence_reference_ids:
                fail_validation("Known driver equivalence requires captured evidence.")
            for identifier in item.driver.evidence_reference_ids:
                proof = evidence.get(identifier)
                if proof is None or proof.owner_id != item.owner_id:
                    fail_validation("Driver equivalence evidence is absent.", field="evidence")
