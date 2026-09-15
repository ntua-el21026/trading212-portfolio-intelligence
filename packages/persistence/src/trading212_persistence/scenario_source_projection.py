"""Fixed canonical sensitivity projection; shared by publication and strict replay checks."""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid5

from trading212_domain.scenario import (
    ScenarioEntitySelector,
    ScenarioInstrumentSelector,
    ScenarioRegionSelector,
    ScenarioSectorSelector,
)
from trading212_domain.scenario_serialization import scenario_record_bytes
from trading212_domain.scenario_sources import (
    ScenarioEntitySubject,
    ScenarioFactorEquivalence,
    ScenarioFxEquivalence,
    ScenarioInstrumentSubject,
    ScenarioPriceEquivalence,
    ScenarioRateEquivalence,
    ScenarioSensitivityCapture,
    ScenarioUnknownEquivalence,
)
from trading212_domain.values import CurrencyCode

from .scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityMembershipModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivitySetModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
)
from .source_models import SourceOwned

SOURCE_PUBLICATION_MODELS = (
    ScenarioSensitivitySetModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityVersionPayloadModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivityMembershipModel,
    ScenarioSensitivityEvidenceLinkModel,
)


def _scalar(value: object) -> object:
    return value.value if isinstance(value, (Enum, CurrencyCode)) else value


def normalized_sensitivity_rows(
    capture: ScenarioSensitivityCapture,
    *,
    expires_at: datetime,
) -> dict[type[SourceOwned], list[dict[str, object]]]:
    rows: dict[type[SourceOwned], list[dict[str, object]]] = {
        model: [] for model in SOURCE_PUBLICATION_MODELS
    }
    owners = {version.version_id: version.owner_id for version in capture.versions}
    sets: dict[UUID, tuple[UUID, UUID]] = {}
    for version in capture.versions:
        sets[version.source_set_id] = (version.owner_id, version.provider_id)
        observations = [
            value for value in capture.observations if value.version_id == version.version_id
        ]
        version_memberships = [
            value for value in capture.memberships if value.version_id == version.version_id
        ]
        version_evidence = set(version.driver.evidence_reference_ids)
        for observation in observations:
            version_evidence.update(observation.evidence_reference_ids)
        rows[ScenarioSensitivityVersionModel].append(
            dict(
                id=version.version_id,
                owner_id=version.owner_id,
                source_set_id=version.source_set_id,
                provider_id=version.provider_id,
                license_version_id=version.license_version_id,
                content_digest=version.content_digest,
                driver_id=version.driver.driver_id,
                driver_definition_version_id=version.driver.definition_version_id,
                driver_definition_digest=version.driver.definition_digest,
                revision=version.revision,
                observation_count=len(observations),
                membership_count=len(version_memberships),
                evidence_count=len(version_evidence),
                expires_at=expires_at,
                sealed=False,
            )
        )
        equivalence = version.driver.equivalence
        values: dict[str, object] = {
            name: None
            for name in (
                "equivalence_rate_id",
                "equivalence_factor_id",
                "equivalence_currency",
                "equivalence_selector_kind",
                "equivalence_instrument_id",
                "equivalence_entity_id",
                "equivalence_taxonomy_id",
                "equivalence_taxonomy_version",
                "equivalence_bucket_key",
                "equivalence_reason",
            )
        }
        if isinstance(equivalence, ScenarioRateEquivalence):
            values.update(
                equivalence_rate_id=equivalence.rate_id,
                equivalence_currency=equivalence.currency.value,
            )
        elif isinstance(equivalence, ScenarioFactorEquivalence):
            values["equivalence_factor_id"] = equivalence.factor_id
        elif isinstance(equivalence, ScenarioFxEquivalence):
            values["equivalence_currency"] = equivalence.currency.value
        elif isinstance(equivalence, ScenarioUnknownEquivalence):
            values["equivalence_reason"] = equivalence.reason.value
        elif isinstance(equivalence, ScenarioPriceEquivalence):
            selector = equivalence.selector
            values["equivalence_selector_kind"] = selector.kind
            if isinstance(selector, ScenarioInstrumentSelector):
                values["equivalence_instrument_id"] = selector.instrument_id
            elif isinstance(selector, ScenarioEntitySelector):
                values["equivalence_entity_id"] = selector.entity_id
            elif isinstance(selector, (ScenarioSectorSelector, ScenarioRegionSelector)):
                values.update(
                    equivalence_taxonomy_id=selector.taxonomy_id,
                    equivalence_taxonomy_version=selector.taxonomy_version,
                    equivalence_bucket_key=selector.bucket_key,
                )
        rows[ScenarioSensitivityVersionPayloadModel].append(
            dict(
                id=uuid5(version.version_id, "scenario_sensitivity_version_payloads"),
                owner_id=version.owner_id,
                version_id=version.version_id,
                driver_kind=version.driver.kind,
                shock_unit=version.driver.shock_unit,
                equivalence_kind=equivalence.kind,
                effective_at=version.effective_at,
                first_known_at=version.first_known_at,
                valid_from=version.valid_from,
                valid_until=version.valid_until,
                revision=version.revision,
                adapter_id=version.adapter_id,
                adapter_version=version.adapter_version,
                availability=version.availability.value,
                quality=version.quality.value,
                canonical_payload=scenario_record_bytes(version),
                **values,
            )
        )
        for identifier in version.driver.evidence_reference_ids:
            rows[ScenarioSensitivityEvidenceLinkModel].append(
                dict(
                    id=uuid5(version.version_id, "driver-evidence:" + str(identifier)),
                    owner_id=version.owner_id,
                    version_id=version.version_id,
                    evidence_id=identifier,
                    observation_id=None,
                )
            )
    rows[ScenarioSensitivitySetModel] = [
        dict(id=key, owner_id=owner, provider_id=provider)
        for key, (owner, provider) in sorted(sets.items())
    ]
    for observation in capture.observations:
        rows[ScenarioSensitivityObservationModel].append(
            dict(
                id=observation.observation_id,
                owner_id=observation.owner_id,
                version_id=observation.version_id,
                provider_id=observation.provider_id,
                license_version_id=observation.license_version_id,
                content_digest=observation.content_digest,
                driver_id=observation.driver_id,
                driver_definition_version_id=observation.driver_definition_version_id,
            )
        )
        values = {
            name: _scalar(getattr(observation, name))
            for name in (
                "coefficient",
                "shock_unit",
                "response_unit",
                "response_basis",
                "response_currency",
                "effective_at",
                "first_known_at",
                "valid_from",
                "valid_until",
                "revision",
                "state",
                "quality",
                "confidence",
                "reason",
            )
        }
        subject = observation.subject
        rows[ScenarioSensitivityObservationPayloadModel].append(
            dict(
                id=uuid5(observation.observation_id, "scenario_sensitivity_observation_payloads"),
                owner_id=observation.owner_id,
                observation_id=observation.observation_id,
                subject_kind=subject.kind,
                instrument_id=subject.instrument_id
                if isinstance(subject, ScenarioInstrumentSubject)
                else None,
                entity_id=subject.entity_id if isinstance(subject, ScenarioEntitySubject) else None,
                canonical_payload=scenario_record_bytes(observation),
                **values,
            )
        )
        for identifier in observation.evidence_reference_ids:
            rows[ScenarioSensitivityEvidenceLinkModel].append(
                dict(
                    id=uuid5(
                        observation.version_id,
                        "observation-evidence:"
                        + str(observation.observation_id)
                        + ":"
                        + str(identifier),
                    ),
                    owner_id=observation.owner_id,
                    version_id=observation.version_id,
                    evidence_id=identifier,
                    observation_id=observation.observation_id,
                )
            )
    for membership in capture.memberships:
        rows[ScenarioSensitivityMembershipModel].append(
            dict(
                id=uuid5(membership.version_id, "membership:" + str(membership.observation_id)),
                owner_id=owners[membership.version_id],
                version_id=membership.version_id,
                version_digest=membership.version_digest,
                observation_id=membership.observation_id,
                observation_digest=membership.observation_digest,
            )
        )
    for evidence in capture.evidence:
        rows[ScenarioSensitivityEvidenceModel].append(
            {
                name: getattr(evidence, name)
                for name in (
                    "id",
                    "owner_id",
                    "provider_id",
                    "license_version_id",
                    "source_record_id",
                    "content_digest",
                )
            }
        )
        rows[ScenarioSensitivityEvidencePayloadModel].append(
            dict(
                id=uuid5(evidence.id, "scenario_sensitivity_evidence_payloads"),
                owner_id=evidence.owner_id,
                evidence_id=evidence.id,
                effective_at=evidence.effective_at,
                first_known_at=evidence.first_known_at,
                adapter_id=evidence.adapter_id,
                adapter_version=evidence.adapter_version,
                transformation=evidence.transformation,
                canonical_payload=scenario_record_bytes(evidence),
            )
        )
    return rows
