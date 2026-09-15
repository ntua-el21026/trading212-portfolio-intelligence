"""Final metadata-only authority for the original sensitivity records of a saved run."""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .report_authorization import ReportAuthorization
from .scenario_models import (
    ScenarioRunModel,
    ScenarioRunSensitivityEvidenceModel,
    ScenarioRunSensitivityObservationModel,
    ScenarioRunSensitivityVersionModel,
)
from .scenario_source_models import (
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityVersionModel,
)
from .scenario_source_store import ScenarioCopySources
from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code


def _refresh_headers[
    Header: ScenarioSensitivityVersionModel
    | ScenarioSensitivityObservationModel
    | ScenarioSensitivityEvidenceModel
](
    session: Session,
    auth: ReportAuthorization,
    sources: ScenarioCopySources,
    statement: Select[tuple[Header]],
    expected: int,
) -> None:
    count = 0
    for original in session.scalars(statement.limit(expected + 1)).yield_per(500):
        count += 1
        if count > expected:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        if count % 500 == 1:
            auth.check(session, now=sources._now())
        sources.original_permit(session, original)
    if count != expected:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)


def reauthorize_original_sensitivity_sources(
    session: Session,
    auth: ReportAuthorization,
    run_id: UUID,
    sources: ScenarioCopySources,
) -> None:
    """Refresh every original lifetime without reading or decoding licensed payloads.

    Callers retain the existing source/owner transaction locks and enforce their
    root expiry against the resulting copy_deadline immediately before returning.
    The original header date matters when a future-effective license tightens
    retention during decoding or projection of a much newer saved run.
    """
    auth.check(session, now=sources._now())
    run = session.scalar(
        select(ScenarioRunModel).where(
            ScenarioRunModel.id == run_id,
            ScenarioRunModel.owner_id == auth.owner_id,
            ScenarioRunModel.account_id == auth.account_id,
        )
    )
    if run is None or not run.sealed:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    counts = (
        run.sensitivity_version_count,
        run.sensitivity_observation_count,
        run.sensitivity_membership_count,
        run.sensitivity_evidence_count,
    )
    if (
        any(type(count) is not int or count < 0 for count in counts)
        or counts[0] > 128
        or sum(counts[1:]) > 100000
    ):
        raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
    version, version_ref = ScenarioSensitivityVersionModel, ScenarioRunSensitivityVersionModel
    _refresh_headers(
        session,
        auth,
        sources,
        select(version)
        .join(
            version_ref,
            (version_ref.version_id == version.id)
            & (version_ref.owner_id == version.owner_id)
            & (version_ref.content_digest == version.content_digest),
        )
        .where(
            version_ref.run_id == run_id,
            version_ref.owner_id == auth.owner_id,
            version_ref.account_id == auth.account_id,
        )
        .order_by(version.id),
        counts[0],
    )
    observation, observation_ref = (
        ScenarioSensitivityObservationModel,
        ScenarioRunSensitivityObservationModel,
    )
    _refresh_headers(
        session,
        auth,
        sources,
        select(observation)
        .join(
            observation_ref,
            (observation_ref.observation_id == observation.id)
            & (observation_ref.owner_id == observation.owner_id)
            & (observation_ref.version_id == observation.version_id)
            & (observation_ref.content_digest == observation.content_digest),
        )
        .where(
            observation_ref.run_id == run_id,
            observation_ref.owner_id == auth.owner_id,
            observation_ref.account_id == auth.account_id,
        )
        .order_by(observation.id),
        counts[1],
    )
    evidence, evidence_ref = ScenarioSensitivityEvidenceModel, ScenarioRunSensitivityEvidenceModel
    _refresh_headers(
        session,
        auth,
        sources,
        select(evidence)
        .join(
            evidence_ref,
            (evidence_ref.evidence_id == evidence.id)
            & (evidence_ref.owner_id == evidence.owner_id)
            & (evidence_ref.content_digest == evidence.content_digest),
        )
        .where(
            evidence_ref.run_id == run_id,
            evidence_ref.owner_id == auth.owner_id,
            evidence_ref.account_id == auth.account_id,
        )
        .order_by(evidence.id),
        counts[3],
    )
    auth.check(session, now=sources._now())
