"""Original source lifetimes are refreshed after private input/result decoding."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid5

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    scenario_result_digest,
)
from trading212_domain.sources import SourceUse
from trading212_persistence import scenario_result_store as result_module
from trading212_persistence import scenario_run_capture as capture_module
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.scenario_input_codec import pack_scenario_input, unpack_scenario_input
from trading212_persistence.scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
    ScenarioRunModel,
)
from trading212_persistence.scenario_original_source_authorization import (
    reauthorize_original_sensitivity_sources,
)
from trading212_persistence.scenario_result_projection import normalized_scenario_result
from trading212_persistence.scenario_result_store import ScenarioResultStore
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityVersionModel,
)
from trading212_persistence.scenario_source_store import ScenarioCopySources
from trading212_persistence.scenario_store_types import (
    CapturedScenarioInputs,
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import AuthorizationError

from tests.unit.analytics.xray_factories import CUTOFF, uid
from tests.unit.persistence.test_scenario_private_stores import authority
from tests.unit.persistence.test_scenario_result_storage import sensitivity_input


def streamed(rows: tuple[object, ...]) -> Mock:
    values = Mock()
    values.yield_per.return_value = iter(rows)
    return values


@pytest.mark.parametrize("seam", ("input", "result"))
@pytest.mark.parametrize("kind", ("version", "observation", "evidence"))
@pytest.mark.parametrize("new_days", (15, 21, 30))
def test_final_boundary_rechecks_original_headers_when_current_license_tightens(
    monkeypatch: pytest.MonkeyPatch, seam: str, kind: str, new_days: int
) -> None:
    auth = authority()
    # The source is twenty days old; the new run is two seconds old at final recheck.
    # 15 days has already expired; 21 days is still live but cannot retain this root
    # for its remaining two days; 30 days is the unchanged positive control.
    original = replace(sensitivity_input(), expires_at=CUTOFF.value + timedelta(days=2))
    now = [CUTOFF.value]
    boundary = CUTOFF.value + timedelta(seconds=1)
    pinned = replace(original.sensitivities.licenses[0].license, retention_days=30)
    current = replace(pinned, retention_days=new_days)
    root = PremiumRunModel(
        id=uid(9960),
        kind="scenario",
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        input_digest=original.input_digest,
        expires_at=original.expires_at,
        created_at=CUTOFF.value,
    )
    run = ScenarioRunModel(
        id=root.id,
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        sealed=True,
        **capture_module._header(original),
    )
    store = ScenarioResultStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: now[0],
    )
    monkeypatch.setattr(ReportAuthorization, "check", lambda *args, **kwargs: None)
    requested_uses: list[SourceUse] = []

    def permit(
        self: PostgresSourceService,
        session: Session,
        owner: object,
        license_id: object,
        use: SourceUse,
    ) -> object:
        requested_uses.append(use)
        return pinned

    monkeypatch.setattr(PostgresSourceService, "_permit", permit)
    monkeypatch.setattr(
        PostgresSourceService,
        "_current_license",
        lambda *args, **kwargs: current if now[0] >= boundary else pinned,
    )
    sources = store.copy_authority(
        retained_at=root.created_at,
        required_copy_use=SourceUse.REPORT if seam == "input" else None,
    )
    monkeypatch.setattr(store, "copy_authority", lambda **kwargs: sources)
    headers: list[
        ScenarioSensitivityVersionModel
        | ScenarioSensitivityObservationModel
        | ScenarioSensitivityEvidenceModel
    ] = []
    for name, model, source_value in (
        ("version", ScenarioSensitivityVersionModel, original.sensitivities.versions[0]),
        (
            "observation",
            ScenarioSensitivityObservationModel,
            original.sensitivities.observations[0],
        ),
        ("evidence", ScenarioSensitivityEvidenceModel, original.sensitivities.evidence[0]),
    ):
        fields: dict[str, object] = dict(
            id=uid(9970 + len(headers)),
            owner_id=auth.owner_id,
            provider_id=uid(900),
            license_version_id=uid(999),
            content_digest=source_value.content_digest,
            created_at=CUTOFF.value - timedelta(days=20 if name == kind else 0),
        )
        if name == "version":
            fields["expires_at"] = CUTOFF.value + timedelta(days=10)
        headers.append(model(**fields))
    licenses = (uid(999),)
    session = Mock(spec=Session)
    if seam == "input":
        monkeypatch.setattr(store, "authority", lambda *args, **kwargs: auth)
        monkeypatch.setattr(
            store,
            "_owned",
            lambda session, auth, model, identifier: root if model is PremiumRunModel else run,
        )
        monkeypatch.setattr(
            store,
            "capture",
            lambda *args, **kwargs: CapturedScenarioInputs(
                value=original, license_version_ids=licenses
            ),
        )
        refs = capture_module._references(run.id, original)
        reference_rows = [tuple(model(**row) for row in refs[model]) for model in refs]
        payload = pack_scenario_input(original)
        session.scalar.side_effect = (None, payload, run)
        session.scalars.side_effect = (
            licenses,
            *reference_rows,
            *(streamed((header,)) for header in headers),
        )
        session.execute.return_value.one.return_value = (1, len(payload))

        def delayed_input(value: bytes, *, expected_digest: str) -> ScenarioExecutionInput:
            decoded = unpack_scenario_input(value, expected_digest=expected_digest)
            now[0] = boundary + timedelta(seconds=1)
            return decoded

        monkeypatch.setattr(capture_module, "unpack_scenario_input", delayed_input)

        def read() -> ScenarioExecutionInput | ScenarioCalculation:
            return store.read_retained_input(
                session, auth, root.id, required_copy_use=SourceUse.REPORT
            )
    else:
        from trading212_analytics.scenario import calculate_scenario

        value = calculate_scenario(original)
        identifier = uuid5(root.id, "scenario_results")
        projection = normalized_scenario_result(value, identifier)
        result_header = ScenarioResultModel(
            id=identifier,
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            run_id=root.id,
            content_digest=scenario_result_digest(value),
            component_count=len(projection.components),
            sensitivity_source_row_count=value.sensitivity_source_row_count,
            applied_use_count=len(projection.applied_uses),
            sealed=True,
        )
        monkeypatch.setattr(store, "_result_authority", lambda *args, **kwargs: (auth, root))
        monkeypatch.setattr(store, "_result_bytes", lambda *args, **kwargs: 1000)
        session.scalar.side_effect = (
            "succeeded",
            result_header,
            run,
            canonical_scenario_bytes(value),
            run,
        )
        session.scalars.side_effect = (
            licenses,
            *(streamed((header,)) for header in headers),
            tuple(ScenarioComponentModel(**row) for row in projection.components),
            tuple(ScenarioAppliedSensitivityModel(**row) for row in projection.applied_uses),
            licenses,
            *(streamed((header,)) for header in headers),
        )

        def delayed_projection(value: ScenarioCalculation, identifier: object) -> object:
            now[0] = boundary + timedelta(seconds=1)
            return projection

        monkeypatch.setattr(result_module, "normalized_scenario_result", delayed_projection)

        def read() -> ScenarioExecutionInput | ScenarioCalculation:
            return store.read_result(session, auth, root, original)

    if new_days < 30:
        with pytest.raises(ScenarioStorageError) as failure:
            read()
        assert failure.value.code is ScenarioStorageErrorCode.RUN_EXPIRED
    else:
        assert read().input_digest == original.input_digest
    assert now[0] > boundary
    assert SourceUse.STORE in requested_uses and SourceUse.DISPLAY in requested_uses
    if seam == "input":
        assert SourceUse.REPORT in requested_uses
    # Only the existing explicit scenario envelope/result query may read private bytes.
    # The new sensitivity refresh queries select permanent headers and scoped references.
    for call in session.scalars.call_args_list:
        statement = str(call.args[0])
        assert "scenario_sensitivity_version_payloads" not in statement
        assert "scenario_sensitivity_observation_payloads" not in statement
        assert "scenario_sensitivity_evidence_payloads" not in statement


def test_final_original_source_refresh_authorizes_before_selecting_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock(spec=Session)
    sources = ScenarioCopySources(
        sessions=sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: CUTOFF.value,
    )
    monkeypatch.setattr(
        ReportAuthorization, "check", Mock(side_effect=AuthorizationError("access denied"))
    )
    with pytest.raises(AuthorizationError):
        reauthorize_original_sensitivity_sources(session, authority(), uid(9960), sources)
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
