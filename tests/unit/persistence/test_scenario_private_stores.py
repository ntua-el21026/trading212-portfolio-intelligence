"""Private authority ordering and normalized source proof regressions."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_domain.scenario import ScenarioSensitivityVersionPin
from trading212_domain.scenario_execution import ScenarioReplaySelection
from trading212_domain.scenario_sources import ScenarioRateEquivalence
from trading212_domain.sources import SourceUse
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_models import ApplicationCommandIdentityModel
from trading212_persistence.scenario_definition_store import ScenarioDefinitionStore
from trading212_persistence.scenario_input_store import ScenarioCopyXray, ScenarioInputStore
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
)
from trading212_persistence.scenario_source_projection import normalized_sensitivity_rows
from trading212_persistence.scenario_source_store import ScenarioCopySources, ScenarioSourceStore
from trading212_persistence.scenario_store_types import (
    ScenarioCaptureSelection,
    ScenarioStorageError,
    ScenarioStorageErrorCode,
    StoredScenarioDefinition,
)
from trading212_security.principals import AuthorizationError, Scope

from tests.unit.analytics.xray_factories import CUTOFF, uid
from tests.unit.domain.scenario_factories import definition, sensitivity_capture


def authority() -> ReportAuthorization:
    return ReportAuthorization(
        principal_id=uid(7701),
        owner_id=uid(1),
        account_id=uid(2),
        required_scopes=frozenset((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ)),
        expires_at=CUTOFF.value + timedelta(days=1),
        issuer="synthetic",
        subject="synthetic",
    )


def test_adapter_publication_checks_write_grant_before_encoding_private_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScenarioSourceStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )

    def denied(self: ReportAuthorization, session: Session, *, now: object) -> None:
        assert Scope.SCENARIOS_WRITE in self.required_scopes
        raise AuthorizationError("access denied")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Private canonical source data encoded before grant authorization")

    monkeypatch.setattr(ReportAuthorization, "check", denied)
    monkeypatch.setattr(
        "trading212_persistence.scenario_source_store.scenario_record_bytes", forbidden
    )
    session = Mock(spec=Session)
    with pytest.raises(AuthorizationError):
        store.publish_capture(
            session, authority(), sensitivity_capture(), expires_at=CUTOFF.value + timedelta(days=1)
        )
    session.execute.assert_not_called()


def test_read_checks_current_license_before_any_source_payload_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = sensitivity_capture()
    source = capture.versions[0]
    row = ScenarioSensitivityVersionModel(
        id=source.version_id,
        owner_id=source.owner_id,
        content_digest=source.content_digest,
        driver_id=source.driver.driver_id,
        driver_definition_version_id=source.driver.definition_version_id,
        license_version_id=source.license_version_id,
        observation_count=1,
        membership_count=1,
        sealed=True,
        expires_at=CUTOFF.value + timedelta(days=1),
    )
    session = Mock(spec=Session)
    session.scalars.return_value = (row,)
    session.scalar.return_value = None
    monkeypatch.setattr(ReportAuthorization, "check", lambda *args, **kwargs: None)

    def denied(
        self: ScenarioCopySources, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> None:
        assert license_id == source.license_version_id
        raise ScenarioStorageError(ScenarioStorageErrorCode.ACCESS_DENIED)

    monkeypatch.setattr(ScenarioCopySources, "_permit", denied)
    store = ScenarioSourceStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    with pytest.raises(ScenarioStorageError) as error:
        store.read_capture(
            session,
            authority(),
            (
                ScenarioSensitivityVersionPin(
                    version_id=source.version_id,
                    content_digest=source.content_digest,
                    driver_id=source.driver.driver_id,
                    driver_definition_version_id=source.driver.definition_version_id,
                ),
            ),
        )
    assert error.value.code is ScenarioStorageErrorCode.ACCESS_DENIED
    assert session.scalars.call_count == 1
    assert "canonical_payload" not in str(session.scalars.call_args.args[0])
    assert session.execute.call_count == 1  # Owner lock only; no private payload projection.


def test_normalized_source_retains_driver_and_observation_evidence_and_exact_coefficient() -> None:
    capture = sensitivity_capture()
    rows = normalized_sensitivity_rows(capture, expires_at=CUTOFF.value + timedelta(days=1))
    driver = rows[ScenarioSensitivityVersionPayloadModel][0]
    observation = rows[ScenarioSensitivityObservationPayloadModel][0]
    assert driver["equivalence_kind"] == "rate"
    equivalence = capture.versions[0].driver.equivalence
    assert isinstance(equivalence, ScenarioRateEquivalence)
    assert driver["equivalence_rate_id"] == equivalence.rate_id
    assert observation["coefficient"] == capture.observations[0].coefficient
    assert observation["response_currency"] == "EUR"
    links = rows[ScenarioSensitivityEvidenceLinkModel]
    assert len(links) == 2
    assert {item["observation_id"] for item in links} == {
        None,
        capture.observations[0].observation_id,
    }
    assert {item["evidence_id"] for item in links} == {capture.evidence[0].id}


def test_definition_idempotent_retry_preserves_owned_reference_after_source_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScenarioDefinitionStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    auth = authority()
    saved = StoredScenarioDefinition(
        id=uid(7702),
        account_id=auth.account_id,
        name="Original",
        revision=1,
        archived=False,
        current_version_id=uid(7703),
        created_at=CUTOFF.value,
        updated_at=CUTOFF.value,
    )
    monkeypatch.setattr(store, "authority", lambda *args, **kwargs: auth)
    monkeypatch.setattr(
        store,
        "prior_command",
        lambda *args, **kwargs: ApplicationCommandIdentityModel(premium_resource_id=saved.id),
    )
    monkeypatch.setattr(store, "read_definition", lambda *args, **kwargs: saved)
    expired = Mock(side_effect=ScenarioStorageError(ScenarioStorageErrorCode.RUN_EXPIRED))
    monkeypatch.setattr(store, "_validate_references", expired)
    assert (
        store.publish_definition(
            Mock(spec=Session),
            auth,
            definition(),
            idempotency_key="retry",
            correlation_id="synthetic",
        )
        == saved
    )
    expired.assert_not_called()


@pytest.mark.parametrize("has_target", (False, True))
def test_replay_conditional_scopes_precede_any_financial_parent_decode(
    monkeypatch: pytest.MonkeyPatch, has_target: bool
) -> None:
    from tests.unit.analytics.xray_factories import EUR

    auth = authority()
    store = ScenarioInputStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    session = Mock(spec=Session)
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        id=uid(7705), sealed=True, target_version_id=uid(7706) if has_target else None
    )
    monkeypatch.setattr(store, "authority", lambda *args, **kwargs: auth)
    monkeypatch.setattr(store, "read_version", lambda *args, **kwargs: Mock())

    def denied(self: ReportAuthorization, session: Session, *, now: object) -> None:
        assert Scope.ACTIVITY_READ in self.required_scopes
        assert (Scope.TARGETS_READ in self.required_scopes) is has_target
        raise AuthorizationError("access denied")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Private saved input reached before conditional grants")

    monkeypatch.setattr(ReportAuthorization, "check", denied)
    monkeypatch.setattr(store, "_history", forbidden)
    monkeypatch.setattr(ScenarioCopyXray, "_authorize_xray_run", forbidden)
    selection = ScenarioCaptureSelection(
        scenario_version_id=uid(7702),
        portfolio_snapshot_id=uid(7703),
        xray_run_id=uid(7704),
        reporting_currency=EUR,
        source_cutoff_at=CUTOFF.value,
        replay=ScenarioReplaySelection(
            historical_input_snapshot_id=uid(7705),
            start_date=CUTOFF.value.date() - timedelta(days=1),
            end_date=CUTOFF.value.date(),
            market_knowledge_cutoff_at=CUTOFF.value,
            holdings_basis="historical_holdings",
            knowledge_basis="point_in_time",
        ),
    )
    with pytest.raises(AuthorizationError):
        store.capture(session, auth, selection)


@pytest.mark.parametrize("kind", ["version", "observation", "evidence"])
@pytest.mark.parametrize("shortened", [True, False])
def test_source_original_retention_cannot_restart_at_new_copy_time(
    monkeypatch: pytest.MonkeyPatch, kind: str, shortened: bool
) -> None:
    pinned = replace(sensitivity_capture().licenses[0].license, retention_days=7)
    current = replace(pinned, retention_days=1 if shortened else 30)
    sources = ScenarioCopySources(
        sessions=sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    sources.begin_copy(retained_at=CUTOFF.value, required_copy_use=None)
    monkeypatch.setattr(sources, "_permit", lambda *args, **kwargs: pinned)
    monkeypatch.setattr(sources, "_current_license", lambda *args, **kwargs: current)
    common = dict(
        id=uid(9921),
        owner_id=uid(1),
        license_version_id=uid(9922),
        created_at=CUTOFF.value - timedelta(days=2),
    )
    row: (
        ScenarioSensitivityVersionModel
        | ScenarioSensitivityObservationModel
        | ScenarioSensitivityEvidenceModel
    )
    if kind == "version":
        row = ScenarioSensitivityVersionModel(
            **common, expires_at=CUTOFF.value + timedelta(days=20)
        )
    elif kind == "observation":
        row = ScenarioSensitivityObservationModel(**common)
    else:
        row = ScenarioSensitivityEvidenceModel(**common)
    if shortened:
        with pytest.raises(ScenarioStorageError) as failure:
            sources.original_permit(Mock(spec=Session), row)
        assert failure.value.code is ScenarioStorageErrorCode.RUN_EXPIRED
    else:
        assert sources.original_permit(Mock(spec=Session), row) == pinned
        assert sources.copy_deadline == CUTOFF.value + timedelta(days=5)
