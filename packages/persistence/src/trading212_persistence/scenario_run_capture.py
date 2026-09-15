"""Atomic normalized scenario capture publication and current-authorized retained replay."""

from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID, uuid5

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session
from trading212_domain.scenario_execution import ScenarioExecutionInput, ScenarioReplaySelection
from trading212_domain.scenario_serialization import encode_scenario_execution
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Scope

from .historical_models import HistoricalInputModel
from .premium_models import (
    PremiumOwned,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization
from .scenario_input_codec import pack_scenario_input, unpack_scenario_input
from .scenario_models import (
    ScenarioRunModel,
    ScenarioRunPayloadModel,
    ScenarioRunSensitivityEvidenceModel,
    ScenarioRunSensitivityMembershipModel,
    ScenarioRunSensitivityObservationModel,
    ScenarioRunSensitivityVersionModel,
)
from .scenario_original_source_authorization import reauthorize_original_sensitivity_sources
from .scenario_retention_boundary import require_scenario_retention
from .scenario_store_types import (
    CapturedScenarioInputs,
    ScenarioCaptureSelection,
    ScenarioStorageError,
)
from .scenario_store_types import ScenarioStorageErrorCode as Code

if TYPE_CHECKING:
    from .scenario_input_store import ScenarioInputStore

_REFERENCE_MODELS = (
    ScenarioRunSensitivityVersionModel,
    ScenarioRunSensitivityObservationModel,
    ScenarioRunSensitivityMembershipModel,
    ScenarioRunSensitivityEvidenceModel,
)


def _header(value: ScenarioExecutionInput) -> dict[str, object]:
    pins = value.pins
    replay = value.replay
    selection = None if replay is None else replay.selection
    return dict(
        definition_version_id=pins.scenario_version_id,
        definition_digest=pins.scenario_version_digest,
        portfolio_snapshot_id=pins.portfolio_snapshot_id,
        portfolio_snapshot_digest=pins.portfolio_snapshot_digest,
        xray_run_id=pins.xray_run_id,
        xray_input_id=pins.xray_input_id,
        xray_input_digest=pins.xray_input_digest,
        xray_result_digest=pins.xray_result_digest,
        reporting_currency=pins.reporting_currency.value,
        source_cutoff_at=pins.source_cutoff_at,
        historical_input_id=None if selection is None else selection.historical_input_snapshot_id,
        historical_input_digest=None if replay is None else replay.historical_input_digest,
        replay_start_date=None if selection is None else selection.start_date,
        replay_end_date=None if selection is None else selection.end_date,
        market_knowledge_cutoff_at=None
        if selection is None
        else selection.market_knowledge_cutoff_at,
        holdings_basis=None if selection is None else selection.holdings_basis,
        knowledge_basis=None if selection is None else selection.knowledge_basis,
        sensitivity_version_count=len(value.sensitivities.versions),
        sensitivity_observation_count=len(value.sensitivities.observations),
        sensitivity_membership_count=len(value.sensitivities.memberships),
        sensitivity_evidence_count=len(value.sensitivities.evidence),
    )


def _references(
    run_id: UUID, value: ScenarioExecutionInput
) -> dict[type[PremiumOwned], list[dict[str, object]]]:
    sources = value.sensitivities
    return {
        ScenarioRunSensitivityVersionModel: [
            dict(
                id=uuid5(run_id, "version:" + str(v.version_id)),
                version_id=v.version_id,
                content_digest=v.content_digest,
            )
            for v in sources.versions
        ],
        ScenarioRunSensitivityObservationModel: [
            dict(
                id=uuid5(run_id, "observation:" + str(v.observation_id)),
                version_id=v.version_id,
                observation_id=v.observation_id,
                content_digest=v.content_digest,
            )
            for v in sources.observations
        ],
        ScenarioRunSensitivityMembershipModel: [
            dict(
                id=uuid5(run_id, "membership:" + str(v.version_id) + ":" + str(v.observation_id)),
                version_id=v.version_id,
                observation_id=v.observation_id,
                membership_id=uuid5(v.version_id, "membership:" + str(v.observation_id)),
            )
            for v in sources.memberships
        ],
        ScenarioRunSensitivityEvidenceModel: [
            dict(
                id=uuid5(run_id, "evidence:" + str(v.id)),
                evidence_id=v.id,
                content_digest=v.content_digest,
            )
            for v in sources.evidence
        ],
    }


def _selection(value: ScenarioExecutionInput) -> ScenarioCaptureSelection:
    return ScenarioCaptureSelection(
        scenario_version_id=value.pins.scenario_version_id,
        portfolio_snapshot_id=value.pins.portfolio_snapshot_id,
        xray_run_id=value.pins.xray_run_id,
        reporting_currency=value.pins.reporting_currency,
        source_cutoff_at=value.pins.source_cutoff_at,
        replay=None if value.replay is None else value.replay.selection,
    )


def _conditional_auth(
    store: "ScenarioInputStore",
    session: Session,
    auth: ReportAuthorization,
    history_id: UUID | None,
) -> ReportAuthorization:
    if history_id is None:
        return auth
    scopes = {Scope.ACTIVITY_READ}
    header = session.execute(
        select(HistoricalInputModel.id, HistoricalInputModel.target_version_id).where(
            HistoricalInputModel.id == history_id,
            HistoricalInputModel.owner_id == auth.owner_id,
            HistoricalInputModel.broker_account_id == auth.account_id,
        )
    ).one_or_none()
    if header is None:
        raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
    if header.target_version_id is not None:
        scopes.add(Scope.TARGETS_READ)
    auth = replace(auth, required_scopes=auth.required_scopes | scopes)
    auth.check(session, now=store._now())
    return auth


def persist_capture(
    store: "ScenarioInputStore",
    session: Session,
    auth: ReportAuthorization,
    root: PremiumRunModel,
    captured: CapturedScenarioInputs,
) -> ScenarioRunModel:
    """Caller owns root, reservation, one job/outbox and commit; no partial publication."""
    auth = store.authority(session, auth, write=True)
    value = captured.value
    selection = _selection(value)
    auth = _conditional_auth(
        store,
        session,
        auth,
        None if selection.replay is None else selection.replay.historical_input_snapshot_id,
    )
    if (
        root.kind != "scenario"
        or root.owner_id != auth.owner_id
        or root.account_id != auth.account_id
        or value.pins.owner_id != auth.owner_id
        or value.pins.account_id != auth.account_id
        or root.input_digest != value.input_digest
        or root.expires_at != value.expires_at
        or root.expires_at <= store._now()
    ):
        raise ScenarioStorageError(Code.CONFLICT)
    # A typed in-process record is not authority to publish caller-invented proof. Reload
    # the saved inventory under the same owner locks and compare its financial digest.
    current = store.capture(session, auth, selection, retained_at=root.created_at)
    if (
        current.value.input_digest != value.input_digest
        or current.license_version_ids != captured.license_version_ids
        or value.expires_at > current.value.expires_at
    ):
        raise ScenarioStorageError(Code.CONFLICT)
    payload = pack_scenario_input(value)
    run = ScenarioRunModel(
        id=root.id,
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        sealed=False,
        created_at=root.created_at,
        **_header(value),
    )
    session.add(run)
    session.flush()
    references = _references(run.id, value)
    for model in _REFERENCE_MODELS:
        rows = references[model]
        for begin in range(0, len(rows), 500):
            auth.check(session, now=store._now())
            session.execute(
                insert(model),
                [
                    dict(
                        row,
                        owner_id=auth.owner_id,
                        account_id=auth.account_id,
                        run_id=run.id,
                        created_at=root.created_at,
                    )
                    for row in rows[begin : begin + 500]
                ],
            )
    sources = store.copy_authority(retained_at=root.created_at)
    for identifier in captured.license_version_ids:
        license = sources._permit(session, auth.owner_id, identifier, SourceUse.DISPLAY)
        session.add(
            PremiumRunLicenseModel(
                id=uuid5(run.id, "license:" + str(identifier)),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                run_id=run.id,
                provider_id=UUID(license.provider_id),
                license_version_id=identifier,
                created_at=root.created_at,
            )
        )
    session.flush()
    for identifier in captured.license_version_ids:
        sources._permit(session, auth.owner_id, identifier, SourceUse.DISPLAY)
    require_scenario_retention(
        expires_at=root.expires_at,
        copy_deadline=min(sources.copy_deadline, current.value.expires_at),
        now=store._now(),
    )
    session.add(
        ScenarioRunPayloadModel(
            id=uuid5(run.id, "scenario_run_payloads"),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            run_id=run.id,
            canonical_input=payload,
            created_at=root.created_at,
        )
    )
    session.flush()
    run.sealed = True
    session.flush()
    size = session.scalar(text("SELECT scenario_storage_bytes(:run)"), {"run": run.id})
    if size is None or size > 33554432:
        raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
    for identifier in captured.license_version_ids:
        sources._permit(session, auth.owner_id, identifier, SourceUse.DISPLAY)
    auth.check(session, now=store._now())
    require_scenario_retention(
        expires_at=root.expires_at,
        copy_deadline=min(sources.copy_deadline, current.value.expires_at),
        now=store._now(),
    )
    return run


def read_retained_input(
    store: "ScenarioInputStore",
    session: Session,
    auth: ReportAuthorization,
    identifier: UUID,
    *,
    required_copy_use: SourceUse | None = None,
) -> ScenarioExecutionInput:
    auth = store.authority(session, auth)
    root = store._owned(session, auth, PremiumRunModel, identifier)
    if root.kind != "scenario":
        raise ScenarioStorageError(Code.NOT_FOUND)
    run = store._owned(session, auth, ScenarioRunModel, identifier)
    auth = _conditional_auth(store, session, auth, run.historical_input_id)
    if (
        not run.sealed
        or root.expires_at <= store._now()
        or session.scalar(
            select(PremiumRetentionModel.id).where(PremiumRetentionModel.run_id == root.id)
        )
    ):
        raise ScenarioStorageError(Code.RUN_EXPIRED)
    # Authorize every permanent captured license, including any normalized mismatch,
    # before reconstructing or decoding the retained financial envelope.
    licenses = tuple(
        session.scalars(
            select(PremiumRunLicenseModel.license_version_id)
            .where(
                PremiumRunLicenseModel.run_id == root.id,
                PremiumRunLicenseModel.owner_id == auth.owner_id,
                PremiumRunLicenseModel.account_id == auth.account_id,
            )
            .order_by(PremiumRunLicenseModel.license_version_id)
            .limit(8193)
        )
    )
    if len(licenses) > 8192:
        raise ScenarioStorageError(Code.INPUT_BOUND_EXCEEDED)
    sources = store.copy_authority(retained_at=root.created_at, required_copy_use=required_copy_use)
    for license_id in licenses:
        sources._permit(session, auth.owner_id, license_id, SourceUse.DISPLAY)
    replay = None
    if run.historical_input_id is not None:
        replay = ScenarioReplaySelection(
            historical_input_snapshot_id=run.historical_input_id,
            start_date=cast(date, run.replay_start_date),
            end_date=cast(date, run.replay_end_date),
            market_knowledge_cutoff_at=cast(datetime, run.market_knowledge_cutoff_at),
            holdings_basis=cast(
                Literal["current_holdings", "historical_holdings"], run.holdings_basis
            ),
            knowledge_basis=cast(Literal["point_in_time", "retrospective"], run.knowledge_basis),
        )
    selection = ScenarioCaptureSelection(
        scenario_version_id=run.definition_version_id,
        portfolio_snapshot_id=run.portfolio_snapshot_id,
        xray_run_id=run.xray_run_id,
        reporting_currency=CurrencyCode(run.reporting_currency),
        source_cutoff_at=run.source_cutoff_at,
        replay=replay,
    )
    current = store.capture(
        session, auth, selection, retained_at=root.created_at, required_copy_use=required_copy_use
    )
    if current.value.input_digest != root.input_digest or current.license_version_ids != licenses:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    if any(getattr(run, key) != expected for key, expected in _header(current.value).items()):
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    expected_refs = _references(run.id, current.value)
    for model in _REFERENCE_MODELS:
        expected = expected_refs[model]
        actual = tuple(
            session.scalars(
                select(model)
                .where(
                    model.run_id == run.id,
                    model.owner_id == auth.owner_id,
                    model.account_id == auth.account_id,
                )
                .limit(len(expected) + 1)
            )
        )
        by_id = {row.id: row for row in actual}
        if len(actual) != len(expected):
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        for fields in expected:
            row = by_id.get(cast(UUID, fields["id"]))
            if row is None or any(getattr(row, key) != value for key, value in fields.items()):
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    count, size = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(func.octet_length(ScenarioRunPayloadModel.canonical_input)), 0),
        ).where(
            ScenarioRunPayloadModel.run_id == run.id,
            ScenarioRunPayloadModel.owner_id == auth.owner_id,
            ScenarioRunPayloadModel.account_id == auth.account_id,
        )
    ).one()
    if count != 1 or not 0 < size <= 33554432:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    auth.check(session, now=store._now())
    require_scenario_retention(
        expires_at=root.expires_at,
        copy_deadline=min(sources.copy_deadline, current.value.expires_at),
        now=store._now(),
    )
    payload = session.scalar(
        select(ScenarioRunPayloadModel.canonical_input).where(
            ScenarioRunPayloadModel.run_id == run.id,
            ScenarioRunPayloadModel.owner_id == auth.owner_id,
            ScenarioRunPayloadModel.account_id == auth.account_id,
        )
    )
    if payload is None:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    value = unpack_scenario_input(payload, expected_digest=root.input_digest)
    if (
        value.expires_at != root.expires_at
        or value.expires_at > current.value.expires_at
        or encode_scenario_execution(replace(value, expires_at=current.value.expires_at))
        != encode_scenario_execution(current.value)
    ):
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
    for license_id in licenses:
        sources._permit(session, auth.owner_id, license_id, SourceUse.DISPLAY)
    auth.check(session, now=store._now())
    require_scenario_retention(
        expires_at=root.expires_at,
        copy_deadline=min(sources.copy_deadline, current.value.expires_at),
        now=store._now(),
    )
    reauthorize_original_sensitivity_sources(session, auth, root.id, sources)
    require_scenario_retention(
        expires_at=root.expires_at,
        copy_deadline=min(sources.copy_deadline, current.value.expires_at),
        now=store._now(),
    )
    return value
